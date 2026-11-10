import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

# session_exercises for one session (training day), joined with the
# exercise's name/movement type, its per-set completion logs, and its RPE.
SESSION_EXERCISE_JOIN = (
    "id, category, slot_label, sets, reps, rep_range, note, "
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
