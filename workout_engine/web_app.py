"""Apple-styled web frontend for the raw-text -> profile -> weekly plan pipeline.

Run:  python3 web_app.py   (from workout_engine/)   then open http://localhost:8000

Serves the static frontend in web/ and exposes the two pipeline stages as
separate endpoints so the page can report real progress between them.
"""
import os

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.preprocessor_agent import SAMPLE_RAW_TEXT, generate_user_profile
from workout_engine.agents.workout_agent import generate_workout_plan_v1

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

app = FastAPI(title="Fitness Coach")


class ProfileRequest(BaseModel):
    text: str


class PlanRequest(BaseModel):
    profile: dict


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/api/sample")
def sample():
    return {"text": SAMPLE_RAW_TEXT}


@app.post("/api/profile")
def profile(req: ProfileRequest):
    if not req.text.strip():
        raise HTTPException(status_code=422, detail="Describe the client first.")
    try:
        return {"profile": generate_user_profile(req.text)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read that profile: {e}")


@app.post("/api/plan")
def plan(req: PlanRequest):
    try:
        result = generate_workout_plan_v1(req.profile)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {e}")
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


app.mount("/", StaticFiles(directory=WEB_DIR), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
