#!/usr/bin/env python3
"""Submit one MiniMax H3 direct-API clip (first/last frames via OSS).

Reads `.env.local` for the MiniMax key and OSS credentials. The bucket can stay
private: first/last frames are exposed as short-lived presigned URLs for the
provider to fetch.

This script is deliberately single-clip and requires an explicit approval id.
It does NOT decide whether spending is approved; check `state/task_board.json`
before running.

Usage:
    python3 scripts/minimax_h3_generate.py \
      --approval-id APR-20261122-VID-003 \
      --node ch01_s01_voiceover \
      --resolution 480p --duration 7 \
      --confirm CONFIRM
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oss_upload import parse_env, presign, ENV_PATH  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHAPTER = ROOT / "story" / "03_storyboards" / "chapter_01.json"


def env_value(name: str) -> str:
    env = parse_env(ENV_PATH)
    value = env.get(name, "").strip()
    if not value:
        raise SystemExit(f"缺少 {name}；先运行 scripts/minimax_config.py / oss_config.py")
    return value


def api(method: str, path: str, payload: dict | None = None) -> tuple[int, dict | str]:
    base = env_value("MINIMAX_BASE_URL").rstrip("/")
    key = env_value("MINIMAX_API_KEY")
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body
    except urllib.error.URLError as exc:
        return 0, f"network error: {exc}"


def balance() -> float | None:
    status, data = api("GET", "/v2/credits/balance")
    if status == 200 and isinstance(data, dict):
        try:
            return float(data.get("balance"))
        except (TypeError, ValueError):
            return None
    return None


def task_of(data: dict) -> dict:
    task = data.get("task")
    return task if isinstance(task, dict) else data


def main() -> int:
    parser = argparse.ArgumentParser(description="Single MiniMax H3 direct-API clip")
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--node", default="ch01_s01_voiceover")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--resolution", default="480p", choices=["480p", "768P", "1080p", "2K"])
    parser.add_argument("--duration", type=int, default=7)
    parser.add_argument("--ratio", default="adaptive")
    parser.add_argument("--out", default="assets/videos/calibration_ch01_s01_480p.mp4")
    parser.add_argument("--first-key", default=None, help="自定义 OSS 首帧 key")
    parser.add_argument("--last-key", default=None, help="自定义 OSS 末帧 key")
    parser.add_argument("--ttl", type=int, default=7 * 24 * 3600)
    parser.add_argument("--poll-interval", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--confirm", default=None, help="必须精确写 CONFIRM 才会真正提交")
    args = parser.parse_args()

    if args.confirm != "CONFIRM":
        print("未提交：需要 --confirm CONFIRM（且审批必须已完成）。", file=sys.stderr)
        return 2

    chapter = json.loads(CHAPTER.read_text(encoding="utf-8"))
    node = next((n for n in chapter.get("nodes", []) if n.get("node_id") == args.node), None)
    if node is None:
        print(f"章节里没有节点 {args.node}", file=sys.stderr)
        return 2
    prompt = args.prompt or (
        str(node["video"].get("video_prompt", "")).strip()
        + "\n从首帧平滑过渡到尾帧，保持人物外观、发型与服装一致；镜头运动克制，无剪切、无转场、无文字、无水印。"
    )

    first_key = args.first_key or f"movie_game_lab/frames/{args.node}_first.png"
    last_key = args.last_key or f"movie_game_lab/frames/{args.node}_last.png"
    env = parse_env(ENV_PATH)
    first_url = presign(env, first_key, args.ttl)
    last_url = presign(env, last_key, args.ttl)

    payload = {
        "model": "MiniMax-H3",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": first_url}, "role": "first_frame"},
            {"type": "image_url", "image_url": {"url": last_url}, "role": "last_frame"},
        ],
        "resolution": args.resolution,
        "duration": args.duration,
        "ratio": args.ratio,
        "fast_mode": False,
    }

    before = balance()
    print(json.dumps({
        "approval_id": args.approval_id,
        "node": args.node,
        "resolution": args.resolution,
        "duration": args.duration,
        "balance_before": before,
    }, ensure_ascii=False))

    status, data = api("POST", "/v2/video_generation", payload)
    if status != 200 or not isinstance(data, dict):
        print(f"提交失败 HTTP {status}: {str(data)[:1500]}", file=sys.stderr)
        return 1
    task = task_of(data)
    task_id = task.get("id") or data.get("task_id") or data.get("id")
    if not task_id:
        print(f"提交响应里没有 task id：{json.dumps(data, ensure_ascii=False)[:1200]}", file=sys.stderr)
        return 1
    print(json.dumps({"task_id": task_id, "status": task.get("status")}, ensure_ascii=False))

    started = time.time()
    final = None
    while time.time() - started < args.timeout:
        time.sleep(args.poll_interval)
        qs, qd = api("GET", f"/v2/query/video_generation/{task_id}")
        if qs != 200 or not isinstance(qd, dict):
            print(f"[poll] HTTP {qs}: {str(qd)[:300]}", flush=True)
            continue
        t = task_of(qd)
        state = str(t.get("status", ""))
        print(f"[poll] {int(time.time() - started)}s status={state}", flush=True)
        if state in ("succeeded", "success", "completed"):
            final = t
            break
        if state in ("failed", "error", "cancelled"):
            print(json.dumps(t, ensure_ascii=False)[:2000], file=sys.stderr)
            return 1
    if final is None:
        print("轮询超时；任务可能仍在运行，请用 query 接口继续查，不要盲目重提。", file=sys.stderr)
        return 1

    content = final.get("content")
    video_url = content.get("url") if isinstance(content, dict) else None
    if not video_url:
        print(f"任务成功但没有 content.url：{json.dumps(final, ensure_ascii=False)[:1200]}", file=sys.stderr)
        return 1

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(video_url, timeout=300) as resp, open(out, "wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)

    after = balance()
    usage = final.get("usage") if isinstance(final.get("usage"), dict) else {}
    credits_spent = (before - after) if (before is not None and after is not None) else None
    probe = {}
    try:
        raw = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_name",
             "-of", "json", str(out)],
            capture_output=True, text=True, check=True,
        ).stdout
        probe = json.loads(raw)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        pass

    summary = {
        "approval_id": args.approval_id,
        "task_id": task_id,
        "status": final.get("status"),
        "resolution": final.get("resolution"),
        "duration_sec": final.get("duration"),
        "usage": usage,
        "balance_before": before,
        "balance_after": after,
        "credits_spent": credits_spent,
        "usd_estimate_at_cap_rate": round(credits_spent * 0.0025, 4) if credits_spent is not None else None,
        "output": str(out.relative_to(ROOT)),
        "bytes": out.stat().st_size,
        "ffprobe": probe,
    }
    (ROOT / "state" / "h3_direct_calibration.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
