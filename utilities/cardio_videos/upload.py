"""Upload the prepared cardio clips and posters to the public `cardio-videos`
Storage bucket, overwriting any already there.

    SUPABASE_SERVICE_ROLE_KEY=... .venv/bin/python utilities/cardio_videos/upload.py [dir]

`dir` defaults to utilities/cardio_videos/out (what prepare.sh writes). The
bucket only lets the service-role key write — the app's publishable key can
just read — so pass that key in the environment for this one run; it is
never stored. SUPABASE_URL comes from .env as usual. File names must match
cardio_exercises.video_path / poster_path.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

BUCKET = "cardio-videos"
CONTENT_TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg"}


def main() -> int:
    load_dotenv()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        print("Set SUPABASE_SERVICE_ROLE_KEY (Supabase dashboard → Project Settings → API keys).")
        return 1
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "out")
    files = sorted(p for p in folder.iterdir() if p.suffix in CONTENT_TYPES)
    if not files:
        print(f"No .mp4/.jpg files in {folder} — run prepare.sh first.")
        return 1

    bucket = create_client(os.environ["SUPABASE_URL"], key).storage.from_(BUCKET)
    for path in files:
        bucket.upload(
            path.name,
            path.read_bytes(),
            {"content-type": CONTENT_TYPES[path.suffix], "upsert": "true", "cache-control": "31536000"},
        )
        print(f"uploaded {path.name} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
