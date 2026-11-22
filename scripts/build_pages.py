#!/usr/bin/env python3
"""Build a self-contained static site for GitHub Pages.

Layout (served from the site root):
  /index.html                     -> redirect to /player/
  /player/                        -> player files
  /story/03_storyboards/chapter_01.json
  /assets/videos/<node>.mp4       -> 12 final clips (audio baked in)
  /assets/frames/chapter_01/<node>_{first,last}.png

Only files the player actually needs are copied; raw backups, WIP frames and
generated audio masters stay out of the published site.

Usage:
  python3 scripts/build_pages.py [--out dist]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAPTER_REL = Path("story/03_storyboards/chapter_01.json")


def copy(src: Path, dst: Path) -> int:
    if not src.exists():
        raise SystemExit(f"missing: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    args = ap.parse_args()
    out = (ROOT / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    if out == ROOT or ROOT not in out.parents:
        raise SystemExit(f"refusing to write outside repo: {out}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    chapter = json.loads((ROOT / CHAPTER_REL).read_text(encoding="utf-8"))
    total = 0
    videos = frames = 0

    for name in ("index.html", "player.css", "player.js"):
        total += copy(ROOT / "player" / name, out / "player" / name)

    total += copy(ROOT / CHAPTER_REL, out / CHAPTER_REL)

    for node in chapter["nodes"]:
        vid = node["video"].get("video_path")
        if not vid:
            raise SystemExit(f"{node['node_id']}: no video_path")
        total += copy(ROOT / vid, out / vid)
        videos += 1
        for key in ("first_frame_path", "last_frame_path"):
            fp = node["video"].get(key)
            if not fp:
                raise SystemExit(f"{node['node_id']}: no {key}")
            total += copy(ROOT / fp, out / fp)
            frames += 1

    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "index.html").write_text(
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"refresh\" content=\"0; url=player/\">"
        "<title>猫眼之后</title></head><body>"
        "<p>正在进入《猫眼之后》…</p>"
        "<p><a href=\"player/\">如果没有自动跳转，点这里</a></p>"
        "</body></html>\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "out": str(out),
        "videos": videos,
        "frames": frames,
        "bytes": total,
        "mib": round(total / 1048576, 2),
        "url_hint": "https://<user>.github.io/<repo>/player/",
    }, ensure_ascii=False, indent=2))
    if videos != len(chapter["nodes"]):
        print(f"warning: {videos} videos for {len(chapter['nodes'])} nodes", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
