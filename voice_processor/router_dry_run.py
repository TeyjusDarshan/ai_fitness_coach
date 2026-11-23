"""Try the router's Claude Haiku decision without acting on it: nothing is
downloaded, stored, logged or sent (only the Claude call's cost is
recorded, as `dry_run_message_routing`).

    .venv/bin/python -m voice_processor.router_dry_run --phone 919876543210 --text "rendu idli saaptaen"
    .venv/bin/python -m voice_processor.router_dry_run --stored

--phone uses that client's real open questions and diet switch.
--stored runs every transcript already in the database — WhatsApp replies
(clarification_replies, expected `question_reply`, with the questions she
was answering) and app food recordings (meal_logs, expected
`diet_checkin`) — and prints how many came out as expected.
"""
import argparse
import json
from typing import Any, Dict, List, Optional

from ai_usage import set_feature_prefix
from diet.dates import app_now
from voice_processor import router_agent
from voice_processor.repository import AnalysisRepository
from voice_processor.router import _minutes_since, allowed_labels
from voice_processor.router_agent import DIET_CHECKIN, OTHER, QUESTION_REPLY


def _run(text: str, labels: List[str], questions: Optional[List[Dict[str, Any]]], minutes: Optional[int],
         user_id: Optional[str], verbose: bool) -> str:
    payload = router_agent.build_payload(text, "audio", labels, app_now(), questions, minutes)
    if verbose:
        print("--- payload ---")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    decision = router_agent.classify_message(payload, user_id=user_id)
    print(f"-> {decision.label} ({decision.day}): {decision.reason}")
    return decision.label


def _stored(repo: AnalysisRepository) -> None:
    client = repo.client
    replies = (
        client.table("clarification_replies")
        .select("text, transcript, session_clarifications(user_id, questions)")
        .execute().data
    )
    meals = client.table("meal_logs").select("user_id, transcript").not_.is_("transcript", "null").execute().data
    cases = [
        (r.get("transcript") or r.get("text"), QUESTION_REPLY, (r.get("session_clarifications") or {}).get("questions"),
         (r.get("session_clarifications") or {}).get("user_id"))
        for r in replies if r.get("transcript") or r.get("text")
    ] + [(m["transcript"], DIET_CHECKIN, None, m["user_id"]) for m in meals if m["transcript"]]

    hits = 0
    for text, expected, questions, user_id in cases:
        print(f"\n[{expected}] {text}")
        # As in production: food can be logged, and replies are only
        # possible while questions are open (here: the round she answered).
        labels = allowed_labels(bool(questions), True)
        label = _run(text, labels, questions, 60 if questions else None, user_id, verbose=False)
        hits += label == expected
    print(f"\n{hits}/{len(cases)} routed as expected")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phone", help="sender, e.g. 919876543210")
    parser.add_argument("--text", action="append", help="message (repeatable)")
    parser.add_argument("--stored", action="store_true", help="run every stored reply and meal transcript")
    args = parser.parse_args()

    set_feature_prefix("dry_run_")
    repo = AnalysisRepository()
    if args.stored:
        return _stored(repo)
    if not (args.phone and args.text):
        parser.error("--phone and --text, or --stored")

    profile = repo.get_profile_for_routing(args.phone.lstrip("+"))
    if profile is None:
        parser.error(f"no client for {args.phone}")
    clarification = repo.find_open_clarification(args.phone)
    labels = allowed_labels(clarification is not None, bool(profile.get("diet_enabled")))
    print(f"client {profile['user_id']} — allowed labels: {labels}")
    for text in args.text:
        print(f"\n{text}")
        if labels == [OTHER]:
            print("-> other (no open questions, diet tracking off; Claude not asked)")
            continue
        _run(text, labels, (clarification or {}).get("questions"),
             _minutes_since((clarification or {}).get("asked_at")), profile["user_id"], verbose=True)


if __name__ == "__main__":
    main()
