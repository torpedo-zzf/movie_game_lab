#!/usr/bin/env python3
"""Generate one 16:9 keyframe with Codex's built-in imagegen, using refs.

Requires Codex CLI with imagegen access. Runs in a temp dir, asks Codex to use
$imagegen, then copies ./out.png to --out and resizes to 854x480.
"""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "frame_generation.json"


def frame_prompt(node: str, frame: str) -> str:
    data = json.loads(STATE.read_text(encoding="utf-8"))
    recs = data["records"] if isinstance(data, dict) and "records" in data else data
    rec = next((r for r in recs if r.get("node_id") == node and r.get("frame") == frame), None)
    if rec is None:
        raise SystemExit(f"no frame record for {node}/{frame}")
    return str(rec["prompt"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True)
    ap.add_argument("--frame", required=True, choices=["first", "last"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref", action="append", default=[])
    ap.add_argument("--prompt-extra", default="")
    ap.add_argument("--timeout", type=int, default=15 * 60)
    args = ap.parse_args()

    refs = [str(Path(p).resolve()) for p in args.ref]
    for r in refs:
        if not Path(r).exists():
            raise SystemExit(f"reference missing: {r}")

    base = frame_prompt(args.node, args.frame)
    note = (
        "The attached images are references. Image 1 is the character identity reference; "
        "any further images are composition / room / lighting references for this exact shot. "
        "Keep the same person, age, hairstyle, wardrobe and room as the references."
        if refs else ""
    )
    prompt = (
        "Use $imagegen to generate exactly one 16:9 cinematic still at 854x480. "
        + (note + " " if note else "")
        + base
        + " 16:9 cinematic still, realistic film still, no text, no watermark."
        + ((" " + args.prompt_extra) if args.prompt_extra else "")
        + "\nThen copy the final PNG to ./out.png in the current working directory. "
          "Reply with only the final file path."
    )

    tmp = Path(tempfile.mkdtemp(prefix="codex-keyframe-"))
    try:
        (tmp / "prompt.txt").write_text(prompt, encoding="utf-8")
        cmd = ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check"]
        for r in refs:
            cmd += ["-i", r]
        cmd += ["-"]
        proc = subprocess.run(cmd, cwd=tmp, input=prompt, text=True, capture_output=True, timeout=args.timeout)
        (tmp / "codex.log").write_text((proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8")
        out = tmp / "out.png"
        if not out.exists():
            tail = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-2000:]
            print(json.dumps({"ok": False, "node": args.node, "frame": args.frame, "exit": proc.returncode, "tail": tail}, ensure_ascii=False))
            return 1
        dst = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
        dst.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["sips", "-s", "format", "png", "-z", "480", "854", str(out), "--out", str(dst)], check=True, capture_output=True)
        dims = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(dst)], capture_output=True, text=True).stdout
        print(json.dumps({"ok": True, "node": args.node, "frame": args.frame, "out": str(dst), "dims": dims.strip(), "exit": proc.returncode}, ensure_ascii=False))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
