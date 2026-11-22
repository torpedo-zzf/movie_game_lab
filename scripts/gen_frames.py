#!/usr/bin/env python3
"""Generate chapter_01 first/last frames with the local ComfyUI Qwen-Image 2.1.

Stdlib only. One text-to-image request per frame:
  UNETLoader(qwen_image_2.1) + CLIPLoader(qwen3vl_8b) + VAELoader(qwen_image_2.1_vae)
  -> TextEncodeQwenImage21 (no reference images, resolution=1024)
  -> EmptyLatentImage(1024x576) -> KSampler(30 steps, cfg 1.0, euler/simple)
  -> VAEDecode -> SaveImage

Master:  assets/frames/chapter_01/_master/<node_id>_<first|last>.png   (1024x576)
Delivery: assets/frames/chapter_01/<node_id>_<first|last>.png          (854x480, sips)
State:   state/frame_generation.json

This script never writes first_frame_path / last_frame_path back into the
storyboard. It also never overwrites an existing delivery frame whose size is
already correct; such frames count as done and are skipped.

Usage:
    python3 scripts/gen_frames.py --dry-run
    python3 scripts/gen_frames.py --only ch01_s01_voiceover --frames first
    python3 scripts/gen_frames.py --frames both --limit 2
    python3 scripts/gen_frames.py --step          # generate the next pending frame only

No cloud nodes, no MiniMax H3. Local cash cost is zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone, timedelta

COMFY = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAPTER_PATH = os.path.join(ROOT, "story", "03_storyboards", "chapter_01.json")
BIBLE_PATH = os.path.join(ROOT, "story", "01_bible", "02_characters.md")
CHAPTER_ID = "chapter_01"
OUT_DIR = os.path.join(ROOT, "assets", "frames", CHAPTER_ID)
MASTER_DIR = os.path.join(OUT_DIR, "_master")
WIP_DIR = os.path.join(OUT_DIR, "_wip")
STATE_PATH = os.path.join(ROOT, "state", "frame_generation.json")

MODELS = {
    "unet": "qwen_image_2.1_int8_convrot.safetensors",
    "clip": "qwen3vl_8b_int8_convrot.safetensors",
    "vae": "qwen_image_2.1_vae_bf16.safetensors",
}

MASTER_W, MASTER_H = 1024, 576
DELIVERY_W, DELIVERY_H = 854, 480
STEPS = 30
CFG = 1.0
SEED_BASE = 20261122

# 固定电影后缀（每帧追加）
SUFFIX = "16:9 电影静帧，写实电影质感，35mm，浅景深，低照度，画面干净，无文字、无水印"

# 参考图模式（本轮身份一致性路径）：16 步 / cfg 2.5 / shift 3.1 / 64 通道 latent
# TextEncodeQwenImage21 的 resolution 是“面积 ≈ resolution²”，不是长边。
# 480 → 16:9 只有 640x352；要 854x480 级别需 640（输出约 864x480）。
REF_STEPS, REF_CFG, REF_RES = 16, 2.5, 640
KEEP_SENTENCE = (
    "Keep the same person as the reference images: same face, hairstyle, age and clothing."
)
REF_FILES = {
    "shen_yan": os.path.join(ROOT, "assets", "frames", "anchors", "shen_yan_anchor.png"),
    "zhou_qiming": os.path.join(ROOT, "assets", "frames", CHAPTER_ID, "_refs", "zhou_qiming_16x9.png"),
    "su_min": os.path.join(ROOT, "assets", "frames", "anchors", "su_min_partial_anchor.png"),
}

# 固定负面词（t2i 路径 cfg=1.0 时负向条件不参与采样，仍按要求原样记录并提交）
NEGATIVE = (
    "多余手指, 手部畸形, 文字, 水印, logo, 过饱和, 塑料皮肤, "
    "双人重复, 服装不一致, 现代电子设备乱入, 多余肢体"
)

# 苏敏在圣经里没有“角色描述块”，这段由第 4 节表格逐项压缩而来，只允许局部出现。
SU_MIN_BLOCK = (
    "苏敏，31 岁，仅右手、右眼与部分黑发可见；右眼下方一颗泪痣，皮肤苍白，眼睑浮肿，不化妆；"
    "黑色长直发、发尾深棕；米色针织长裙袖口起球，细银手链三颗小珠，右手食指第二指节有咬痕，"
    "指甲短且无甲油；不露全脸"
)

# 每个角色块之后逐字追加的硬约束（左右映射 / 年龄脸型 / 标志物）
CHAR_CONSTRAINTS = {
    "shen_yan": [
        "沈砚左眉尾的旧疤在画面右侧眉毛末端；左胸白漆点在画面右侧胸口。",
        "左胸（画面右侧）一小块洗不掉的白色漆点，不要大面积溅点。",
        "33 岁，窄长脸、偏瘦、眼下青黑、疲惫克制，不要年轻偶像脸/磨皮。",
    ],
    "zhou_qiming": [
        "周启明左眼下方的黑痣在画面右侧；右手虎口烫伤疤在画面左侧的手上。",
        "腰间挂一串黄铜钥匙。",
        "42 岁，方脸宽下颌、体格厚实，不要年轻化。",
    ],
    "su_min": [
        "苏敏右眼泪痣在画面右侧；右手食指第二指节咬痕；右腕三颗小珠银手链。",
        "米色针织袖口、短甲无甲油。",
    ],
}

# 节点级镜头约束（只对猫眼节点 s02/s09 的 first/last 生效）
FISHEYE_SENTENCE = (
    "shot through a door peephole, 8mm fisheye lens, heavy circular barrel distortion, "
    "black circular vignette around the frame, extreme wide-angle, the corridor bends at the edges"
)
NODE_PROMPT_APPEND = {
    "ch01_s02_peephole": FISHEYE_SENTENCE,
    "ch01_s09_second_knock": FISHEYE_SENTENCE,
}

# 单帧整段 prompt 覆盖：s04 last 只允许地毯边 + 一截手指，不许出现完整女性/合影。
NODE_PROMPT_OVERRIDE = {
    ("ch01_s04_open", "last"): (
        "Extreme close-up of the bottom edge of a rolled dark red carpet at the apartment threshold. "
        "A sliver of a pale female hand with short unpolished nails protrudes from under the carpet edge. "
        "Zhou Qiming's leg and torso block most of the opening; Shen Yan's blurred shoulder in the foreground. "
        "Zhou's face is partly visible at the edge, still smiling. No face of the woman, no full woman, no full body, "
        "no group photo, no lineup. Shallow depth of field, green emergency light and warm door light, 16:9 cinematic still."
    ),
}
# 覆盖帧的参考图固定顺序（s04 last 去掉苏敏，只留 Shen + Zhou）
NODE_REF_OVERRIDE = {
    ("ch01_s04_open", "last"): ["shen_yan", "zhou_qiming"],
}

# 名字/局部线索 -> 角色。苏敏只在明确出现肢体局部时追加，避免生成完整人物。
SHEN_TOKENS = ("沈砚",)
ZHOU_TOKENS = ("周启明", "老周")
SU_TOKENS = ("苏敏", "苍白手指", "泪痣", "银手链", "毯子盖住人形")

TZ = timezone(timedelta(hours=8))
CLASS_TYPES = {
    "UNETLoader", "CLIPLoader", "VAELoader", "TextEncodeQwenImage21", "ModelSamplingAuraFlow",
    "LoadImage", "EmptyLatentImage", "KSampler", "VAEDecode", "SaveImage",
}


# --------------------------------------------------------------------------- #
# 输入
# --------------------------------------------------------------------------- #
def load_chapter() -> dict:
    with open(CHAPTER_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def bible_character_blocks() -> dict[str, str]:
    """从角色圣经里逐字抓取“角色描述块（中，逐字复用）”，抓不到就用内置副本。"""
    fallback = {
        "shen_yan": "沈砚，33 岁，窄长脸、单眼皮、眼尾略垂，左眉尾有一道 1.5cm 旧疤，黑色三七分短发，"
                     "穿深灰连帽卫衣与白 T，左胸有白色漆点，银色监听耳机挂在脖上，神情疲惫而克制。",
        "zhou_qiming": "周启明，42 岁，方脸浓眉、眉间竖纹，左眼下方一颗小黑痣，灰黑寸头，青灰胡茬，"
                       "穿深蓝工装夹克与灰 polo，左袖口磨白，右手虎口有烫伤疤，腰间挂黄铜钥匙串。",
        "su_min": SU_MIN_BLOCK,
    }
    try:
        text = open(BIBLE_PATH, encoding="utf-8").read()
    except OSError:
        return fallback
    blocks = re.findall(r"\*\*角色描述块（中，逐字复用）\*\*：(.+)", text)
    found = {}
    for block in blocks:
        block = block.strip()
        if "沈砚" in block:
            found["shen_yan"] = block
        elif "周启明" in block:
            found["zhou_qiming"] = block
    found.setdefault("shen_yan", fallback["shen_yan"])
    found.setdefault("zhou_qiming", fallback["zhou_qiming"])
    found["su_min"] = SU_MIN_BLOCK
    return found


def characters_in(prompt: str) -> list[str]:
    """按固定顺序返回本帧出场的角色键（“头像为某人”不算本人出场）。"""
    prompt = re.sub(r"头像为(?:沈砚|周启明|苏敏)", "", prompt)
    hits = []
    if any(t in prompt for t in SHEN_TOKENS):
        hits.append("shen_yan")
    if any(t in prompt for t in ZHOU_TOKENS):
        hits.append("zhou_qiming")
    if any(t in prompt for t in SU_TOKENS):
        hits.append("su_min")
    return hits


def compose_prompt(base: str, blocks: dict[str, str], use_refs: bool = False,
                   extra: str | None = None) -> tuple[str, list[str]]:
    keys = characters_in(base)
    parts = [base.strip().rstrip("。；")]
    if extra:
        parts.append(extra.strip().rstrip("。."))
    if keys:
        clauses = []
        for k in keys:
            clause = blocks[k].strip()
            if not clause.endswith("。"):
                clause += "。"
            for d in CHAR_CONSTRAINTS[k]:
                d = d.strip()
                clause += d if d.endswith("。") else d + "。"
            clauses.append(clause)
        parts.append("角色设定（逐字复用，不得改词）：" + "".join(clauses))
    head = "。".join(parts)
    if use_refs:
        head += " " + KEEP_SENTENCE
        head += " " + SUFFIX + "。"
    else:
        head += "。" + SUFFIX + "。"
    return head, keys


def frame_jobs(chapter: dict, frames_mode: str) -> list[dict]:
    """展开成待处理帧列表，node 序号从 1 开始，seed 稳定。"""
    jobs = []
    for idx, node in enumerate(chapter.get("nodes", []), 1):
        node_id = node.get("node_id")
        video = node.get("video") or {}
        wanted = ["first", "last"] if frames_mode == "both" else [frames_mode]
        for frame in wanted:
            key = f"{frame}_frame_prompt"
            base = (video.get(key) or "").strip()
            if not base:
                continue
            jobs.append({
                "node_id": node_id,
                "node_index": idx,
                "frame": frame,
                "base_prompt": base,
                "seed": SEED_BASE + idx * 10 + (0 if frame == "first" else 1),
            })
    return jobs


# --------------------------------------------------------------------------- #
# 工作流
# --------------------------------------------------------------------------- #
def build_workflow(prompt: str, seed: int) -> dict:
    """无人物帧：纯 t2i，1024x576 / 30 步 / cfg 1.0（与既有锚点流程一致）。"""
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
            "inputs": {"width": MASTER_W, "height": MASTER_H, "batch_size": 1},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": seed,
                "steps": STEPS,
                "cfg": CFG,
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
            "inputs": {"images": ["7", 0], "filename_prefix": "chapter_01/_master"},
        },
    }


def build_ref_workflow(prompt: str, seed: int, ref_names: list[str]) -> dict:
    """带角色参考的帧：TextEncodeQwenImage21 吃参考图，latent 用它的 64 通道输出。

    输出比例跟第一张参考图走（16:9 参考 -> 约 864x480）。
    """
    wf = {
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
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["1", 0], "shift": 3.1, "sampling": "flow"},
        },
        "5": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {
                "clip": ["2", 0],
                "prompt": prompt,
                "negative_prompt": NEGATIVE,
                "resolution": REF_RES,
                "vae": ["3", 0],
            },
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "seed": seed,
                "steps": REF_STEPS,
                "cfg": REF_CFG,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "positive": ["5", 0],
                "negative": ["5", 1],
                "latent_image": ["5", 2],
            },
        },
        "7": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["6", 0], "vae": ["3", 0]},
        },
        "8": {
            "class_type": "SaveImage",
            "inputs": {"images": ["7", 0], "filename_prefix": "chapter_01/_master"},
        },
    }
    for i, name in enumerate(ref_names, 1):
        wf[f"ref{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        # 自动扩展输入在 API 格式里是扁平键 images.image_N
        wf["5"]["inputs"][f"images.image_{i}"] = [f"ref{i}", 0]
    return wf


def validate_workflow(wf: dict, mode: str) -> list[str]:
    """dry-run 用的本地结构校验：节点类型、连线、latent 来源、采样参数。"""
    problems = []
    for nid, node in wf.items():
        ctype = node.get("class_type")
        if ctype not in CLASS_TYPES:
            problems.append(f"node {nid}: 未知 class_type {ctype}")
        for key, val in (node.get("inputs") or {}).items():
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str) and isinstance(val[1], int):
                if val[0] not in wf:
                    problems.append(f"node {nid}.{key}: 指向不存在的节点 {val[0]}")

    pos_id = next((n for n, v in wf.items() if v.get("class_type") == "TextEncodeQwenImage21"), None)
    ks_id = next((n for n, v in wf.items() if v.get("class_type") == "KSampler"), None)
    if not pos_id or not ks_id:
        return problems + ["缺少 TextEncodeQwenImage21 或 KSampler"]
    enc = wf[pos_id]["inputs"]
    ks = wf[ks_id]["inputs"]

    if mode == "ref":
        if not any(k.startswith("images.image_") for k in enc):
            problems.append("ref 模式缺少参考图输入")
        if enc.get("resolution") != REF_RES:
            problems.append(f"ref 模式 resolution 应为 {REF_RES}")
        if (ks["steps"], ks["cfg"]) != (REF_STEPS, REF_CFG):
            problems.append(f"ref 模式采样应为 {REF_STEPS} 步 / cfg {REF_CFG}")
        if ks.get("latent_image") != [pos_id, 2]:
            problems.append("ref 模式 latent 应接 pos 的 64 通道输出")
        if not any(v.get("class_type") == "ModelSamplingAuraFlow" for v in wf.values()):
            problems.append("ref 模式缺少 ModelSamplingAuraFlow(shift 3.1)")
    else:
        if any(k.startswith("images.") for k in enc):
            problems.append("t2i 模式不应带参考图")
        if enc.get("resolution") != 1024:
            problems.append("t2i 模式 resolution 应为 1024")
        lat_id = ks.get("latent_image", [None])[0]
        lat = wf.get(lat_id, {})
        if lat.get("class_type") != "EmptyLatentImage":
            problems.append("t2i 模式 latent 应为 EmptyLatentImage")
        elif (lat["inputs"]["width"], lat["inputs"]["height"]) != (MASTER_W, MASTER_H):
            problems.append("t2i 模式 latent 尺寸应为 1024x576")
        if (ks["steps"], ks["cfg"]) != (STEPS, CFG):
            problems.append(f"t2i 模式采样应为 {STEPS} 步 / cfg {CFG}")
    if (ks.get("sampler_name"), ks.get("scheduler")) != ("euler", "simple"):
        problems.append("采样器应为 euler/simple")
    return problems


# --------------------------------------------------------------------------- #
# ComfyUI / 文件
# --------------------------------------------------------------------------- #
def http_json(url: str, payload: dict | None = None, timeout: int = 30) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with urllib.request.urlopen(f"{COMFY}/view?{query}", timeout=120) as resp:
        data = resp.read()
    with open(dst, "wb") as fh:
        fh.write(data)


def upload_image(path: str) -> str:
    """把本地参考图上传到 ComfyUI input，返回 LoadImage 可用的名字。"""
    with open(path, "rb") as fh:
        data = fh.read()
    digest = hashlib.sha1(data).hexdigest()[:8]
    filename = f"ch01_{os.path.splitext(os.path.basename(path))[0]}_{digest}.png"
    boundary = "----ch01" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + data + b"\r\n"
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
        f"true\r\n"
    ).encode("utf-8")
    body += f"--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{COMFY}/upload/image", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]


def master_path(node_id: str, frame: str) -> str:
    return os.path.join(MASTER_DIR, f"{node_id}_{frame}.png")


def delivery_path(node_id: str, frame: str) -> str:
    return os.path.join(OUT_DIR, f"{node_id}_{frame}.png")


def archive_existing(node_id: str, frame: str) -> list[str]:
    """--force 重跑前把旧母版/交付移到 _wip/，不丢旧版本。"""
    stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    moved = []
    for kind, src in (("master", master_path(node_id, frame)), ("delivery", delivery_path(node_id, frame))):
        if not os.path.exists(src):
            continue
        dst = os.path.join(WIP_DIR, f"{node_id}_{frame}.{kind}.{stamp}{os.path.splitext(src)[1]}")
        os.makedirs(WIP_DIR, exist_ok=True)
        os.replace(src, dst)
        moved.append(os.path.relpath(dst, ROOT))
    return moved


def already_done(node_id: str, frame: str) -> tuple[bool, str]:
    """交付帧存在且尺寸正确就算完成；不覆盖已验收的帧。"""
    d = delivery_path(node_id, frame)
    m = master_path(node_id, frame)
    if os.path.exists(d):
        try:
            if png_size(d) == (DELIVERY_W, DELIVERY_H):
                note = "" if os.path.exists(m) else "（母版缺失）"
                return True, note
        except (OSError, ValueError):
            pass
    return False, ""


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError:
            pass
    return {
        "chapter_id": CHAPTER_ID,
        "params": {
            "steps": STEPS, "cfg": CFG, "sampler": "euler", "scheduler": "simple", "denoise": 1.0,
            "master_px": [MASTER_W, MASTER_H], "delivery_px": [DELIVERY_W, DELIVERY_H],
            "resolution": 1024, "seed_base": SEED_BASE,
            "models": MODELS, "workflow": "qwen_image_2_1_t2i_minimal (TextEncodeQwenImage21 + EmptyLatentImage, no refs)",
            "negative": NEGATIVE, "suffix": SUFFIX,
        },
        "records": [],
    }


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def upsert_record(state: dict, record: dict) -> None:
    state["records"] = [
        r for r in state.get("records", [])
        if not (r.get("node_id") == record.get("node_id") and r.get("frame") == record.get("frame"))
    ]
    state["records"].append(record)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Generate chapter_01 first/last frames with local Qwen-Image 2.1")
    ap.add_argument("--only", action="append", default=[], metavar="NODE_ID",
                    help="只处理指定节点，可重复或逗号分隔")
    ap.add_argument("--frames", choices=["first", "last", "both"], default="both")
    ap.add_argument("--limit", type=int, default=0, help="本次最多新生成几张（0 = 不限）")
    ap.add_argument("--step", action="store_true", help="逐帧模式：本次只生成下一张待处理帧")
    ap.add_argument("--force", action="store_true", help="覆盖重跑：旧母版/交付先移到 _wip/ 留档")
    ap.add_argument("--ref-mode", nargs="?", const="auto", default="auto", choices=["auto", "t2i"],
                    help="auto：有角色就带参考图（16 步/cfg 2.5），无角色走 t2i；t2i：全部纯文生图")
    ap.add_argument("--dry-run", action="store_true", help="只打印并校验工作流 JSON，不提交")
    ap.add_argument("--timeout", type=int, default=1800, help="单张等待上限（秒）")
    ap.add_argument("--poll", type=int, default=5, help="轮询间隔（秒）")
    args = ap.parse_args()

    chapter = load_chapter()
    blocks = bible_character_blocks()
    jobs = frame_jobs(chapter, args.frames)
    upload_cache: dict[str, str] = {}

    only = set()
    for item in args.only:
        only.update(x.strip() for x in item.split(",") if x.strip())
    if only:
        known = {n.get("node_id") for n in chapter.get("nodes", [])}
        unknown = only - known
        if unknown:
            print(f"[error] 未知 node_id: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
        jobs = [j for j in jobs if j["node_id"] in only]
    if not jobs:
        print("[error] 没有匹配到任何帧", file=sys.stderr)
        return 1

    for job in jobs:
        key = (job["node_id"], job["frame"])
        override = NODE_PROMPT_OVERRIDE.get(key)
        if override:
            job["override"] = True
            characters = list(NODE_REF_OVERRIDE.get(key, []))
            use_refs = args.ref_mode != "t2i" and bool(characters)
            job["prompt"] = override.strip()
            job["characters"] = characters
        else:
            job["override"] = False
            use_refs = args.ref_mode != "t2i" and bool(characters_in(job["base_prompt"]))
            job["prompt"], job["characters"] = compose_prompt(
                job["base_prompt"], blocks, use_refs, NODE_PROMPT_APPEND.get(job["node_id"]))
        job["use_refs"] = use_refs
        job["ref_paths"] = [REF_FILES[k] for k in job["characters"]] if use_refs else []
        if use_refs:
            # dry-run 用本地文件名占位；真实运行时先上传再换成 ComfyUI 里的名字
            names = [os.path.basename(p) for p in job["ref_paths"]]
            job["workflow"] = build_ref_workflow(job["prompt"], job["seed"], names)
        else:
            job["workflow"] = build_workflow(job["prompt"], job["seed"])

    if args.dry_run:
        out = []
        for job in jobs:
            mode = "ref" if job["use_refs"] else "t2i"
            problems = validate_workflow(job["workflow"], mode)
            out.append({
                "node_id": job["node_id"],
                "frame": job["frame"],
                "seed": job["seed"],
                "mode": mode,
                "override": job.get("override", False),
                "steps": REF_STEPS if job["use_refs"] else STEPS,
                "cfg": REF_CFG if job["use_refs"] else CFG,
                "characters": job["characters"],
                "refs": [os.path.relpath(p, ROOT) for p in job["ref_paths"]],
                "prompt": job["prompt"],
                "negative": NEGATIVE,
                "problems": problems,
                "workflow": job["workflow"],
            })
        print(json.dumps({"chapter_id": CHAPTER_ID, "frames": out}, ensure_ascii=False, indent=2))
        bad = [f"{x['node_id']}/{x['frame']}: {p}" for x in out for p in x["problems"]]
        if bad:
            print("[error] 工作流校验失败：\n  " + "\n  ".join(bad), file=sys.stderr)
            return 1
        print(f"[dry-run] {len(out)} 帧，工作流 JSON 校验通过", file=sys.stderr)
        return 0

    os.makedirs(MASTER_DIR, exist_ok=True)
    state = load_state()
    if "params" not in state:
        state["params"] = load_state()["params"]

    pending = []
    for job in jobs:
        if not args.force:
            done, note = already_done(job["node_id"], job["frame"])
            if done:
                print(f"[skip] {job['node_id']}/{job['frame']} 已存在且尺寸正确{note}", flush=True)
                continue
        pending.append(job)

    if not pending:
        print("[done] 所有选中帧均已存在，无需生成", flush=True)
        return 0

    if args.step:
        args.limit = 1
    if args.limit:
        pending = pending[:args.limit]

    failures = 0
    for job in pending:
        node_id, frame = job["node_id"], job["frame"]
        seed = job["seed"]
        mpath = master_path(node_id, frame)
        dpath = delivery_path(node_id, frame)
        if args.force:
            for moved in archive_existing(node_id, frame):
                print(f"[wip] 旧版本已留档 {moved}", flush=True)
        started = time.time()
        prompt_id = None
        try:
            if job["use_refs"]:
                names = []
                for ref_path in job["ref_paths"]:
                    if ref_path not in upload_cache:
                        upload_cache[ref_path] = upload_image(ref_path)
                        print(f"[upload] {os.path.relpath(ref_path, ROOT)} -> {upload_cache[ref_path]}", flush=True)
                    names.append(upload_cache[ref_path])
                job["workflow"] = build_ref_workflow(job["prompt"], job["seed"], names)
            resp = http_json(f"{COMFY}/prompt", {"prompt": job["workflow"], "client_id": str(uuid.uuid4())})
            prompt_id = resp["prompt_id"]
            print(f"[submit] {node_id}/{frame} seed={seed} prompt_id={prompt_id}", flush=True)

            deadline = started + args.timeout
            history = None
            while time.time() < deadline:
                time.sleep(args.poll)
                hist = http_json(f"{COMFY}/history/{prompt_id}")
                if prompt_id in hist:
                    history = hist[prompt_id]
                    break
                print(f"[wait] {node_id}/{frame} {int(time.time() - started)}s", flush=True)
            if history is None:
                raise TimeoutError(f"ComfyUI 等待超过 {args.timeout}s")

            status = history.get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m and m[0] == "execution_error"]
                raise RuntimeError(f"ComfyUI 执行出错：{json.dumps(msgs, ensure_ascii=False)[:800]}")

            images = []
            for node_out in history.get("outputs", {}).values():
                images.extend(node_out.get("images", []))
            if not images:
                raise RuntimeError("history 里没有图片输出")

            download_image(images[0], mpath)
            scale_to(mpath, dpath, DELIVERY_W, DELIVERY_H)
            mw, mh = png_size(mpath)
            dw, dh = png_size(dpath)
            elapsed = round(time.time() - started, 1)

            record = {
                "node_id": node_id,
                "frame": frame,
                "seed": seed,
                "mode": "ref" if job["use_refs"] else "t2i",
                "steps": REF_STEPS if job["use_refs"] else STEPS,
                "cfg": REF_CFG if job["use_refs"] else CFG,
                "refs": [os.path.relpath(p, ROOT) for p in job["ref_paths"]],
                "characters": job["characters"],
                "prompt": job["prompt"],
                "negative": NEGATIVE,
                "prompt_id": prompt_id,
                "elapsed_sec": elapsed,
                "master_path": os.path.relpath(mpath, ROOT),
                "delivery_path": os.path.relpath(dpath, ROOT),
                "master_px": [mw, mh],
                "delivery_px": [dw, dh],
                "status": "ok",
                "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
            }
            upsert_record(state, record)
            save_state(state)
            print(f"[done] {node_id}/{frame} {elapsed}s {mw}x{mh} -> {dw}x{dh} {os.path.relpath(dpath, ROOT)}", flush=True)
        except Exception as exc:  # noqa: BLE001 —— 单帧失败不影响后续，错误原文保留
            elapsed = round(time.time() - started, 1)
            failures += 1
            record = {
                "node_id": node_id, "frame": frame, "seed": seed,
                "mode": "ref" if job["use_refs"] else "t2i",
                "steps": REF_STEPS if job["use_refs"] else STEPS,
                "cfg": REF_CFG if job["use_refs"] else CFG,
                "refs": [os.path.relpath(p, ROOT) for p in job["ref_paths"]],
                "characters": job["characters"], "prompt": job["prompt"], "negative": NEGATIVE,
                "prompt_id": prompt_id, "elapsed_sec": elapsed,
                "master_path": os.path.relpath(mpath, ROOT),
                "delivery_path": os.path.relpath(dpath, ROOT),
                "status": "error", "error": f"{type(exc).__name__}: {exc}",
                "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
            }
            upsert_record(state, record)
            save_state(state)
            print(f"[error] {node_id}/{frame} {record['error']}", file=sys.stderr, flush=True)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
