#!/usr/bin/env python3
"""Migrate utilities/workout_builder/data/{exercises,relationships}.csv into Supabase.

Populates, in order: movement_types, equipment, joints (lookups) -> exercises
(hub, with explicit CSV ids) -> exercise_loaded_joints (join, from the
semicolon-delimited loaded_joints column) -> exercise_relationships (from
relationships.csv).

All writes are upserts, so the script is safe to re-run.

Usage:
    python3 utilities/scripts/migrate_exercises_to_supabase.py [--dry-run]

Requires SUPABASE_URL and SUPABASE_KEY in the repo-root .env.
"""
import argparse
import csv
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "utilities", "workout_builder", "data")
EXERCISES_CSV = os.path.join(DATA_DIR, "exercises.csv")
RELATIONSHIPS_CSV = os.path.join(DATA_DIR, "relationships.csv")

# Printed at the end as a reminder — inserting explicit ids does not advance
# the identity sequence, so future id-less inserts could collide.
SEQUENCE_RESYNC_SQL = """\
SELECT setval(pg_get_serial_sequence('exercises', 'id'), (SELECT MAX(id) FROM exercises));
SELECT setval(pg_get_serial_sequence('exercise_relationships', 'id'), (SELECT MAX(id) FROM exercise_relationships));
"""


def _split(value):
    return [part for part in (value or "").split(";") if part]


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value, default=None):
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() == "true"


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def upsert_lookup(client, table, names):
    """Insert any names missing from `table`, return a complete name -> id map."""
    existing = client.table(table).select("id, name").execute().data
    name_to_id = {row["name"]: row["id"] for row in existing}
    missing = sorted(n for n in names if n and n not in name_to_id)
    if missing:
        inserted = client.table(table).insert([{"name": n} for n in missing]).execute().data
        for row in inserted:
            name_to_id[row["name"]] = row["id"]
    return name_to_id


def build_records(exercise_rows, relationship_rows, movement_type_ids, equipment_ids, joint_ids):
    exercise_records = []
    joint_links = []
    for row in exercise_rows:
        ex_id = _to_int(row["id"])
        exercise_records.append({
            "id": ex_id,
            "name": row["name"],
            "movement_type_id": movement_type_ids.get(row["movement_type"]),
            "orientation": row["orientation"] or None,
            "dominant": _to_bool(row["dominant"]),
            "equipment_id": equipment_ids.get(row["equipment"]),
            "min_reps": _to_int(row["min_reps"]),
            "max_reps": _to_int(row["max_reps"]),
            "avoid_if": row["avoid_if"] or None,
            "on_board": _to_bool(row["on_board"], default=True),
            "board_x": _to_float(row["board_x"]),
            "board_y": _to_float(row["board_y"]),
        })
        for joint_name in _split(row["loaded_joints"]):
            joint_links.append({"exercise_id": ex_id, "joint_id": joint_ids[joint_name]})

    relationship_records = [
        {
            "from_exercise_id": _to_int(row["from_exercise_id"]),
            "to_exercise_id": _to_int(row["to_exercise_id"]),
            "type": row["type"],
            "reason": row["reason"] or None,
        }
        for row in relationship_rows
    ]

    return exercise_records, joint_links, relationship_records


def migrate(client, dry_run):
    exercise_rows = load_csv(EXERCISES_CSV)
    relationship_rows = load_csv(RELATIONSHIPS_CSV)

    movement_types = {row["movement_type"] for row in exercise_rows if row["movement_type"]}
    equipment_names = {row["equipment"] for row in exercise_rows if row["equipment"]}
    joint_names = {j for row in exercise_rows for j in _split(row["loaded_joints"])}

    print(f"Parsed {len(exercise_rows)} exercises, {len(relationship_rows)} relationships")
    print(
        f"Lookups -> movement_types: {len(movement_types)}, "
        f"equipment: {len(equipment_names)}, joints: {len(joint_names)}"
    )

    if dry_run:
        exercise_records, joint_links, relationship_records = build_records(
            exercise_rows, relationship_rows,
            {n: None for n in movement_types}, {n: None for n in equipment_names}, {n: None for n in joint_names},
        )
        print(
            f"Dry run — would upsert {len(exercise_records)} exercises, "
            f"{len(joint_links)} exercise_loaded_joints rows, "
            f"{len(relationship_records)} exercise_relationships rows. No writes performed."
        )
        return

    movement_type_ids = upsert_lookup(client, "movement_types", movement_types)
    equipment_ids = upsert_lookup(client, "equipment", equipment_names)
    joint_ids = upsert_lookup(client, "joints", joint_names)

    exercise_records, joint_links, relationship_records = build_records(
        exercise_rows, relationship_rows, movement_type_ids, equipment_ids, joint_ids,
    )

    print(f"Upserting {len(exercise_records)} exercises...")
    client.table("exercises").upsert(exercise_records, on_conflict="id").execute()

    print(f"Upserting {len(joint_links)} exercise_loaded_joints links...")
    client.table("exercise_loaded_joints").upsert(joint_links, on_conflict="exercise_id,joint_id").execute()

    print(f"Upserting {len(relationship_records)} exercise_relationships...")
    client.table("exercise_relationships").upsert(
        relationship_records, on_conflict="from_exercise_id,to_exercise_id,type"
    ).execute()

    print("Migration complete.")
    print("\nExplicit ids were inserted into exercises/exercise_relationships — resync their")
    print("identity sequences before relying on auto-generated ids for new rows:\n")
    print(SEQUENCE_RESYNC_SQL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse CSVs and print counts without connecting to or writing to Supabase",
    )
    args = parser.parse_args()

    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not args.dry_run and not (url and key):
        sys.exit("SUPABASE_URL and SUPABASE_KEY must be set in .env")

    client = create_client(url, key) if not args.dry_run else None
    migrate(client, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
