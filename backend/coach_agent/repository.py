"""Supabase reads and writes for the AI Coach agent: everything it needs to
know about one scheduled session and its client, and the suggestion runs it
stores (coach_suggestion_runs / exercise_suggestions).

Built on an existing Supabase client (the backend's WorkoutPlanRepository
one), so it never opens a connection of its own.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

# How many earlier sessions' clarifying questions/answers, and how many
# earlier same-day sessions ("the last two weeks of this day"), it reads.
MAX_QUESTION_HISTORY_SESSIONS = 8
SAME_DAY_WEEKS = 2
# Plans walked up parent_plan_id looking for those same-day sessions.
MAX_PLAN_HOPS = 6
MAX_RECENT_COMMENTS = 40
RECENT_PERIOD_DAYS = 45

EXERCISE_FIELDS = (
    "id, name, min_reps, max_reps, is_time_based, avoid_if, orientation, dominant, "
    "movement_types(name), equipment(name), exercise_loaded_joints(joint_load, joints(name))"
)
SESSION_EXERCISE_SELECT = (
    f"id, exercise_id, category, slot_label, sets, reps, rep_range, note, skipped, skip_reason, "
    f"exercises({EXERCISE_FIELDS}), "
    "session_exercise_set_logs(set_number, completed_reps), session_exercise_rpe(rpe)"
)
HISTORY_EXERCISE_SELECT = (
    "id, exercise_id, sets, reps, skipped, exercises(name, is_time_based), "
    "session_exercise_set_logs(set_number, completed_reps), session_exercise_rpe(rpe)"
)


def _shape_question_history(
    rows: List[Dict[str, Any]], exercise_names: Dict[int, str], max_sessions: int
) -> List[Dict[str, Any]]:
    """session_clarifications rows (newest first, joined with their sessions)
    -> one entry per session, newest first, at most max_sessions, with every
    question asked across its rounds and the answer's summary (None if never
    answered). Mirrors workout_analysis_consumer.repository's copy (the two
    packages deploy separately)."""
    by_session: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        session_id = row["session_id"]
        if session_id not in by_session:
            if len(by_session) == max_sessions:
                continue
            session = row.get("sessions") or {}
            by_session[session_id] = {
                "session_id": session_id,
                "date": (session.get("completed_at") or "")[:10] or session.get("scheduled_date"),
                "day_number": session.get("day_number"),
                "rounds": [],
            }
        answers = row.get("answers") or {}
        by_session[session_id]["rounds"].append((row.get("round") or 1, [
            {
                "question": question.get("text"),
                "intent": question.get("intent"),
                "exercise": exercise_names.get(question.get("session_exercise_id")),
                "joint": question.get("joint"),
                "answer": (answers.get(question.get("id")) or {}).get("summary"),
            }
            for question in row.get("questions") or []
        ]))
    history = []
    for entry in by_session.values():
        rounds = sorted(entry.pop("rounds"), key=lambda pair: pair[0])
        entry["questions"] = [
            {**question, "follow_up": round_number > 1}
            for round_number, questions in rounds
            for question in questions
        ]
        history.append(entry)
    return history


class CoachAgentRepository:
    def __init__(self, client: Client):
        self.client = client

    # ---------- reads ----------

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """The session with its plan and its exercises (library details,
        loaded joints with load, set logs, RPE) nested."""
        rows = (
            self.client.table("sessions")
            .select(
                "id, plan_id, day_number, scheduled_date, started_at, completed_at, is_period, kind, "
                "plans(id, user_id, plan_type, parent_plan_id, completed, coach_notes, safety_summary), "
                f"session_exercises({SESSION_EXERCISE_SELECT})"
            )
            .eq("id", session_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def get_exercise_edges(self, exercise_ids: List[int]) -> List[Dict[str, Any]]:
        """Progression/regression edges out of these exercises, each with the
        target exercise's library details."""
        if not exercise_ids:
            return []
        return (
            self.client.table("exercise_relationships")
            .select(
                "from_exercise_id, type, reason, "
                f"exercises!exercise_relationships_to_exercise_id_fkey({EXERCISE_FIELDS})"
            )
            .in_("from_exercise_id", sorted(set(exercise_ids)))
            .execute()
            .data
        )

    def get_same_day_history(
        self, parent_plan_id: Optional[int], day_number: int, weeks: int = SAME_DAY_WEEKS
    ) -> List[Dict[str, Any]]:
        """The sessions for the same day_number in the previous `weeks`
        plans (walking up parent_plan_id), newest first, whatever happened
        to them (completed, missed, on her period) — with their exercises."""
        sessions = []
        plan_id = parent_plan_id
        for _ in range(MAX_PLAN_HOPS):
            if plan_id is None or len(sessions) == weeks:
                break
            rows = (
                self.client.table("sessions")
                .select(
                    "id, day_number, scheduled_date, started_at, completed_at, is_period, kind, "
                    f"plans(parent_plan_id), session_exercises({HISTORY_EXERCISE_SELECT})"
                )
                .eq("plan_id", plan_id)
                .eq("day_number", day_number)
                .execute()
                .data
            )
            plan_parent = None
            if rows:
                sessions.append(rows[0])
                plan_parent = (rows[0].get("plans") or {}).get("parent_plan_id")
            else:
                plan_rows = (
                    self.client.table("plans").select("parent_plan_id").eq("id", plan_id).execute().data
                )
                plan_parent = plan_rows[0]["parent_plan_id"] if plan_rows else None
            plan_id = plan_parent
        return sessions

    def get_client(self, user_id: str) -> Dict[str, Any]:
        """Profile row, joint pain and recent period days."""
        profile_rows = (
            self.client.table("user_profiles")
            .select("user_id, name, gender, profile")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        pain_rows = (
            self.client.table("user_joint_pain")
            .select("pain_level, updated_at, joints(name)")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        since = (date.today() - timedelta(days=RECENT_PERIOD_DAYS)).isoformat()
        period_rows = (
            self.client.table("user_period_logs")
            .select("logged_on")
            .eq("user_id", user_id)
            .gte("logged_on", since)
            .order("logged_on", desc=True)
            .execute()
            .data
        )
        return {
            "profile_row": profile_rows[0] if profile_rows else {},
            "joint_pain": [
                {"joint": row["joints"]["name"], "pain_level": row["pain_level"],
                 "updated_at": (row.get("updated_at") or "")[:10] or None}
                for row in pain_rows if row.get("joints")
            ],
            "period_days": [row["logged_on"] for row in period_rows],
        }

    def get_question_history(
        self, user_id: str, current_session_id: int, max_sessions: int = MAX_QUESTION_HISTORY_SESSIONS
    ) -> List[Dict[str, Any]]:
        rows = (
            self.client.table("session_clarifications")
            .select(
                "session_id, round, questions, answers, asked_at, "
                "sessions(day_number, scheduled_date, completed_at)"
            )
            .eq("user_id", user_id)
            .neq("session_id", current_session_id)
            .order("asked_at", desc=True)
            .limit(max_sessions * 2)
            .execute()
            .data
        )
        ids = sorted({
            q["session_exercise_id"]
            for row in rows for q in row.get("questions") or [] if q.get("session_exercise_id")
        })
        names: Dict[int, str] = {}
        if ids:
            names = {
                row["id"]: (row.get("exercises") or {}).get("name")
                for row in (
                    self.client.table("session_exercises")
                    .select("id, exercises(name)")
                    .in_("id", ids)
                    .execute()
                    .data
                )
            }
        return _shape_question_history(rows, names, max_sessions)

    def get_recent_comments(self, user_id: str, limit: int = MAX_RECENT_COMMENTS) -> List[Dict[str, Any]]:
        """Her most recent workout_comments (from voice notes and replies),
        newest first, with the exercise named and the session's date."""
        rows = (
            self.client.table("workout_comments")
            .select(
                "session_id, category, difficulty, pain_level, urgent, comment, quote, source, created_at, "
                "exercises(name), joints(name), sessions(scheduled_date, completed_at)"
            )
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )
        return [
            {
                "session_id": row["session_id"],
                "date": ((row.get("sessions") or {}).get("completed_at") or "")[:10]
                or (row.get("sessions") or {}).get("scheduled_date"),
                "exercise": (row.get("exercises") or {}).get("name"),
                "category": row.get("category"),
                "difficulty": row.get("difficulty"),
                "joint": (row.get("joints") or {}).get("name"),
                "pain_level": row.get("pain_level"),
                "urgent": row.get("urgent"),
                "comment": row.get("comment"),
                "quote": row.get("quote"),
                "source": row.get("source"),
            }
            for row in rows
        ]

    # ---------- suggestion runs ----------

    def save_run(
        self, session_id: int, user_id: str, overview: str, model: str, suggestions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Store a run and its suggestions; the session's earlier pending
        suggestions become superseded. Returns the run with its rows."""
        earlier_runs = (
            self.client.table("coach_suggestion_runs").select("id").eq("session_id", session_id).execute().data
        )
        if earlier_runs:
            (
                self.client.table("exercise_suggestions")
                .update({"status": "superseded"})
                .in_("run_id", [run["id"] for run in earlier_runs])
                .eq("status", "pending")
                .execute()
            )
        run = (
            self.client.table("coach_suggestion_runs")
            .insert({"session_id": session_id, "user_id": user_id, "overview": overview, "model": model})
            .execute()
            .data[0]
        )
        rows = []
        if suggestions:
            rows = (
                self.client.table("exercise_suggestions")
                .insert([{**suggestion, "run_id": run["id"]} for suggestion in suggestions])
                .execute()
                .data
            )
        return {**run, "exercise_suggestions": rows}

    def get_latest_run(self, session_id: int) -> Optional[Dict[str, Any]]:
        rows = (
            self.client.table("coach_suggestion_runs")
            .select("*, exercise_suggestions(*)")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def get_suggestion(self, suggestion_id: int) -> Optional[Dict[str, Any]]:
        rows = (
            self.client.table("exercise_suggestions")
            .select("*, coach_suggestion_runs(session_id, user_id)")
            .eq("id", suggestion_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def set_suggestion_status(self, suggestion_id: int, status: str) -> None:
        (
            self.client.table("exercise_suggestions")
            .update({"status": status, "decided_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", suggestion_id)
            .execute()
        )

    def get_exercises(self, exercise_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """id -> {id, name, min_reps, max_reps, is_time_based} for display."""
        if not exercise_ids:
            return {}
        rows = (
            self.client.table("exercises")
            .select("id, name, min_reps, max_reps, is_time_based")
            .in_("id", sorted(set(exercise_ids)))
            .execute()
            .data
        )
        return {row["id"]: row for row in rows}
