#!/usr/bin/env bash
# Re-encode the cardio circuit clips for phones and grab a poster frame each.
#
#   utilities/cardio_videos/prepare.sh ~/Desktop/cardioVideos [out_dir]
#
# Each clip becomes <slug>.mp4 (720p H.264, no audio — the PWA plays them
# muted and looped, timed by its own countdown) and <slug>.jpg (a frame 2 s
# in). Slugs are the lower-cased, hyphenated file names, matching
# cardio_exercises.video_path / poster_path. Upload them with upload.py.
set -euo pipefail

src="${1:?usage: prepare.sh <source dir> [out dir]}"
out="${2:-$(dirname "$0")/out}"
mkdir -p "$out"

for clip in "$src"/*.mp4; do
  name="$(basename "$clip" .mp4)"
  slug="$(echo "$name" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-|-$//g')"
  echo "→ $name  ($slug)"
  ffmpeg -nostdin -loglevel error -y -i "$clip" \
    -vf "scale=-2:720" -c:v libx264 -preset slow -crf 28 -pix_fmt yuv420p \
    -movflags +faststart -an "$out/$slug.mp4"
  ffmpeg -nostdin -loglevel error -y -ss 2 -i "$clip" -frames:v 1 \
    -vf "scale=-2:480" -q:v 4 "$out/$slug.jpg"
done

ls -lh "$out"
