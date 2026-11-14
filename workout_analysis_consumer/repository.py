import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

# session_exercises for one session (training day), joined with the
# exercise's name/movement type, its per-set completion logs, and its RPE.
SESSION_EXERCISE_JOIN = (
    "id, exercise_id, category, slot_label, sets, reps, rep_range, note, feedback_audio_path, "
    "exercises(name, is_time_based, movement_types(name)), "
    "session_exercise_set_logs(set_number, completed_reps), "
    "session_exercise_rpe(rpe)"
)

# A cardio session's level and rating (sessions.kind = 'cardio'; see
# backend/cardio.py). It has no session_exercises: the client follows the
# whole cardio_exercises circuit for `cardio_rounds` rounds.
CARDIO_SESSION_FIELDS = "kind, cardio_rounds, cardio_work_seconds, cardio_rating"

# How many plans back _fetch_previous_session_context looks for a completed
# same-day session when the most recent ones were missed.
MAX_PREVIOUS_PLAN_HOPS = 4

# How many earlier sessions' clarifying questions and answers the summary
# (and follow-up questions) get as context.
MAX_QUESTION_HISTORY_SESSIONS = 8


def _shape_question_history(
    rows: List[Dict[str, Any]], exercise_names: Dict[int, str], max_sessions: int
) -> List[Dict[str, Any]]:
    """session_clarifications rows (newest first, joined with their
    sessions) -> one entry per session, newest first, at most max_sessions:
    every question asked across its rounds, with the exercise named and the
    answer's summary (None when she never answered it)."""
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
                "workout_type": session.get("kind") or "strength",
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


# The app's RPE input only ever logs one of 3 values, matching
# backend/repository/workout_plan_repository.py's Easy/Medium/Hard = 6/8/10
# (PROGRESSION_TARGET_RPE=8 is the intended/ideal effort). Computed here
# rather than left for the LLM to infer, since a generic RPE scale would
# read 8 as already hard rather than as this app's target.
def _effort_flag(rpe):
    if rpe == 6:
        return "too_easy"
    if rpe == 10:
        return "too_difficult"
    return None


def _shape_exercise_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Shared shaping for session_exercises rows joined via
    SESSION_EXERCISE_JOIN, used for both the current session and the
    same-day session from the parent plan.
    """
    return [
        {
            "session_exercise_id": row["id"],
            "exercise_id": row.get("exercise_id"),
            "name": row["exercises"]["name"],
            "movement_type": (row["exercises"].get("movement_types") or {}).get("name"),
            "slot": row.get("slot_label"),
            # Timed holds (e.g. planks): prescribed_reps and completed_reps are seconds.
            "unit": "seconds" if row["exercises"].get("is_time_based") else "reps",
            "prescribed_sets": row.get("sets"),
            "prescribed_reps": row.get("reps"),
            "rep_range": row.get("rep_range"),
            "set_logs": sorted(
                (row.get("session_exercise_set_logs") or []),
                key=lambda log: log["set_number"],
            ),
            "rpe": (row.get("session_exercise_rpe") or {}).get("rpe"),
            "effort_flag": _effort_flag((row.get("session_exercise_rpe") or {}).get("rpe")),
        }
        for row in rows
    ]


# Mirrors backend/cardio.py: on her period each exercise runs 70% of its
# planned seconds (at least 15) — the stored cardio_work_seconds is the plan.
CARDIO_PERIOD_FACTOR = 0.7
CARDIO_MIN_SECONDS = 15


def _cardio_work_seconds(session: Dict[str, Any]) -> int:
    """Seconds per exercise she actually did in a cardio session."""
    seconds = session.get("cardio_work_seconds") or 0
    if session.get("is_period") and seconds:
        return max(CARDIO_MIN_SECONDS, round(seconds * CARDIO_PERIOD_FACTOR))
    return seconds


def _cardio_volume(session: Dict[str, Any]) -> int:
    """Seconds of work per exercise across all rounds of a cardio session."""
    return (session.get("cardio_rounds") or 0) * _cardio_work_seconds(session)


def _compare(total: int, previous_total: Optional[int]) -> Optional[str]:
    if previous_total is None:
        return None
    return "more" if total > previous_total else "less" if total < previous_total else "same"


def _total_done(exercise: Dict[str, Any]) -> int:
    return sum(log.get("completed_reps") or 0 for log in exercise["set_logs"])


def _compare_to_last_time(
    exercises: List[Dict[str, Any]], previous_exercises: List[Dict[str, Any]]
) -> None:
    """Set each exercise's "compared_to_last_time" to "more", "less" or
    "same": its total reps (or seconds, for a timed hold) completed across
    all sets against the same exercise, matched by name, in the previous
    session. None when it wasn't done last time (e.g. swapped in since).
    Computed here so the summary's comparison doesn't rely on the LLM
    adding up set logs.
    """
    previous_totals = {exercise["name"]: _total_done(exercise) for exercise in previous_exercises}
    for exercise in exercises:
        previous_total = previous_totals.get(exercise["name"])
        if previous_total is None:
            exercise["compared_to_last_time"] = None
            continue
        total = _total_done(exercise)
        exercise["compared_to_last_time"] = (
            "more" if total > previous_total else "less" if total < previous_total else "same"
        )


class AnalysisRepository:
    """Reads the Supabase data needed to summarize one workout session, and
    persists the generated summary to session_analysis.
    """

    def __init__(self, client: Optional[Client] = None):
        if client is not None:
            self.client = client
        else:
            url = os.environ["SUPABASE_URL"]
            key = os.environ["SUPABASE_KEY"]
            self.client = create_client(url, key)

    def fetch_context(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Gather everything needed to summarize this session (one training
        day of a plan): the prescribed exercises with their set logs and RPE,
        the client's profile, and any joint pain they've reported. Returns
        None if the session doesn't exist.

        Also carries the session's feedback_audio_path (None if the client
        recorded no voice feedback), for the caller to transcribe — it is a
        storage path, not something to send to the LLM.
        """
        sessions = (
            self.client.table("sessions")
            .select(
                f"id, day_number, plan_id, is_period, feedback_audio_path, {CARDIO_SESSION_FIELDS}, "
                "plans(user_id, plan_type, parent_plan_id)"
            )
            .eq("id", session_id)
            .execute()
            .data
        )
        if not sessions:
            return None
        session = sessions[0]
        plan = session["plans"]
        user_id = plan["user_id"]
        day_number = session["day_number"]

        exercise_rows = (
            self.client.table("session_exercises")
            .select(SESSION_EXERCISE_JOIN)
            .eq("session_id", session_id)
            .order("id")
            .execute()
            .data
        )

        profile_rows = (
            self.client.table("user_profiles")
            .select("profile, name")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        profile = profile_rows[0]["profile"] if profile_rows else None
        client_name = profile_rows[0].get("name") if profile_rows else None

        joint_pain_rows = (
            self.client.table("user_joint_pain")
            .select("pain_level, joints(name)")
            .eq("user_id", user_id)
            .execute()
            .data
        )

        context = {
            "session_id": session_id,
            "plan_id": session["plan_id"],
            "day_number": day_number,
            "user_id": user_id,
            "client_name": client_name,
            "plan_type": plan["plan_type"],
            "is_period": bool(session.get("is_period")),
            "feedback_audio_path": session.get("feedback_audio_path"),
            "user_profile": profile,
            "joint_pain": [
                {"joint": row["joints"]["name"], "pain_level": row["pain_level"]}
                for row in joint_pain_rows
                if row.get("joints")
            ],
            "exercises": _shape_exercise_rows(exercise_rows),
        }

        previous_session = None
        if plan.get("parent_plan_id") is not None:
            previous_session = self._fetch_previous_session_context(plan["parent_plan_id"], day_number)
            context["previous_session"] = previous_session
        _compare_to_last_time(
            context["exercises"], previous_session["exercises"] if previous_session else []
        )
        # New this week: not in the last same-day session (swapped or
        # progressed in), so the clarifying questions can ask how it felt.
        # Everything is new in a client's first plan.
        for exercise in context["exercises"]:
            exercise["is_new"] = previous_session is None or exercise["compared_to_last_time"] is None
        # session_exercise_id -> its voice note's storage path, for the
        # caller to transcribe (not something to send to the LLM).
        context["exercise_feedback_audio_paths"] = {
            row["id"]: row["feedback_audio_path"]
            for row in exercise_rows
            if row.get("feedback_audio_path")
        }

        if session.get("kind") == "cardio":
            context["workout_type"] = "cardio"
            context["cardio"] = {
                "circuit": self._fetch_cardio_circuit(),
                "rounds": session.get("cardio_rounds"),
                "seconds_per_exercise": _cardio_work_seconds(session),
                "rating": session.get("cardio_rating"),
                # Total time on each exercise against the last cardio session
                # on this day of the week, worked out here rather than by the LLM.
                "compared_to_last_time": _compare(
                    _cardio_volume(session),
                    previous_session.get("cardio_volume") if previous_session else None,
                ),
            }

        return context

    def _fetch_cardio_circuit(self) -> List[str]:
        """The names of the active cardio_exercises, in circuit order."""
        rows = (
            self.client.table("cardio_exercises")
            .select("name, position")
            .eq("active", True)
            .order("position")
            .execute()
            .data
        )
        return [row["name"] for row in sorted(rows, key=lambda row: row["position"])]

    def _fetch_previous_session_context(self, parent_plan_id: int, day_number: int) -> Optional[Dict[str, Any]]:
        """The most recent earlier session for the same day_number as the
        current analysis that the client actually completed outside a period, so the LLM can
        compare like for like (same split day). Starts at the parent plan and
        walks further up parent_plan_id (at most MAX_PREVIOUS_PLAN_HOPS plans)
        past missed sessions, which have no logs to compare against. None if
        no such session is found.
        """
        plan_id = parent_plan_id
        for _ in range(MAX_PREVIOUS_PLAN_HOPS):
            if plan_id is None:
                return None
            sessions = (
                self.client.table("sessions")
                .select(
                    f"id, started_at, completed_at, is_period, {CARDIO_SESSION_FIELDS}, plans(parent_plan_id), "
                    f"session_exercises({SESSION_EXERCISE_JOIN})"
                )
                .eq("plan_id", plan_id)
                .eq("day_number", day_number)
                .execute()
                .data
            )
            if not sessions:
                return None
            session = sessions[0]
            # A period session ran at reduced reps, so it's no fair comparison.
            if session.get("completed_at") and not session.get("is_period"):
                break
            plan_id = (session.get("plans") or {}).get("parent_plan_id")
        else:
            return None
        return {
            "session_id": session["id"],
            "plan_id": plan_id,
            "started_at": session.get("started_at"),
            "completed_at": session.get("completed_at"),
            "exercises": _shape_exercise_rows(
                sorted(session.get("session_exercises") or [], key=lambda row: row["id"])
            ),
            **(
                {"cardio_volume": _cardio_volume(session), "cardio_rating": session.get("cardio_rating")}
                if session.get("kind") == "cardio" else {}
            ),
        }

    def save_analysis(self, session_id: int, analysis: str, audio_url: Optional[str] = None) -> dict:
        """Upsert keyed by session_id, so redelivering an already-processed
        message overwrites rather than duplicates.

        audio_url is omitted from the payload (rather than sent as None) when
        not given, so a redelivery whose voice-note generation fails doesn't
        null out audio_url from an earlier successful attempt.
        """
        row = {"session_id": session_id, "analysis": analysis}
        if audio_url is not None:
            row["audio_url"] = audio_url
        result = (
            self.client.table("session_analysis")
            .upsert(row, on_conflict="session_id")
            .execute()
            .data
        )
        return result[0]

    # --- Voice-feedback agent: comments, joint pain, clarifying questions ---

    def list_joints(self) -> Dict[str, int]:
        """joint name -> id, from the joints lookup table."""
        rows = self.client.table("joints").select("id, name").execute().data
        return {row["name"]: row["id"] for row in rows}

    def replace_voice_note_comments(
        self, user_id: str, session_id: int, rows: List[Dict[str, Any]]
    ) -> None:
        """Replace this session's voice-note workout_comments with rows, so a
        redelivered workout-complete event doesn't duplicate them. Comments
        from clarification replies are left alone."""
        (
            self.client.table("workout_comments")
            .delete()
            .eq("session_id", session_id)
            .in_("source", ["session_voice_note", "exercise_voice_note"])
            .execute()
        )
        self.insert_comments(user_id, session_id, rows)

    def insert_comments(self, user_id: str, session_id: int, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        self.client.table("workout_comments").insert(
            [{**row, "user_id": user_id, "session_id": session_id} for row in rows]
        ).execute()

    def apply_joint_pain(self, user_id: str, changes: Dict[int, Optional[str]]) -> None:
        """Write joint_id -> pain_level changes to user_joint_pain: a level
        overwrites what's on file (upsert on the (user_id, joint_id) unique
        key, as WorkoutPlanRepository.upsert_joint_pain does), None deletes
        the row (the client said the pain is gone)."""
        now = datetime.now(timezone.utc).isoformat()
        upserts = [
            {"user_id": user_id, "joint_id": joint_id, "pain_level": level, "updated_at": now}
            for joint_id, level in changes.items()
            if level is not None
        ]
        if upserts:
            self.client.table("user_joint_pain").upsert(upserts, on_conflict="user_id,joint_id").execute()
        cleared = [joint_id for joint_id, level in changes.items() if level is None]
        if cleared:
            (
                self.client.table("user_joint_pain")
                .delete()
                .eq("user_id", user_id)
                .in_("joint_id", cleared)
                .execute()
            )

    def supersede_open_clarifications(self, phone_number: str, except_session_id: int) -> None:
        """Close any questions still open for this phone from an earlier
        session: replies from now on belong to the newest workout."""
        (
            self.client.table("session_clarifications")
            .update({"status": "superseded", "closed_at": datetime.now(timezone.utc).isoformat()})
            .eq("phone_number", phone_number)
            .eq("status", "open")
            .neq("session_id", except_session_id)
            .execute()
        )

    def save_clarification(
        self,
        session_id: int,
        user_id: str,
        phone_number: str,
        round_number: int,
        questions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Open a round of questions for the session (upsert on
        (session_id, round), with a fresh 24-hour window). If that round
        already has replies — a redelivered event — it's returned unchanged,
        so the questions she is answering aren't swapped out under her."""
        existing = (
            self.client.table("session_clarifications")
            .select("*, clarification_replies(id)")
            .eq("session_id", session_id)
            .eq("round", round_number)
            .execute()
            .data
        )
        if existing and existing[0].get("clarification_replies"):
            row = existing[0]
            row.pop("clarification_replies", None)
            return row
        now = datetime.now(timezone.utc)
        return (
            self.client.table("session_clarifications")
            .upsert(
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "phone_number": phone_number,
                    "round": round_number,
                    "questions": questions,
                    "answers": {},
                    "status": "open",
                    "asked_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=24)).isoformat(),
                    "closed_at": None,
                },
                on_conflict="session_id,round",
            )
            .execute()
            .data[0]
        )

    def find_open_clarification(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """The latest open round of questions for this phone, or None. Open
        rounds past their 24-hour window are marked expired on the way."""
        rows = (
            self.client.table("session_clarifications")
            .select("*")
            .eq("phone_number", phone_number)
            .eq("status", "open")
            .order("asked_at", desc=True)
            .execute()
            .data
        )
        now = datetime.now(timezone.utc)
        current = None
        for row in rows:
            if datetime.fromisoformat(row["expires_at"]) <= now:
                self.update_clarification(row["id"], {"status": "expired", "closed_at": now.isoformat()})
            elif current is None:
                current = row
        return current

    def update_clarification(self, clarification_id: int, fields: Dict[str, Any]) -> None:
        self.client.table("session_clarifications").update(fields).eq("id", clarification_id).execute()

    def record_reply(
        self, clarification_id: int, whatsapp_message_id: str, message_type: str, text: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """The clarification_replies row for an inbound WhatsApp message,
        created if new. None when that message was already processed (Meta
        or Kafka redelivering it)."""
        existing = (
            self.client.table("clarification_replies")
            .select("*")
            .eq("whatsapp_message_id", whatsapp_message_id)
            .execute()
            .data
        )
        if existing:
            return None if existing[0].get("processed_at") else existing[0]
        return (
            self.client.table("clarification_replies")
            .insert({
                "clarification_id": clarification_id,
                "whatsapp_message_id": whatsapp_message_id,
                "message_type": message_type,
                "text": text,
            })
            .execute()
            .data[0]
        )

    def update_reply(self, reply_id: int, fields: Dict[str, Any]) -> None:
        self.client.table("clarification_replies").update(fields).eq("id", reply_id).execute()

    def list_processed_reply_texts(self, clarification_id: int) -> List[str]:
        """What she already replied to this round, oldest first."""
        rows = (
            self.client.table("clarification_replies")
            .select("text, transcript, created_at")
            .eq("clarification_id", clarification_id)
            .not_.is_("processed_at", "null")
            .order("created_at")
            .execute()
            .data
        )
        return [row.get("transcript") or row.get("text") for row in rows if row.get("transcript") or row.get("text")]

    def fetch_question_history(
        self, user_id: str, current_session_id: int, max_sessions: int = MAX_QUESTION_HISTORY_SESSIONS
    ) -> List[Dict[str, Any]]:
        """The clarifying questions asked after her last max_sessions
        workouts that had any (current session excluded), with her answers —
        newest first. See _shape_question_history."""
        rows = (
            self.client.table("session_clarifications")
            .select(
                "session_id, round, questions, answers, asked_at, "
                "sessions(day_number, scheduled_date, completed_at, kind)"
            )
            .eq("user_id", user_id)
            .neq("session_id", current_session_id)
            .order("asked_at", desc=True)
            # At most two rounds (questions + follow-ups) per session.
            .limit(max_sessions * 2)
            .execute()
            .data
        )
        session_exercise_ids = sorted({
            question["session_exercise_id"]
            for row in rows
            for question in row.get("questions") or []
            if question.get("session_exercise_id")
        })
        exercise_names: Dict[int, str] = {}
        if session_exercise_ids:
            exercise_rows = (
                self.client.table("session_exercises")
                .select("id, exercises(name)")
                .in_("id", session_exercise_ids)
                .execute()
                .data
            )
            exercise_names = {
                row["id"]: (row.get("exercises") or {}).get("name") for row in exercise_rows
            }
        return _shape_question_history(rows, exercise_names, max_sessions)
