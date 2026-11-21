#!/usr/bin/env python3
"""Generate character anchor frames with local ComfyUI Qwen-Image 2.1.

Stdlib only. Builds an API-format workflow, submits it to the local ComfyUI
instance, polls /history, downloads the PNG, keeps a 1024x576 master and
exports an 854x480 delivery frame.

Usage:
    python3 scripts/gen_anchors.py --character shen_yan --dry-run
    python3 scripts/gen_anchors.py --character shen_yan --seed 20261121

No cloud nodes are used. Cash cost is zero.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone, timedelta

COMFY = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANCHOR_DIR = os.path.join(ROOT, "assets", "frames", "anchors")
MASTER_DIR = os.path.join(ANCHOR_DIR, "_master")
STATE_PATH = os.path.join(ROOT, "state", "anchor_generation.json")

MODELS = {
    "unet": "qwen_image_2.1_int8_convrot.safetensors",
    "clip": "qwen3vl_8b_int8_convrot.safetensors",
    "vae": "qwen_image_2.1_vae_bf16.safetensors",
}

NEGATIVE = (
    "多余手指, 手部畸形, 双眼不对称, 文字, 水印, logo, 过饱和, 塑料皮肤, "
    "双人重复, 服装不一致, 现代电子设备乱入, 眼镜, 胡须, 耳机戴在头上, 多余肢体"
)

CHARACTERS = {
    "shen_yan": {
        "label": "沈砚",
        "prompt": (
            "角色定妆照，正面半身肖像，单人，直视镜头。沈砚，33 岁，窄长脸、单眼皮、眼尾略垂，"
            "左眉尾（画面右侧眉毛末端）有一道清晰可见的 1.5cm 旧疤；黑色短发三七分，"
            "分缝在画面左侧、画面左侧刘海略长垂到眉骨；穿深灰连帽卫衣与白色圆领 T 恤，"
            "卫衣左胸（画面右侧）有一小块洗不掉的白色漆点；银色头戴式监听耳机挂在脖上"
            "（不戴在头上），神情疲惫而克制；纯中性灰背景，柔和均匀布光，写实电影质感，"
            "35mm，浅景深，16:9 横向构图，画面干净，无文字、无水印、无 logo。"
        ),
        "seed": 20261121,
    },
    "zhou_qiming": {
        "label": "周启明",
        "prompt": (
            "角色定妆照，正面半身肖像，单人，直视镜头。周启明，42 岁，方脸、浓眉、眉间竖纹，"
            "左眼下方（画面右侧）一颗小黑痣，灰黑寸头，青灰胡茬，穿深蓝工装夹克与灰色 polo，"
            "夹克左袖口（画面右侧）磨白，右手虎口（画面左侧手）有烫伤疤，腰间挂黄铜钥匙串，"
            "站姿沉稳，神情温和而克制；纯中性灰背景，柔和均匀布光，写实电影质感，"
            "35mm，浅景深，16:9 横向构图，画面干净，无文字、无水印、无 logo。"
        ),
        "seed": 20261122,
    },
    "su_min_partial": {
        "label": "苏敏（局部）",
        "prompt": (
            "局部一致性参考图，暗色室内地毯上的特写：一只苍白女性的右手从米色针织长裙"
            "袖口伸出，手腕戴着细银手链、三颗小珠，右手食指第二指节有浅咬痕，指甲短且"
            "无甲油；画面边缘可见一缕黑色长直发（发尾深棕）与一只浮肿的右眼，右眼下方"
            "有泪痣；不露全脸。写实电影质感，35mm，浅景深，低照度，"
            "16:9 横向构图，画面干净，无文字、无水印、无 logo。"
        ),
        "seed": 20261123,
    },
}


def http_json(url: str, payload: dict | None = None, timeout: int = 30) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_workflow(prompt: str, seed: int, steps: int, cfg: float, width: int, height: int) -> dict:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": MODELS["unet"], "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": MODELS["clip"], "type": "qwen_image", "device": "default"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": MODELS["vae"]},
        },
        "4": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {
                "clip": ["2", 0],
                "prompt": prompt,
                "negative_prompt": NEGATIVE,
                "resolution": 1024,
                "vae": ["3", 0],
            },
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "positive": ["4", 0],
                "negative": ["4", 1],
                "latent_image": ["5", 0],
            },
        },
        "7": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["6", 0], "vae": ["3", 0]},
        },
        "8": {
            "class_type": "SaveImage",
            "inputs": {"images": ["7", 0], "filename_prefix": "anchors/_master"},
        },
    }


def png_size(path: str) -> tuple[int, int]:
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    return struct.unpack(">II", head[16:24])


def scale_to(src: str, dst: str, width: int, height: int) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    subprocess.run(["sips", "-z", str(height), str(width), src, "--out", dst],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def download_image(image: dict, dst: str) -> None:
    query = urllib.parse.urlencode({
        "filename": image["filename"],
        "subfolder": image.get("subfolder", ""),
        "type": image.get("type", "output"),
    })
    with urllib.request.urlopen(f"{COMFY}/view?{query}", timeout=60) as resp:
        data = resp.read()
    with open(dst, "wb") as fh:
        fh.write(data)


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError:
            pass
    return {"chapter_id": "chapter_01", "records": []}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--character", required=True, choices=sorted(CHARACTERS))
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=1.0)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=576)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    spec = CHARACTERS[args.character]
    seed = args.seed if args.seed is not None else spec["seed"]
    wf = build_workflow(spec["prompt"], seed, args.steps, args.cfg, args.width, args.height)

    if args.dry_run:
        print(json.dumps({"prompt": wf, "seed": seed, "character": args.character},
                         ensure_ascii=False, indent=2))
        return 0

    os.makedirs(MASTER_DIR, exist_ok=True)
    started = time.time()
    prompt_id = http_json(f"{COMFY}/prompt", {
        "prompt": wf,
        "client_id": str(uuid.uuid4()),
    })["prompt_id"]
    print(f"[submit] character={args.character} seed={seed} prompt_id={prompt_id}", flush=True)

    deadline = started + args.timeout
    history = None
    while time.time() < deadline:
        time.sleep(5)
        hist = http_json(f"{COMFY}/history/{prompt_id}")
        if prompt_id in hist:
            history = hist[prompt_id]
            break
        print(f"[wait] {int(time.time() - started)}s", flush=True)

    if history is None:
        print("[error] timeout waiting for ComfyUI", file=sys.stderr)
        return 2

    status = history.get("status", {})
    if status.get("status_str") == "error":
        print(json.dumps(status, ensure_ascii=False)[:2000], file=sys.stderr)
        return 3

    images = []
    for node_out in history.get("outputs", {}).values():
        images.extend(node_out.get("images", []))
    if not images:
        print("[error] no images in history outputs", file=sys.stderr)
        return 4

    image = images[0]
    master = os.path.join(MASTER_DIR, f"{args.character}_anchor_{args.width}x{args.height}.png")
    delivery = os.path.join(ANCHOR_DIR, f"{args.character}_anchor.png")
    download_image(image, master)
    scale_to(master, delivery, 854, 480)

    elapsed = round(time.time() - started, 1)
    mw, mh = png_size(master)
    dw, dh = png_size(delivery)
    record = {
        "character_id": args.character,
        "label": spec["label"],
        "seed": seed,
        "prompt": spec["prompt"],
        "negative_prompt": NEGATIVE,
        "params": {
            "steps": args.steps, "cfg": args.cfg, "sampler": "euler",
            "scheduler": "simple", "denoise": 1.0,
            "master_size": [args.width, args.height], "delivery_size": [854, 480],
            "unet": MODELS["unet"], "clip": MODELS["clip"], "vae": MODELS["vae"],
            "workflow": "qwen_image_2_1_t2i_minimal (TextEncodeQwenImage21 + EmptyLatentImage)",
        },
        "prompt_id": prompt_id,
        "elapsed_sec": elapsed,
        "master_path": os.path.relpath(master, ROOT),
        "delivery_path": os.path.relpath(delivery, ROOT),
        "master_px": [mw, mh],
        "delivery_px": [dw, dh],
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
    }
    state = load_state()
    state["records"] = [r for r in state.get("records", []) if r.get("character_id") != args.character]
    state["records"].append(record)
    save_state(state)

    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
