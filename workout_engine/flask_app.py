"""Flask API for the raw-text -> profile -> workout-plan pipeline.

Run:  python3 flask_app.py   (from workout_engine/)   then:

  curl -X POST http://localhost:8001/workout-plan \\
    -H "Content-Type: application/json" \\
    -d '{"userid": "usr_10235", "raw_user_text": "..."}'
"""
from flask import Flask, jsonify, request

from agents.preprocessor_agent import generate_user_profile
from agents.workout_agent import generate_workout_plan_v1

app = Flask(__name__)


@app.post("/workout-plan")
def create_workout_plan():
    body = request.get_json(silent=True) or {}
    user_id = body.get("userid")
    raw_user_text = body.get("raw_user_text")

    if not user_id or not raw_user_text:
        return jsonify({"error": "Both 'userid' and 'raw_user_text' are required."}), 400

    try:
        profile = generate_user_profile(raw_user_text)
    except ValueError as e:
        return jsonify({"error": f"Failed to extract client profile: {e}"}), 502

    # The preprocessor assigns its own placeholder user_id (it's forbidden
    # from inventing one) — the caller's id is authoritative.
    profile["user_id"] = user_id

    plan = generate_workout_plan_v1(profile)
    status = 500 if "error" in plan else 200
    return jsonify(plan), status


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=True)
