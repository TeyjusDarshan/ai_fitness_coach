"""Checks the AI Coach agent's suggestions against the database facts
(context.build_context) before anything is stored or shown. Pure — no I/O.

Each output row is an exercise_suggestions row minus run_id: a suggestion
the coach can accept ("pending") or one that changes nothing ("no_change").
"""
import re
from typing import Any, Dict, List, Optional

# Bounds on a suggested prescription (the admin editor allows up to 10 sets;
# the agent is held to a tighter, realistic range).
MIN_SETS, MAX_SETS = 1, 6
MAX_TARGET = 600

CLIENT_SOURCES = {"client_answer", "client_comment"}
DIRECTIONS = {"progress": "progression", "regress": "regression"}

_PUNCTUATION_RE = re.compile(r"[\s.,!?;:\"'“”‘’…\-()\[\]]+")


def _normalize(text: str) -> str:
    return _PUNCTUATION_RE.sub(" ", (text or "").casefold()).strip()


def quote_found(quote: str, texts: List[str]) -> bool:
    """Whether quote occurs in any of texts (case, punctuation and spacing
    ignored)."""
    needle = _normalize(quote)
    return bool(needle) and any(needle in _normalize(text) for text in texts)


def stored_reps(reps: List[int]) -> str:
    """Per-set targets as session_exercises.reps stores them: one number when
    every set matches, else a comma list (as the admin editor writes them)."""
    return str(reps[0]) if len(set(reps)) == 1 else ",".join(str(r) for r in reps)


def _within(reps: List[int], low: Optional[int], high: Optional[int]) -> bool:
    low = low if low is not None else 1
    high = high if high is not None else MAX_TARGET
    return all(isinstance(r, int) and low <= r <= high for r in reps)


def _evidence(items, client_texts: List[str]) -> List[Dict[str, Any]]:
    """Keep data evidence (labelled unverified, it's a statement about the
    data), and client quotes only when they really appear in her answers or
    comments."""
    kept = []
    for item in items or []:
        quote = (item.quote or "").strip()
        if not quote:
            continue
        if item.source in CLIENT_SOURCES:
            if not quote_found(quote, client_texts):
                continue
            verified = True
        else:
            verified = False
        kept.append({"source": item.source, "quote": quote, "session_id": item.session_id, "verified": verified})
    return kept


def _keep(facts: Dict[str, Any], reason: str, evidence=None) -> Dict[str, Any]:
    return {
        "session_exercise_id": facts["session_exercise_id"],
        "action": "keep",
        "proposed_sets": None,
        "proposed_reps": None,
        "proposed_exercise_id": None,
        "before": _before(facts),
        "reason": reason,
        "evidence": evidence or [],
        "status": "no_change",
    }


def _before(facts: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "exercise_id": facts["exercise_id"],
        "name": facts["name"],
        "sets": facts["sets"],
        "reps": facts["reps_stored"],
    }


def validate_suggestions(suggestions, facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per actionable exercise, in the session's order. Anything
    invalid falls back to "keep" with the reason saying why, so the coach
    always sees every exercise."""
    exercises = facts["exercises"]
    by_id: Dict[int, Any] = {}
    for suggestion in suggestions:
        if suggestion.session_exercise_id in exercises and suggestion.session_exercise_id not in by_id:
            by_id[suggestion.session_exercise_id] = suggestion

    rows = []
    for session_exercise_id, ex in exercises.items():
        if not ex["actionable"]:
            continue
        suggestion = by_id.get(session_exercise_id)
        if suggestion is None:
            rows.append(_keep(ex, "No suggestion from the AI coach for this exercise."))
            continue
        rows.append(_validate_one(suggestion, ex, facts["client_texts"]))
    return rows


def _validate_one(suggestion, ex: Dict[str, Any], client_texts: List[str]) -> Dict[str, Any]:
    reason = (suggestion.reason or "").strip()
    evidence = _evidence(suggestion.evidence, client_texts)
    action = suggestion.action

    def rejected(why: str) -> Dict[str, Any]:
        return _keep(ex, f"[AI suggestion '{action}' not valid: {why}] {reason}".strip(), evidence)

    if action == "keep":
        return _keep(ex, reason or "No change needed.", evidence)
    if not reason:
        return rejected("no reason given")
    if not evidence:
        return rejected("no verifiable evidence")

    row = {
        "session_exercise_id": ex["session_exercise_id"],
        "action": action,
        "proposed_sets": None,
        "proposed_reps": None,
        "proposed_exercise_id": None,
        "before": _before(ex),
        "reason": reason,
        "evidence": evidence,
        "status": "pending",
    }

    if action == "skip":
        return row

    if action == "adjust":
        sets = suggestion.sets if suggestion.sets is not None else ex["sets"]
        reps = list(suggestion.reps or [])
        if not isinstance(sets, int) or not MIN_SETS <= sets <= MAX_SETS:
            return rejected(f"sets must be {MIN_SETS}-{MAX_SETS}")
        if len(reps) == 1 and sets > 1:
            reps = reps * sets
        if len(reps) != sets:
            return rejected("one target per set is needed")
        if not _within(reps, ex["min"], ex["max"]):
            return rejected(f"targets must be within {ex['min']}-{ex['max']}")
        if sets == ex["sets"] and reps == ex["reps"]:
            return _keep(ex, reason, evidence)
        row.update({"proposed_sets": sets, "proposed_reps": stored_reps(reps)})
        return row

    if action in DIRECTIONS:
        options = ex["options"][DIRECTIONS[action]]
        target = options.get(suggestion.to_exercise_id)
        if target is None:
            return rejected(f"not one of this exercise's {DIRECTIONS[action]} options")
        sets = suggestion.sets if suggestion.sets is not None else ex["sets"]
        if not isinstance(sets, int) or not MIN_SETS <= sets <= MAX_SETS:
            return rejected(f"sets must be {MIN_SETS}-{MAX_SETS}")
        reps = list(suggestion.reps or [])
        if not reps:
            start = target["min"] if action == "progress" else target["max"]
            if start is None:
                return rejected("no targets given and the new exercise has no rep range")
            reps = [start] * sets
        if len(reps) == 1 and sets > 1:
            reps = reps * sets
        if len(reps) != sets:
            return rejected("one target per set is needed")
        if not _within(reps, target["min"], target["max"]):
            return rejected(f"targets must be within {target['min']}-{target['max']} for {target['name']}")
        row.update({
            "proposed_sets": sets,
            "proposed_reps": stored_reps(reps),
            "proposed_exercise_id": target["exercise_id"],
        })
        return row

    return rejected("unknown action")
