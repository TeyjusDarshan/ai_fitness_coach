"""Try the diet pipeline on some text or a recording without storing
anything: prints the transcript, every dish with the ingredient grams
Claude gave for her portion, and the nutrients worked out from
ingredient_nutrition_reference.

    .venv/bin/python -m diet.dry_run --text "kaalaila moonu idli, oru karandi sambar, oru tumbler coffee"
    .venv/bin/python -m diet.dry_run --audio ~/meal.webm
    .venv/bin/python -m diet.dry_run --examples          # the utterances in diet/test/utterances.py

It reads the real reference table. The Claude and Sarvam calls are real and
recorded in ai_usage as dry_run_*.
"""
import argparse
from typing import Optional

from ai_usage import set_feature_prefix
from diet.nutrition import add_totals, empty_totals, rounded
from diet.pipeline import build_item_rows, estimate
from diet.repository import DietRepository


def _line(totals) -> str:
    return (
        f"{totals['energy_kcal']} kcal · protein {totals['protein_g']} g · carbs {totals['carbs_g']} g"
        f" · fibre {totals['fibre_g']} g · fat {totals['fat_g']} g (sat {totals['saturated_fat_g']})"
    )


def run(repo: DietRepository, transcript: str, user_id: Optional[str]) -> None:
    print(f"\n=== transcript ===\n{transcript}")
    dishes, skipped = estimate(repo, transcript, user_id)
    if skipped:
        print(f"\n=== skipped ===\n{', '.join(skipped)}")
    if not dishes:
        print("\nNo food heard." if not skipped else "\nNo dishes.")
        return

    print("\n=== dishes ===")
    day = empty_totals()
    for row in build_item_rows(dishes):
        totals = rounded(row["nutrients"])
        add_totals(day, row["nutrients"])
        flags = [flag for flag in ("assumed", "needs_review") if row[flag]]
        print(
            f"- {row['dish_name']} / {row['dish_name_ta'] or '—'}: {row['quantity']:g} {row['unit']} = {row['portion_grams']} g"
            f" [{row['meal'] or 'no meal'}]{' ' + str(flags) if flags else ''}  “{row['quote']}”"
        )
        print(f"    {_line(totals)}")
        for line in row["ingredients"]:
            print(f"      {line['ingredient_name']}: {line['grams']} g")
    print(f"\n=== total ===\n{_line(rounded(day))}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="what she said, as text")
    source.add_argument("--audio", help="path to a recording (webm, m4a, ogg, mp3, wav)")
    source.add_argument("--examples", action="store_true", help="run every utterance in diet/test/utterances.py")
    parser.add_argument("--user-id", help="attribute the AI spend to this client")
    args = parser.parse_args()

    set_feature_prefix("dry_run_")
    if args.examples:
        from diet.test.utterances import UTTERANCES
        transcripts = [example["text"] for example in UTTERANCES]
    elif args.audio:
        from diet.transcription import transcribe_audio
        with open(args.audio, "rb") as recording:
            transcripts = [transcribe_audio(recording.read(), args.audio, args.user_id)]
    else:
        transcripts = [args.text]

    repo = DietRepository()
    for transcript in transcripts:
        run(repo, transcript, args.user_id)


if __name__ == "__main__":
    main()
