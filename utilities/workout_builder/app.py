#!/usr/bin/env python3
"""Workout Builder utility — exercise creator + drag-and-drop relationship board.

Run:  python3 app.py   then open http://localhost:8765

Persistence: data/exercises.csv and data/relationships.csv, rewritten on every
change the frontend makes. No third-party dependencies.
"""
import csv
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
STATIC_DIR = os.path.join(BASE, "static")
EXERCISES_CSV = os.path.join(DATA_DIR, "exercises.csv")
RELATIONSHIPS_CSV = os.path.join(DATA_DIR, "relationships.csv")

EXERCISE_FIELDS = [
    "id", "name", "movement_type", "orientation", "dominant", "equipment", "loaded_joints",
    "min_reps", "max_reps", "avoid_if", "on_board", "board_x", "board_y",
]
RELATIONSHIP_FIELDS = ["id", "from_exercise_id", "to_exercise_id", "type", "reason"]

PORT = 8765


def _split(value):
    return [part for part in (value or "").split(";") if part]


def _join(value):
    return ";".join(value or [])


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_state():
    exercises = []
    if os.path.exists(EXERCISES_CSV):
        with open(EXERCISES_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                exercises.append({
                    "id": _to_int(row.get("id")),
                    "name": row.get("name", ""),
                    "movement_type": row.get("movement_type", ""),
                    "orientation": row.get("orientation", ""),
                    "dominant": row.get("dominant") == "true",
                    "equipment": _split(row.get("equipment")),
                    "loaded_joints": _split(row.get("loaded_joints")),
                    "min_reps": _to_int(row.get("min_reps")),
                    "max_reps": _to_int(row.get("max_reps")),
                    "avoid_if": row.get("avoid_if", ""),
                    "on_board": row.get("on_board") == "true",
                    "board_x": _to_float(row.get("board_x")),
                    "board_y": _to_float(row.get("board_y")),
                })
    relationships = []
    if os.path.exists(RELATIONSHIPS_CSV):
        with open(RELATIONSHIPS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                relationships.append({
                    "id": _to_int(row.get("id")),
                    "from_exercise_id": _to_int(row.get("from_exercise_id")),
                    "to_exercise_id": _to_int(row.get("to_exercise_id")),
                    "type": row.get("type", ""),
                    "reason": _split(row.get("reason")),
                })
    return {"exercises": exercises, "relationships": relationships}


def save_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(EXERCISES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXERCISE_FIELDS)
        writer.writeheader()
        for ex in state.get("exercises", []):
            writer.writerow({
                "id": ex.get("id"),
                "name": ex.get("name", ""),
                "movement_type": ex.get("movement_type", ""),
                "orientation": ex.get("orientation", ""),
                "dominant": "true" if ex.get("dominant") else "false",
                "equipment": _join(ex.get("equipment")),
                "loaded_joints": _join(ex.get("loaded_joints")),
                "min_reps": ex.get("min_reps"),
                "max_reps": ex.get("max_reps"),
                "avoid_if": ex.get("avoid_if", ""),
                "on_board": "true" if ex.get("on_board") else "false",
                "board_x": round(_to_float(ex.get("board_x")), 1),
                "board_y": round(_to_float(ex.get("board_y")), 1),
            })
    with open(RELATIONSHIPS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RELATIONSHIP_FIELDS)
        writer.writeheader()
        for rel in state.get("relationships", []):
            writer.writerow({
                "id": rel.get("id"),
                "from_exercise_id": rel.get("from_exercise_id"),
                "to_exercise_id": rel.get("to_exercise_id"),
                "type": rel.get("type", ""),
                "reason": _join(rel.get("reason")),
            })


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
            self._send_json(load_state())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/state":
            length = int(self.headers.get("Content-Length", 0))
            try:
                state = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, status=400)
                return
            save_state(state)
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "not found"}, status=404)

    def log_message(self, _format, *_args):
        pass  # keep the terminal quiet


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(EXERCISES_CSV) or not os.path.exists(RELATIONSHIPS_CSV):
        save_state(load_state())  # create CSVs with headers on first run
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Workout Builder running at http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
