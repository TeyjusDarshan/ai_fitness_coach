#!/usr/bin/env python3
"""Workout Builder utility — exercise creator + drag-and-drop relationship board.

Run from the repo root with the project venv (it needs `supabase`):

    .venv/bin/python utilities/workout_builder/app.py   then open http://localhost:8765

Reads and writes the exercise library directly in Supabase (SUPABASE_URL /
SUPABASE_KEY from the repo's .env): `exercises`, `exercise_loaded_joints`
and `exercise_relationships`, plus the `movement_types` / `equipment`
lookups. The page saves its whole state on every change; the server diffs
it against what it last loaded or saved and writes only what changed.
"""
import copy
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import create_client

load_dotenv()

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE, "static")
PORT = 8765

JOINT_LOADS = ("high", "mid", "low", "nil")
DEFAULT_JOINT_LOAD = "mid"
RELATIONSHIP_TYPES = ("progression", "regression")

EXERCISE_SELECT = (
    "id, name, orientation, dominant, min_reps, max_reps, is_time_based, avoid_if, "
    "on_board, board_x, board_y, movement_types(name), equipment(name), "
    "exercise_loaded_joints(joint_load, joints(name))"
)


class SaveRefused(Exception):
    """A change Supabase won't accept, explained for the person editing."""


def _split(value):
    return [part for part in (value or "").split(";") if part]


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class LibraryStore:
    """The exercise library in Supabase, in the board's JSON shape:

    exercises: {id, name, movement_type, orientation, dominant, equipment: [name],
                loaded_joints: [name], joint_loads: {joint: high|mid|low|nil},
                min_reps, max_reps, is_time_based, avoid_if, on_board, board_x, board_y}
    relationships: {id, from_exercise_id, to_exercise_id, type, reason: [str]}

    `equipment` is a list for the board's form, but the table holds one
    equipment per exercise, so only the first is stored.
    """

    def __init__(self):
        self.client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        self._lock = threading.Lock()
        self._snapshot = None

    # ---------- reading ----------

    def load(self):
        with self._lock:
            self._snapshot = self._read()
            return copy.deepcopy(self._snapshot)

    def _read(self):
        rows = self.client.table("exercises").select(EXERCISE_SELECT).order("id").execute().data
        exercises = []
        for row in rows:
            joint_loads = {
                link["joints"]["name"]: link.get("joint_load") or DEFAULT_JOINT_LOAD
                for link in row.get("exercise_loaded_joints") or []
                if link.get("joints")
            }
            exercises.append({
                "id": row["id"],
                "name": row.get("name") or "",
                "movement_type": (row.get("movement_types") or {}).get("name") or "",
                "orientation": row.get("orientation") or "",
                "dominant": bool(row.get("dominant")),
                "equipment": [row["equipment"]["name"]] if row.get("equipment") else [],
                "loaded_joints": sorted(joint_loads),
                "joint_loads": joint_loads,
                "min_reps": row.get("min_reps"),
                "max_reps": row.get("max_reps"),
                "is_time_based": bool(row.get("is_time_based")),
                "avoid_if": row.get("avoid_if") or "",
                "on_board": bool(row.get("on_board")),
                "board_x": round(_to_float(row.get("board_x")), 1),
                "board_y": round(_to_float(row.get("board_y")), 1),
            })
        rels = (
            self.client.table("exercise_relationships")
            .select("id, from_exercise_id, to_exercise_id, type, reason")
            .order("id")
            .execute()
            .data
        )
        relationships = [
            {
                "id": rel["id"],
                "from_exercise_id": rel["from_exercise_id"],
                "to_exercise_id": rel["to_exercise_id"],
                "type": rel["type"],
                "reason": _split(rel.get("reason")),
            }
            for rel in rels
        ]
        return {"exercises": exercises, "relationships": relationships}

    # ---------- writing ----------

    def save(self, state):
        """Write the difference between `state` and the last loaded/saved
        state. Exercise deletions go first, so one Supabase refuses (it's
        used in a workout plan) stops the save before anything else changes.
        """
        with self._lock:
            old = self._snapshot if self._snapshot is not None else self._read()
            old_ex = {ex["id"]: ex for ex in old["exercises"]}
            new_ex = {ex["id"]: ex for ex in state.get("exercises", [])}

            self._delete_exercises(old_ex, new_ex)
            self._upsert_exercises(old_ex, new_ex)
            self._sync_joints(old_ex, new_ex)
            self._sync_relationships(old.get("relationships", []), state.get("relationships", []), new_ex)

            self._snapshot = copy.deepcopy(state)

    def _delete_exercises(self, old_ex, new_ex):
        for ex_id in sorted(old_ex.keys() - new_ex.keys()):
            try:
                self.client.table("exercises").delete().eq("id", ex_id).execute()
            except APIError as e:
                self._snapshot = None  # reload on the next request
                if e.code == "23503":
                    raise SaveRefused(
                        f'"{old_ex[ex_id]["name"]}" is used in clients\' workout plans, so it can\'t be '
                        "deleted. Take it off the board instead."
                    ) from e
                raise

    def _upsert_exercises(self, old_ex, new_ex):
        movement_ids = self._lookup_ids("movement_types", {ex["movement_type"] for ex in new_ex.values()})
        equipment_ids = self._lookup_ids(
            "equipment", {ex["equipment"][0] for ex in new_ex.values() if ex.get("equipment")}
        )
        changed = [
            self._exercise_record(ex, movement_ids, equipment_ids)
            for ex_id, ex in new_ex.items()
            if ex_id not in old_ex or self._exercise_fields(ex) != self._exercise_fields(old_ex[ex_id])
        ]
        if changed:
            self.client.table("exercises").upsert(changed, on_conflict="id").execute()

    @staticmethod
    def _exercise_fields(ex):
        return (
            ex.get("name"), ex.get("movement_type"), ex.get("orientation") or "", bool(ex.get("dominant")),
            (ex.get("equipment") or [None])[0], ex.get("min_reps"), ex.get("max_reps"),
            bool(ex.get("is_time_based")), ex.get("avoid_if") or "", bool(ex.get("on_board")),
            round(_to_float(ex.get("board_x")), 1), round(_to_float(ex.get("board_y")), 1),
        )

    @staticmethod
    def _exercise_record(ex, movement_ids, equipment_ids):
        equipment = (ex.get("equipment") or [None])[0]
        return {
            "id": ex["id"],
            "name": ex.get("name"),
            "movement_type_id": movement_ids.get(ex.get("movement_type")),
            "orientation": ex.get("orientation") or None,
            "dominant": bool(ex.get("dominant")),
            "equipment_id": equipment_ids.get(equipment) if equipment else None,
            "min_reps": ex.get("min_reps"),
            "max_reps": ex.get("max_reps"),
            "is_time_based": bool(ex.get("is_time_based")),
            "avoid_if": ex.get("avoid_if") or None,
            "on_board": bool(ex.get("on_board")),
            "board_x": round(_to_float(ex.get("board_x")), 1),
            "board_y": round(_to_float(ex.get("board_y")), 1),
        }

    def _lookup_ids(self, table, names):
        """name -> id for a lookup table, adding any name it doesn't have yet
        (e.g. equipment typed into the form's "other" box)."""
        names = {name for name in names if name}
        rows = self.client.table(table).select("id, name").execute().data
        ids = {row["name"]: row["id"] for row in rows}
        missing = sorted(names - ids.keys())
        if missing:
            added = self.client.table(table).insert([{"name": name} for name in missing]).execute().data
            ids.update({row["name"]: row["id"] for row in added})
        return ids

    @staticmethod
    def _joint_pairs(exercises):
        return {
            (ex_id, joint): (ex.get("joint_loads") or {}).get(joint) or DEFAULT_JOINT_LOAD
            for ex_id, ex in exercises.items()
            for joint in ex.get("loaded_joints") or []
        }

    def _sync_joints(self, old_ex, new_ex):
        old_pairs = self._joint_pairs(old_ex)
        new_pairs = self._joint_pairs(new_ex)
        if old_pairs == new_pairs:
            return
        joint_ids = {row["name"]: row["id"] for row in self.client.table("joints").select("id, name").execute().data}
        changed = [
            {"exercise_id": ex_id, "joint_id": joint_ids[joint], "joint_load": load}
            for (ex_id, joint), load in new_pairs.items()
            if old_pairs.get((ex_id, joint)) != load and joint in joint_ids
        ]
        if changed:
            self.client.table("exercise_loaded_joints").upsert(changed, on_conflict="exercise_id,joint_id").execute()
        for ex_id, joint in old_pairs.keys() - new_pairs.keys():
            if ex_id in new_ex and joint in joint_ids:  # a deleted exercise's links cascade away
                (
                    self.client.table("exercise_loaded_joints")
                    .delete()
                    .eq("exercise_id", ex_id)
                    .eq("joint_id", joint_ids[joint])
                    .execute()
                )

    @staticmethod
    def _relationship_map(relationships):
        return {
            (rel["from_exercise_id"], rel["to_exercise_id"], rel["type"]): ";".join(rel.get("reason") or []) or None
            for rel in relationships
            if rel.get("type") in RELATIONSHIP_TYPES
        }

    def _sync_relationships(self, old_rels, new_rels, new_ex):
        old_map = self._relationship_map(old_rels)
        new_map = self._relationship_map(new_rels)
        changed = [
            {"from_exercise_id": f, "to_exercise_id": t, "type": kind, "reason": reason}
            for (f, t, kind), reason in new_map.items()
            if (f, t, kind) not in old_map or old_map[(f, t, kind)] != reason
        ]
        if changed:
            self.client.table("exercise_relationships").upsert(
                changed, on_conflict="from_exercise_id,to_exercise_id,type"
            ).execute()
        for f, t, kind in old_map.keys() - new_map.keys():
            if f in new_ex and t in new_ex:  # a deleted exercise's edges cascade away
                (
                    self.client.table("exercise_relationships")
                    .delete()
                    .eq("from_exercise_id", f)
                    .eq("to_exercise_id", t)
                    .eq("type", kind)
                    .execute()
                )


store = None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            try:
                self._send_json(store.load())
            except Exception as e:
                self._send_json({"error": f"Could not load from Supabase: {e}"}, status=502)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path != "/api/state":
            self._send_json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            state = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, status=400)
            return
        try:
            store.save(state)
        except SaveRefused as e:
            self._send_json({"error": str(e)}, status=409)
            return
        except Exception as e:
            self._send_json({"error": f"Supabase save failed: {e}"}, status=502)
            return
        self._send_json({"ok": True})

    def log_message(self, _format, *_args):
        pass  # keep the terminal quiet


def main():
    global store
    store = LibraryStore()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Workout Builder running at http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
