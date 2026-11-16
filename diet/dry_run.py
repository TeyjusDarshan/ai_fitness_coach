"""Try the diet pipeline on some text or a recording without storing
anything: prints the transcript, the items heard, any dish and ingredient
that would be added, and the nutrients.

    .venv/bin/python -m diet.dry_run --text "kaalaila moonu idli, oru karandi sambar, oru tumbler coffee"
    .venv/bin/python -m diet.dry_run --audio ~/meal.webm
    .venv/bin/python -m diet.dry_run --examples          # the utterances in diet/test/utterances.py

It reads the real dishes and ingredients (and, with --user-id, her own
recipe versions), so a dish already in the table is used as stored. The
Claude and Sarvam calls are real and recorded in ai_usage as dry_run_*.
"""
import argparse
import json
from typing import Any, Dict, Iterable, List, Optional

from ai_usage import set_feature_prefix
from diet.nutrition import nutrients_of, rounded
from diet.pipeline import add_unknown_dishes, build_item_rows, parse_transcript
from diet.repository import DietRepository


class DryRunRepository(DietRepository):
    """Reads the real tables; anything that would be written is kept in
    memory instead (new dishes and ingredients get negative ids)."""

    def __init__(self):
        super().__init__()
        self.new_foods: Dict[int, Dict[str, Any]] = {}
        self.new_ingredients: Dict[int, Dict[str, Any]] = {}
        self.new_portions: List[Dict[str, Any]] = []

    def insert_ingredient(self, row, model):
        ingredient_id = -(len(self.new_ingredients) + 1)
        self.new_ingredients[ingredient_id] = {**row, "id": ingredient_id}
        return ingredient_id, True

    def insert_food(self, dish, model, meal_log_id):
        food_id = -(len(self.new_foods) + 1)
        self.new_foods[food_id] = {**dish, "id": food_id}
        return food_id, True

    def upsert_portion(self, food_id, unit, grams, source="ai_estimate"):
        self.new_portions.append({"food_id": food_id, "unit": unit, "grams": grams})

    def get_foods(self, food_ids: Iterable[int]):
        ids = [food_id for food_id in food_ids if food_id is not None]
        foods = super().get_foods(food_id for food_id in ids if food_id > 0)
        for portion in self.new_portions:
            if portion["food_id"] in foods:
                foods[portion["food_id"]]["portions"][portion["unit"]] = portion["grams"]
        foods.update({food_id: self.new_foods[food_id] for food_id in ids if food_id in self.new_foods})
        return foods

    def ingredients_by_id(self, ingredient_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
        ids = sorted({ingredient_id for ingredient_id in ingredient_ids if ingredient_id > 0})
        stored = self.client.table("ingredients").select("*").in_("id", ids).execute().data if ids else []
        return {**{row["id"]: row for row in stored}, **self.new_ingredients}


def run(repo: DryRunRepository, transcript: str, user_id: Optional[str]) -> None:
    print(f"\n=== transcript ===\n{transcript}")
    items = parse_transcript(repo, transcript, user_id)
    if not items:
        print("\nNo food heard.")
        return
    add_unknown_dishes(repo, items, user_id, None)
    rows = build_item_rows(repo, items, user_id or "")
    ingredients = repo.ingredients_by_id(
        line["ingredient_id"] for row in rows for line in row["ingredients"]
    )

    print("\n=== items ===")
    for row in rows:
        lines = [{**line, "ingredient": ingredients.get(line["ingredient_id"], {})} for line in row["ingredients"]]
        totals = rounded(nutrients_of(lines))
        flags = [flag for flag in ("assumed", "needs_review", "used_own_recipe") if row[flag]]
        print(
            f"- {row['food_name']}: {row['quantity']:g} {row['unit']} = {row['grams']} g"
            f" [{row['meal'] or 'no meal'}]{' ' + str(flags) if flags else ''}  “{row['quote']}”"
        )
        print(
            f"    {totals['energy_kcal']} kcal · protein {totals['protein_g']} g · carbs {totals['carbs_g']} g"
            f" · fibre {totals['fibre_g']} g · fat {totals['fat_g']} g"
            f" (sat {totals['saturated_fat_g']}, unsat {totals['unsaturated_fat_g']})"
        )
        for line in lines:
            print(f"      {line['ingredient'].get('name', '?')}: {line['grams']} g")

    if repo.new_foods:
        print("\n=== dishes that would be added ===")
        print(json.dumps(list(repo.new_foods.values()), indent=2, ensure_ascii=False))
    if repo.new_ingredients:
        print("\n=== ingredients that would be added ===")
        print(json.dumps(list(repo.new_ingredients.values()), indent=2, ensure_ascii=False))
    if repo.new_portions:
        print("\n=== unit weights that would be added ===")
        print(json.dumps(repo.new_portions, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="what she said, as text")
    source.add_argument("--audio", help="path to a recording (webm, m4a, ogg, mp3, wav)")
    source.add_argument("--examples", action="store_true", help="run every utterance in diet/test/utterances.py")
    parser.add_argument("--user-id", help="use this client's own recipe versions")
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

    for transcript in transcripts:
        # A fresh one each time, so every example starts from the stored tables.
        run(DryRunRepository(), transcript, args.user_id)


if __name__ == "__main__":
    main()
