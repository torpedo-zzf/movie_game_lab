#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T-017 第一章音频构建：TTS / SFX / BGM / 混音 / 回填 / 校验

只依赖 Python 标准库 + 本机 `say` 与 `ffmpeg/ffprobe`，不联网、不装第三方库。

用法：
  python3 scripts/build_audio_chapter_01.py                # 构建除 s01/s07/s08 外的 9 条
  python3 scripts/build_audio_chapter_01.py --dry-run      # 只打印时间轴，不写文件
  python3 scripts/build_audio_chapter_01.py --only s02,s03 # 只处理指定节点（短名或 node_id）
  python3 scripts/build_audio_chapter_01.py --skip-existing
  python3 scripts/build_audio_chapter_01.py --force-tts    # 重做 TTS
  python3 scripts/build_audio_chapter_01.py --force        # 重做 TTS/SFX/BGM 与混音
  python3 scripts/build_audio_chapter_01.py --verify-only  # 只复测成片，不重混

重拍完成后补跑：
  python3 scripts/build_audio_chapter_01.py --only s01,s07,s08 --allow-pending

产物：
  assets/audio/tts/<node>.wav             48k 单声道 TTS
  assets/audio/sfx/<id>.wav               21 个音效调色板（48k 单声道，时长 >= 设计）
  assets/audio/bgm/{tension,ending_a,ending_b}.wav  可循环 BGM（48k 单声道）
  assets/audio/mix/<node>.wav             48k 立体声混音母版（-16 LUFS）
  assets/audio/qc/*.png                   抽帧 + 波形对照图
  assets/videos/raw/<node>.mp4            原始视频备份（只写一次）
  assets/videos/<node>.mp4                回填音轨后的成片（视频流 -c:v copy）
  state/audio_build_chapter_01.json       构建状态
  assets/audio/report_chapter_01.md       人读报告
"""

from __future__ import annotations

import argparse
import array
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "story" / "04_audio" / "audio_design_chapter_01.json"
STORY_PATH = ROOT / "story" / "03_storyboards" / "chapter_01.json"
VIDEOS_DIR = ROOT / "assets" / "videos"
RAW_DIR = VIDEOS_DIR / "raw"
AUDIO_DIR = ROOT / "assets" / "audio"
TTS_DIR = AUDIO_DIR / "tts"
SFX_DIR = AUDIO_DIR / "sfx"
BGM_DIR = AUDIO_DIR / "bgm"
MIX_DIR = AUDIO_DIR / "mix"
QC_DIR = AUDIO_DIR / "qc"
STATE_PATH = ROOT / "state" / "audio_build_chapter_01.json"
REPORT_PATH = AUDIO_DIR / "report_chapter_01.md"

SR = 48000
TARGET_LUFS = -16.0
TRUE_PEAK = -1.5
LIMIT_LINEAR = 10 ** (TRUE_PEAK / 20.0)  # 0.841
ORIG_GAIN_DB = -20.0                     # 原声压低
SIDECHAIN = "sidechaincompress=threshold=0.04:ratio=6:attack=15:release=420:makeup=1"
SCRIPT_VERSION = "1.0.0"

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# 正在重拍，默认绝不处理；重拍完成后显式 --allow-pending 才处理
PENDING_RESHOOT = (
    "ch01_s01_voiceover",
    "ch01_s07_elevator",
    "ch01_s08_groupchat",
)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd, check: bool = True, binary: bool = False):
    p = subprocess.run(
        [str(c) for c in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
    )
    if check and p.returncode != 0:
        err = p.stderr if not binary else p.stderr.decode("utf-8", "replace")
        out = p.stdout if not binary else p.stdout.decode("utf-8", "replace")
        raise RuntimeError(
            "命令失败 (%s): %s\n--- stderr ---\n%s\n--- stdout ---\n%s"
            % (p.returncode, " ".join(str(c) for c in cmd), err[-5000:], out[-2000:])
        )
    return p


def ffmpeg(args, check: bool = True):
    return run([FFMPEG, "-hide_banner", "-nostats", "-y"] + list(args), check=check)


def probe(path) -> dict:
    p = run([
        FFPROBE, "-v", "error",
        "-show_entries",
        "stream=index,codec_type,codec_name,width,height,sample_rate,channels,nb_frames,bit_rate:format=duration,size",
        "-of", "json", str(path),
    ])
    return json.loads(p.stdout)


def probe_duration(path) -> float:
    info = probe(path)
    try:
        return float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return 0.0


def media_streams(path) -> tuple[dict | None, dict | None]:
    info = probe(path)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    return v, a


def measure_max_volume(path) -> float:
    p = run([
        FFMPEG, "-hide_banner", "-nostats", "-i", str(path),
        "-af", "volumedetect", "-f", "null", "-",
    ], check=False)
    text = (p.stdout or "") + (p.stderr or "")
    vals = re.findall(r"max_volume:\s*(-?(?:\d+(?:\.\d+)?|inf))\s*dB", text)
    if not vals:
        return -999.0
    try:
        return float(vals[-1])
    except ValueError:
        return -999.0


def measure_loudness(path) -> dict | None:
    """用 loudnorm 的 JSON 统计测整片响度；返回 input_i/tp/lra/thresh/target_offset。"""
    p = run([
        FFMPEG, "-hide_banner", "-nostats", "-i", str(path),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ], check=False)
    text = (p.stdout or "") + (p.stderr or "")
    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", text, flags=re.S)
    for block in reversed(blocks):
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue
        out = {}
        for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
            try:
                out[k] = float(obj.get(k))
            except (TypeError, ValueError):
                return None
        return out
    return None


def measure_ebur128(path) -> dict | None:
    """独立用 ebur128 测整片 Integrated / LRA / True Peak。"""
    p = run([
        FFMPEG, "-hide_banner", "-nostats", "-i", str(path),
        "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-",
    ], check=False)
    text = (p.stdout or "") + (p.stderr or "")
    i_vals = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", text)
    lra_vals = re.findall(r"LRA:\s*(-?[\d.]+)\s*LU", text)
    tp_vals = re.findall(r"Peak:\s*(-?[\d.]+)\s*dBFS", text)
    if not i_vals:
        return None
    try:
        return {
            "lufs": float(i_vals[-1]),
            "lra": float(lra_vals[-1]) if lra_vals else None,
            "true_peak_db": float(tp_vals[-1]) if tp_vals else None,
        }
    except ValueError:
        return None


def astats_summary(path) -> dict:
    p = run([
        FFMPEG, "-hide_banner", "-nostats", "-i", str(path),
        "-map", "0:a:0", "-af", "astats=metadata=1:reset=0", "-f", "null", "-",
    ], check=False)
    text = (p.stdout or "") + (p.stderr or "")
    def last(pattern):
        vals = re.findall(pattern, text)
        return vals[-1] if vals else None
    rms = last(r"RMS level dB:\s*(-?(?:\d+(?:\.\d+)?|-?inf))")
    peak = last(r"Peak level dB:\s*(-?(?:\d+(?:\.\d+)?|-?inf))")
    flat = last(r"Flat factor:\s*([\d.]+)")
    def f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return {"rms_db": f(rms), "peak_db": f(peak), "flat_factor": f(flat)}


def video_md5(path) -> str:
    p = run([
        FFMPEG, "-v", "error", "-i", str(path),
        "-map", "0:v:0", "-c", "copy", "-f", "md5", "-",
    ])
    return (p.stdout or "").strip().split("=")[-1]


# ---------------------------------------------------------------------------
# WAV 写入 / 归一化
# ---------------------------------------------------------------------------

def write_wav(path: Path, samples, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = array.array("h")
    for x in samples:
        if x > 1.0:
            x = 1.0
        elif x < -1.0:
            x = -1.0
        data.append(int(round(x * 32767.0)))
    tmp = path.with_suffix(".tmp.wav")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
    os.replace(tmp, path)


def rms_of(samples) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(x * x for x in samples) / len(samples))


def normalize(samples, peak_db=None, rms_db=None, ceiling_db=-1.0):
    peak = max((abs(x) for x in samples), default=0.0)
    if peak <= 1e-12:
        return samples
    if rms_db is not None:
        r = rms_of(samples)
        if r <= 1e-12:
            return samples
        gain = (10 ** (rms_db / 20.0)) / r
        ceiling = 10 ** (ceiling_db / 20.0)
        if peak * gain > ceiling:
            gain = ceiling / peak
    else:
        gain = (10 ** ((peak_db if peak_db is not None else -3.0) / 20.0)) / peak
    return [x * gain for x in samples]


def fade_edges(samples, ms: float = 8.0):
    n = min(len(samples) // 2, int(SR * ms / 1000.0))
    for i in range(n):
        g = i / float(n)
        samples[i] *= g
        samples[-1 - i] *= g
    return samples


# ---------------------------------------------------------------------------
# DSP 小工具（纯 stdlib）
# ---------------------------------------------------------------------------

class Biquad:
    __slots__ = ("b0", "b1", "b2", "a1", "a2", "z1", "z2")

    def __init__(self, kind: str, freq: float, q: float = 0.707, gain_db: float = 0.0, sr: int = SR):
        freq = max(20.0, min(freq, sr * 0.45))
        w0 = 2.0 * math.pi * freq / sr
        cw = math.cos(w0)
        sw = math.sin(w0)
        alpha = sw / (2.0 * max(q, 0.05))
        if kind == "lp":
            b0 = (1.0 - cw) / 2.0
            b1 = 1.0 - cw
            b2 = b0
            a0 = 1.0 + alpha
            a1 = -2.0 * cw
            a2 = 1.0 - alpha
        elif kind == "hp":
            b0 = (1.0 + cw) / 2.0
            b1 = -(1.0 + cw)
            b2 = b0
            a0 = 1.0 + alpha
            a1 = -2.0 * cw
            a2 = 1.0 - alpha
        elif kind == "bp":
            b0 = alpha
            b1 = 0.0
            b2 = -alpha
            a0 = 1.0 + alpha
            a1 = -2.0 * cw
            a2 = 1.0 - alpha
        elif kind == "peak":
            a = 10 ** (gain_db / 40.0)
            b0 = 1.0 + alpha * a
            b1 = -2.0 * cw
            b2 = 1.0 - alpha * a
            a0 = 1.0 + alpha / a
            a1 = -2.0 * cw
            a2 = 1.0 - alpha / a
        else:
            raise ValueError(kind)
        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0
        self.z1 = 0.0
        self.z2 = 0.0

    def process(self, x: float) -> float:
        y = self.b0 * x + self.z1
        self.z1 = self.b1 * x - self.a1 * y + self.z2
        self.z2 = self.b2 * x - self.a2 * y
        return y


def apply_filters(samples, specs):
    seg = samples
    for kind, freq, q in specs:
        f = Biquad(kind, freq, q)
        seg = [f.process(x) for x in seg]
    return seg


def smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def env_ar(t: float, dur: float, attack: float, release: float) -> float:
    if attack > 0 and t < attack:
        return smoothstep(t / attack)
    if release > 0 and t > dur - release:
        return smoothstep((dur - t) / release)
    return 1.0


def add_sine(buf, t0, dur, freq, amp, env=None, phase=0.0):
    i0 = int(t0 * SR)
    n = int(dur * SR)
    w = 2.0 * math.pi * freq
    for i in range(n):
        j = i0 + i
        if j < 0 or j >= len(buf):
            continue
        e = env(i / SR) if env else 1.0
        buf[j] += amp * e * math.sin(w * (i / SR) + phase)


def add_noise(buf, t0, dur, rng, amp=0.1, kind="white", filters=(), env=None, decay=0.0):
    n = int(dur * SR)
    seg = [rng.uniform(-1.0, 1.0) for _ in range(n)]
    if kind == "brown":
        b = 0.0
        brown = []
        for x in seg:
            b = 0.995 * b + 0.02 * x
            brown.append(b)
        seg = brown
    if filters:
        seg = apply_filters(seg, filters)
    i0 = int(t0 * SR)
    for i in range(n):
        j = i0 + i
        if j < 0 or j >= len(buf):
            continue
        u = i / SR
        e = env(u) if env else 1.0
        if decay > 0:
            e *= math.exp(-u / decay)
        buf[j] += amp * e * seg[i]


def add_knock(buf, t, rng, amp=0.8, base=68.0):
    add_sine(buf, t, 0.45, base, amp,
             env=lambda u: math.exp(-u / 0.05) * min(1.0, u / 0.002))
    add_sine(buf, t, 0.22, base * 1.63, amp * 0.32,
             env=lambda u: math.exp(-u / 0.035))
    add_noise(buf, t, 0.08, rng, amp * 0.5,
              filters=[("lp", 420.0, 0.8)], decay=0.02)
    add_noise(buf, t, 0.015, rng, amp * 0.28,
              filters=[("bp", 2500.0, 1.0)], decay=0.004)


def add_metal_click(buf, t, rng, amp=0.6, f1=2900.0, f2=4300.0):
    add_noise(buf, t, 0.05, rng, amp * 0.7,
              filters=[("bp", 3300.0, 2.0)], decay=0.012)
    add_sine(buf, t, 0.5, f1, amp * 0.16, env=lambda u: math.exp(-u / 0.2))
    add_sine(buf, t, 0.35, f2, amp * 0.09, env=lambda u: math.exp(-u / 0.13))
    add_sine(buf, t, 0.15, 118.0, amp * 0.12, env=lambda u: math.exp(-u / 0.04))


def loopify(buf, fade_sec: float = 1.0):
    f = int(fade_sec * SR)
    n = len(buf) - f
    if n <= 0 or f <= 0:
        return buf
    out = list(buf[:n])
    for i in range(f):
        w = smoothstep(i / float(f))
        out[i] = buf[i] * w + buf[n + i] * (1.0 - w)
    return out


# ---------------------------------------------------------------------------
# SFX 合成：19 个设计 id + 2 个预留调色板 id = 21
# ---------------------------------------------------------------------------

def sfx_room_tone(rng, dur):
    n = int(dur * SR)
    b = 0.0
    raw = []
    for _ in range(n):
        b = 0.996 * b + 0.02 * rng.uniform(-1.0, 1.0)
        raw.append(b)
    lp = Biquad("lp", 260.0, 0.7)
    out = [lp.process(x) * 0.9 for x in raw]
    add_sine(out, 0.0, dur, 50.0, 0.05,
             env=lambda u: 1.0 + 0.12 * math.sin(2 * math.pi * 0.09 * u))
    add_sine(out, 0.0, dur, 100.0, 0.016)
    add_sine(out, 0.0, dur, 150.0, 0.005)
    for _ in range(int(dur * 1.2)):
        t = rng.uniform(0.0, max(0.01, dur - 0.02))
        add_noise(out, t, 0.004, rng, 0.02,
                  filters=[("bp", 2200.0, 1.5)], decay=0.002)
    return out, {"rms_db": -12.0, "ceiling_db": -4.0}


def sfx_corridor_drag(rng, dur):
    n = int(dur * SR)
    b = 0.0
    raw = []
    for _ in range(n):
        b = 0.995 * b + 0.02 * rng.uniform(-1.0, 1.0)
        raw.append(b)
    lp = Biquad("lp", 190.0, 0.7)
    low = [lp.process(x) for x in raw]
    out = [0.0] * n
    for i in range(n):
        u = i / SR
        env = env_ar(u, dur, 0.35, 0.6) * (0.55 + 0.45 * math.sin(2 * math.pi * 0.8 * u) ** 2)
        out[i] = low[i] * env * 1.1
    add_noise(out, 0.0, dur, rng, 0.16,
              filters=[("bp", 950.0, 0.7)],
              env=lambda u: env_ar(u, dur, 0.4, 0.7) * (0.4 + 0.6 * math.sin(2 * math.pi * 1.7 * u) ** 2))
    for t in (0.45, 1.15, 1.78, 2.25):
        add_noise(out, t, 0.12, rng, 0.28,
                  filters=[("lp", 320.0, 1.0)], decay=0.045)
    return out, {"peak_db": -5.0}


def sfx_peephole_metal(rng, dur):
    out = [0.0] * int(dur * SR)
    for t, a in ((0.02, 1.0), (0.30, 0.55)):
        add_noise(out, t, 0.05, rng, 0.7 * a,
                  filters=[("bp", 3400.0, 2.2)], decay=0.012)
        add_sine(out, t, 0.5, 2870.0, 0.16 * a, env=lambda u: math.exp(-u / 0.22))
        add_sine(out, t, 0.4, 4310.0, 0.09 * a, env=lambda u: math.exp(-u / 0.16))
        add_sine(out, t, 0.15, 118.0, 0.12 * a, env=lambda u: math.exp(-u / 0.045))
    add_noise(out, 0.02, min(dur, 0.7), rng, 0.035,
              filters=[("bp", 2800.0, 3.0)], decay=0.2)
    return out, {"peak_db": -4.0}


def sfx_carpet_drag(rng, dur):
    out = [0.0] * int(dur * SR)
    add_noise(out, 0.0, dur, rng, 1.0, kind="brown",
              filters=[("lp", 250.0, 0.75)],
              env=lambda u: env_ar(u, dur, 0.35, 0.7) * (0.5 + 0.5 * math.sin(2 * math.pi * 0.55 * u) ** 2))
    add_noise(out, 0.0, dur, rng, 0.22,
              filters=[("bp", 720.0, 0.8)],
              env=lambda u: env_ar(u, dur, 0.4, 0.8) * (0.35 + 0.65 * math.sin(2 * math.pi * 1.3 * u + 1.0) ** 2))
    add_noise(out, 0.0, dur, rng, 0.09,
              filters=[("bp", 1600.0, 0.6)],
              env=lambda u: env_ar(u, dur, 0.5, 0.8) * (0.3 + 0.7 * math.sin(2 * math.pi * 2.1 * u + 2.0) ** 2))
    t = 0.55
    while t < dur - 0.2:
        add_noise(out, t + rng.uniform(-0.06, 0.06), 0.12, rng, 0.22,
                  filters=[("lp", 300.0, 1.1)], decay=0.04)
        t += rng.uniform(0.55, 0.8)
    return out, {"peak_db": -5.0}


def sfx_knock_three(rng, dur):
    out = [0.0] * int(dur * SR)
    for i, t in enumerate((0.03, 0.37, 0.70)):
        add_knock(out, t, rng, amp=(0.72, 0.9, 0.8)[i], base=67.0)
    return out, {"peak_db": -3.0}


def sfx_keys_jingle(rng, dur):
    out = [0.0] * int(dur * SR)
    clusters = [(0.03, 0.38), (0.88, 1.18)]
    for lo, hi in clusters:
        for _ in range(7):
            t = rng.uniform(lo, hi)
            f = rng.uniform(1800.0, 5600.0)
            a = rng.uniform(0.12, 0.4)
            add_sine(out, t, 0.55, f, a, env=lambda u: math.exp(-u / rng.uniform(0.12, 0.32)))
            add_sine(out, t, 0.3, f * 1.51, a * 0.35,
                     env=lambda u: math.exp(-u / 0.09))
            add_noise(out, t, 0.012, rng, a * 0.4,
                      filters=[("bp", 4500.0, 1.2)], decay=0.003)
    add_noise(out, 0.0, min(dur, 0.9), rng, 0.04,
              filters=[("bp", 3800.0, 0.7)],
              env=lambda u: env_ar(u, dur, 0.05, 0.4))
    return out, {"peak_db": -5.0}


def sfx_door_open_creak(rng, dur):
    out = [0.0] * int(dur * SR)
    creak_dur = min(1.55, max(0.6, dur - 0.3))
    n = int(creak_dur * SR)
    phase = 0.0
    raw = []
    for i in range(n):
        t = i / SR
        f = (170.0
             + 240.0 * (0.5 + 0.5 * math.sin(2 * math.pi * 0.55 * t + 0.7))
             + 30.0 * math.sin(2 * math.pi * 2.3 * t))
        phase += 2.0 * math.pi * f / SR
        saw = 2.0 * ((phase / (2.0 * math.pi)) % 1.0) - 1.0
        grain = 0.55 + 0.45 * math.sin(2 * math.pi * 14.0 * t + 1.1 * math.sin(2 * math.pi * 0.8 * t))
        env = min(1.0, t / 0.2) * min(1.0, (creak_dur - t) / 0.35)
        raw.append(saw * grain * max(0.0, env))
    raw = apply_filters(raw, [("bp", 620.0, 3.0), ("peak", 1600.0, 1.0)])
    for i in range(n):
        out[i] += raw[i] * 0.9
    thud_t = creak_dur + 0.05
    add_sine(out, thud_t, 0.35, 70.0, 0.5, env=lambda u: math.exp(-u / 0.06))
    add_noise(out, thud_t, 0.1, rng, 0.2, filters=[("lp", 400.0, 0.9)], decay=0.03)
    add_metal_click(out, min(dur - 0.12, thud_t + 0.08), rng, amp=0.3, f1=2200.0, f2=3500.0)
    return out, {"peak_db": -4.0}


def sfx_heartbeat(rng, dur):
    out = [0.0] * int(dur * SR)
    t = 0.06
    while t < dur - 0.15:
        add_sine(out, t, 0.35, 55.0, 0.85, env=lambda u: math.exp(-u / 0.072) * min(1.0, u / 0.006))
        add_sine(out, t + 0.22, 0.35, 47.0, 0.55, env=lambda u: math.exp(-u / 0.095) * min(1.0, u / 0.006))
        add_noise(out, t, 0.14, rng, 0.18, filters=[("lp", 180.0, 0.8)], decay=0.04)
        t += 0.86
    return out, {"peak_db": -4.0}


def sfx_door_lock_click(rng, dur):
    out = [0.0] * int(dur * SR)
    add_metal_click(out, 0.02, rng, amp=0.9, f1=1900.0, f2=3100.0)
    add_sine(out, 0.02, 0.2, 92.0, 0.45, env=lambda u: math.exp(-u / 0.035))
    add_metal_click(out, 0.14, rng, amp=0.35, f1=2400.0, f2=3900.0)
    add_noise(out, 0.26, 0.05, rng, 0.12, filters=[("bp", 2900.0, 1.4)], decay=0.008)
    return out, {"peak_db": -2.5}


def sfx_footsteps_hall(rng, dur):
    out = [0.0] * int(dur * SR)
    t = 0.08
    step = 0
    while t < dur - 0.2:
        amp = 0.75 * (0.86 ** step)
        add_sine(out, t, 0.28, 88.0 + rng.uniform(-6, 6), amp,
                 env=lambda u: math.exp(-u / 0.055) * min(1.0, u / 0.004))
        add_noise(out, t, 0.09, rng, amp * 0.4,
                  filters=[("bp", 900.0, 0.9)], decay=0.025)
        add_noise(out, t, 0.04, rng, amp * 0.2,
                  filters=[("bp", 2600.0, 1.2)], decay=0.01)
        step += 1
        t += 0.44 + rng.uniform(-0.02, 0.03)
    # 简易走廊混响
    tail = list(out)
    for d, g in ((0.06, 0.25), (0.11, 0.16), (0.19, 0.1), (0.31, 0.06)):
        shift = int(d * SR)
        for i in range(len(out) - shift):
            tail[i + shift] += out[i] * g
    return tail, {"peak_db": -5.0}


def sfx_elevator_hum(rng, dur):
    out = [0.0] * int(dur * SR)
    add_sine(out, 0.0, dur, 55.0, 0.12,
             env=lambda u: 0.8 + 0.2 * math.sin(2 * math.pi * 0.07 * u))
    add_sine(out, 0.0, dur, 55.8, 0.08)
    add_sine(out, 0.0, dur, 110.0, 0.05)
    add_sine(out, 0.0, dur, 165.0, 0.015)
    add_sine(out, 0.0, dur, 220.0, 0.008)
    add_sine(out, 0.0, dur, 420.0, 0.004,
             env=lambda u: 0.5 + 0.5 * math.sin(2 * math.pi * 0.23 * u + 1.0))
    add_noise(out, 0.0, dur, rng, 0.05, filters=[("lp", 180.0, 0.7)])
    fade_edges(out, 120)
    return out, {"rms_db": -12.0, "ceiling_db": -4.0}


def sfx_elevator_ding(rng, dur):
    out = [0.0] * int(dur * SR)
    for f, a, d in ((880.0, 0.35, 1.1), (1760.0, 0.16, 0.8),
                    (2640.0, 0.07, 0.55), (2350.0, 0.05, 0.45)):
        add_sine(out, 0.02, min(d, dur), f, a, env=lambda u: math.exp(-u / (d * 0.35)))
    add_noise(out, 0.02, 0.02, rng, 0.2, filters=[("bp", 4000.0, 1.0)], decay=0.004)
    return out, {"peak_db": -5.0}


def sfx_phone_notify(rng, dur):
    out = [0.0] * int(dur * SR)
    for t, f, a, dec in ((0.03, 1318.5, 0.3, 0.2), (0.22, 1046.5, 0.34, 0.32)):
        add_sine(out, t, min(0.5, dur - t), f, a,
                 env=lambda u: math.exp(-u / dec) * min(1.0, u / 0.004))
        add_sine(out, t, min(0.35, dur - t), f * 2.0, a * 0.25,
                 env=lambda u: math.exp(-u / (dec * 0.6)))
    add_noise(out, 0.225, 0.008, rng, 0.05, filters=[("bp", 3000.0, 1.2)], decay=0.002)
    return out, {"peak_db": -5.0}


def sfx_police_siren_far(rng, dur):
    n = int(dur * SR)
    phase = 0.0
    raw = []
    for i in range(n):
        t = i / SR
        f = (850.0
             + 150.0 * math.tanh(3.2 * math.sin(2 * math.pi * 0.42 * t))
             + 12.0 * math.sin(2 * math.pi * 5.2 * t))
        phase += 2.0 * math.pi * f / SR
        dist = env_ar(t, dur, min(1.0, dur * 0.3), min(1.0, dur * 0.25))
        raw.append(math.sin(phase) * dist * 0.9)
    raw = apply_filters(raw, [("lp", 1500.0, 0.7), ("peak", 900.0, 0.9)])
    out = raw
    add_noise(out, 0.0, dur, rng, 0.12, kind="brown",
              filters=[("lp", 300.0, 0.7)],
              env=lambda u: env_ar(u, dur, 0.8, 0.8))
    # 远处反射
    tail = list(out)
    for d, g in ((0.13, 0.2), (0.27, 0.1)):
        shift = int(d * SR)
        for i in range(len(out) - shift):
            tail[i + shift] += out[i] * g
    return tail, {"peak_db": -8.0}


def sfx_knock_hard(rng, dur):
    out = [0.0] * int(dur * SR)
    for i, t in enumerate((0.03, 0.36, 0.68)):
        add_knock(out, t, rng, amp=(0.95, 1.15, 1.05)[i], base=52.0)
        add_noise(out, t + 0.01, 0.16, rng, 0.2,
                  filters=[("bp", 480.0, 1.2)], decay=0.04)
    return out, {"peak_db": -2.5}


def sfx_radio_squelch(rng, dur):
    out = [0.0] * int(dur * SR)
    add_noise(out, 0.02, min(0.42, dur - 0.1), rng, 0.5,
              filters=[("bp", 1800.0, 0.7)],
              env=lambda u: env_ar(u, min(0.42, dur - 0.1), 0.01, 0.12)
              * (0.5 + 0.5 * math.sin(2 * math.pi * 37.0 * u) ** 2))
    add_noise(out, 0.02, 0.02, rng, 0.35, filters=[("hp", 2000.0, 0.7)], decay=0.005)
    add_sine(out, 0.05, min(0.5, dur - 0.05), 900.0, 0.03,
             env=lambda u: 0.5 + 0.5 * math.sin(2 * math.pi * 7.0 * u))
    tail = min(0.3, max(0.05, dur - 0.55))
    add_noise(out, min(0.5, dur - 0.35), tail, rng, 0.16,
              filters=[("hp", 1200.0, 0.8)], decay=tail * 0.5)
    add_noise(out, min(dur - 0.08, 0.95), 0.02, rng, 0.2,
              filters=[("bp", 2600.0, 1.2)], decay=0.004)
    return out, {"peak_db": -6.0}


def sfx_gurney_wheels(rng, dur):
    out = [0.0] * int(dur * SR)
    n = len(out)
    b = 0.0
    for i in range(n):
        t = i / SR
        b = 0.995 * b + 0.02 * rng.uniform(-1.0, 1.0)
        env = env_ar(t, dur, min(0.7, dur * 0.3), min(0.7, dur * 0.25))
        out[i] += b * env * 1.8
    add_sine(out, 0.0, dur, 65.0, 0.1,
             env=lambda u: env_ar(u, dur, 0.5, 0.5) * (0.7 + 0.3 * math.sin(2 * math.pi * 1.2 * u)))
    # 轮子过缝的 clatter
    t = 0.1
    while t < dur - 0.12:
        add_noise(out, t, 0.05, rng, 0.16,
                  filters=[("bp", 2100.0, 1.4)], decay=0.012)
        add_sine(out, t, 0.12, rng.uniform(1100.0, 1800.0), 0.045,
                 env=lambda u: math.exp(-u / 0.025))
        t += 0.17 + rng.uniform(-0.012, 0.012)
    # 一只轮子的吱声
    add_sine(out, 0.3, max(0.2, dur - 0.6), 1450.0, 0.035,
             env=lambda u: env_ar(u, max(0.2, dur - 0.6), 0.2, 0.3)
             * (0.6 + 0.4 * math.sin(2 * math.pi * 4.5 * u)))
    add_noise(out, 0.0, dur, rng, 0.05,
              filters=[("bp", 850.0, 0.7)],
              env=lambda u: env_ar(u, dur, 0.5, 0.5))
    return out, {"peak_db": -6.0}


def sfx_delete_confirm(rng, dur):
    out = [0.0] * int(dur * SR)
    for t, f, a in ((0.02, 1174.66, 0.2), (0.18, 880.0, 0.24)):
        add_sine(out, t, min(0.22, dur - t), f, a,
                 env=lambda u: math.exp(-u / 0.08) * min(1.0, u / 0.004))
        add_sine(out, t, min(0.18, dur - t), f * 2.0, a * 0.18,
                 env=lambda u: math.exp(-u / 0.05))
    add_noise(out, 0.02, 0.008, rng, 0.06, filters=[("bp", 3500.0, 1.2)], decay=0.002)
    return out, {"peak_db": -7.0}


def sfx_light_switch(rng, dur):
    out = [0.0] * int(dur * SR)
    add_noise(out, 0.02, 0.012, rng, 0.75,
              filters=[("bp", 2800.0, 1.4)], decay=0.003)
    add_sine(out, 0.02, 0.12, 165.0, 0.28, env=lambda u: math.exp(-u / 0.02))
    add_sine(out, 0.02, 0.18, 920.0, 0.08, env=lambda u: math.exp(-u / 0.035))
    add_noise(out, 0.11, 0.008, rng, 0.3, filters=[("bp", 3200.0, 1.5)], decay=0.002)
    return out, {"peak_db": -4.0}


def sfx_door_close_soft(rng, dur):
    out = [0.0] * int(dur * SR)
    add_noise(out, 0.0, min(0.3, dur), rng, 0.12,
              filters=[("bp", 700.0, 2.0)], decay=0.08)
    add_sine(out, min(0.55, dur - 0.4), 0.4, 66.0, 0.55,
             env=lambda u: math.exp(-u / 0.075) * min(1.0, u / 0.004))
    add_noise(out, min(0.55, dur - 0.4), 0.12, rng, 0.25,
              filters=[("lp", 380.0, 0.9)], decay=0.04)
    add_metal_click(out, min(dur - 0.1, 0.7), rng, amp=0.35, f1=2100.0, f2=3300.0)
    return out, {"peak_db": -4.0}


def sfx_phone_vibrate(rng, dur):
    out = [0.0] * int(dur * SR)
    for i in range(len(out)):
        t = i / SR
        env = env_ar(t, dur, 0.02, 0.1)
        out[i] += 0.35 * env * math.sin(2 * math.pi * 155.0 * t) * (0.55 + 0.45 * math.sin(2 * math.pi * 27.0 * t))
    add_noise(out, 0.0, dur, rng, 0.08, filters=[("bp", 800.0, 1.0)],
              env=lambda u: env_ar(u, dur, 0.02, 0.1))
    return out, {"peak_db": -5.0}


SFX_ORDER = [
    "room_tone", "corridor_drag", "peephole_metal", "carpet_drag", "knock_three",
    "keys_jingle", "door_open_creak", "heartbeat", "door_lock_click", "footsteps_hall",
    "elevator_hum", "elevator_ding", "phone_notify", "police_siren_far", "knock_hard",
    "radio_squelch", "gurney_wheels", "delete_confirm", "light_switch",
    # 预留调色板（本章未引用，供后续章节复用）
    "door_close_soft", "phone_vibrate",
]

SFX_BUILDERS = {
    "room_tone": (sfx_room_tone, 8.5, "深夜室内底噪/电流声"),
    "corridor_drag": (sfx_corridor_drag, 2.6, "走廊拖行（低频摩擦+织物）"),
    "peephole_metal": (sfx_peephole_metal, 1.0, "猫眼金属罩轻响"),
    "carpet_drag": (sfx_carpet_drag, 5.0, "暗红地毯拖地"),
    "knock_three": (sfx_knock_three, 1.3, "三下沉闷敲门"),
    "keys_jingle": (sfx_keys_jingle, 1.5, "钥匙串轻响"),
    "door_open_creak": (sfx_door_open_creak, 1.8, "防盗门开启吱呀+落锁"),
    "heartbeat": (sfx_heartbeat, 4.2, "心跳（lub-dub）"),
    "door_lock_click": (sfx_door_lock_click, 0.7, "锁舌扣入/门链"),
    "footsteps_hall": (sfx_footsteps_hall, 2.6, "走廊脚步远去"),
    "elevator_hum": (sfx_elevator_hum, 7.5, "电梯停层低频嗡鸣"),
    "elevator_ding": (sfx_elevator_ding, 1.5, "层站提示音"),
    "phone_notify": (sfx_phone_notify, 1.1, "手机通知双音"),
    "police_siren_far": (sfx_police_siren_far, 4.2, "远处警笛由远及近"),
    "knock_hard": (sfx_knock_hard, 1.3, "三下更重的敲门"),
    "radio_squelch": (sfx_radio_squelch, 1.2, "警用对讲机电流/静噪"),
    "gurney_wheels": (sfx_gurney_wheels, 2.8, "担架轮子经过"),
    "delete_confirm": (sfx_delete_confirm, 0.9, "删除录音确认音"),
    "light_switch": (sfx_light_switch, 0.6, "关灯开关"),
    "door_close_soft": (sfx_door_close_soft, 1.4, "轻合门（预留）"),
    "phone_vibrate": (sfx_phone_vibrate, 1.2, "手机震动（预留）"),
}


# ---------------------------------------------------------------------------
# BGM 合成：低频 drone 为主，可循环、无爆音
# ---------------------------------------------------------------------------

def bgm_tension(rng, dur):
    fade = 1.0
    total = dur + fade
    out = [0.0] * int(total * SR)
    for f, a, lf, ph in (
        (36.71, 0.20, 0.043, 0.0), (36.95, 0.14, 0.061, 1.7),
        (73.42, 0.09, 0.037, 3.1), (110.00, 0.05, 0.053, 0.8),
        (87.31, 0.035, 0.071, 4.2), (146.83, 0.02, 0.029, 2.4),
    ):
        add_sine(out, 0.0, total, f, a,
                 env=lambda u, lf=lf, ph=ph: 0.72 + 0.28 * math.sin(2 * math.pi * lf * u + ph))
    t = 0.0
    while t < total - 1.2:
        add_sine(out, t, 1.2, 43.0, 0.05,
                 env=lambda u: math.exp(-u / 0.22) * min(1.0, u / 0.015))
        t += 4.2
    add_noise(out, 0.0, total, rng, 0.02,
              filters=[("bp", 1400.0, 0.6)],
              env=lambda u: 0.35 + 0.65 * math.sin(2 * math.pi * 0.05 * u) ** 2)
    add_sine(out, 0.0, total, 587.33, 0.006,
             env=lambda u: 0.5 + 0.5 * math.sin(2 * math.pi * 0.13 * u))
    return loopify(out, fade), {"rms_db": -19.0, "ceiling_db": -6.0}


def bgm_ending_a(rng, dur):
    fade = 1.0
    total = dur + fade
    out = [0.0] * int(total * SR)
    for f, a, lf, ph in (
        (55.00, 0.16, 0.031, 0.0), (82.41, 0.08, 0.047, 1.3),
        (110.00, 0.05, 0.039, 2.5), (130.81, 0.03, 0.057, 4.0),
        (220.00, 0.025, 0.023, 0.9), (261.63, 0.018, 0.041, 3.4),
        (329.63, 0.014, 0.033, 5.1),
    ):
        add_sine(out, 0.0, total, f, a,
                 env=lambda u, lf=lf, ph=ph: 0.7 + 0.3 * math.sin(2 * math.pi * lf * u + ph))
    # 稀疏钟音
    for k, f in enumerate((440.0, 659.25, 523.25, 329.63, 440.0, 659.25)):
        t = 2.0 + k * 5.4
        if t > total - 1.0:
            break
        add_sine(out, t, min(4.5, total - t), f, 0.03,
                 env=lambda u: math.exp(-u / 1.4) * min(1.0, u / 0.01))
    # 结尾向大调解决靠拢
    add_sine(out, max(0.0, total - 10.0), 10.0, 277.18, 0.022,
             env=lambda u: smoothstep(u / 6.0) * smoothstep((10.0 - u) / 3.0))
    add_noise(out, 0.0, total, rng, 0.012,
              filters=[("bp", 1200.0, 0.5)],
              env=lambda u: 0.4 + 0.6 * math.sin(2 * math.pi * 0.037 * u) ** 2)
    return loopify(out, fade), {"rms_db": -19.0, "ceiling_db": -6.0}


def bgm_ending_b(rng, dur):
    fade = 1.2
    total = dur + fade
    out = [0.0] * int(total * SR)
    for f, a, lf, ph in (
        (36.71, 0.18, 0.029, 0.0), (51.91, 0.10, 0.041, 1.1),
        (73.42, 0.06, 0.033, 2.7), (103.83, 0.04, 0.047, 4.4),
        (146.83, 0.02, 0.021, 0.6), (207.65, 0.012, 0.037, 3.2),
    ):
        add_sine(out, 0.0, total, f, a,
                 env=lambda u, lf=lf, ph=ph: 0.65 + 0.35 * math.sin(2 * math.pi * lf * u + ph))
    # 空洞高频气声
    add_noise(out, 0.0, total, rng, 0.016,
              filters=[("bp", 2400.0, 0.6)],
              env=lambda u: 0.3 + 0.7 * math.sin(2 * math.pi * 0.031 * u + 1.2) ** 2)
    # 稀疏下行音，无解决
    for k, f in enumerate((146.83, 207.65, 138.59, 103.83)):
        t = 3.0 + k * 7.0
        if t > total - 1.0:
            break
        add_sine(out, t, min(5.0, total - t), f, 0.022,
                 env=lambda u: math.exp(-u / 1.8) * min(1.0, u / 0.02))
    add_sine(out, 0.0, total, 1200.0, 0.003,
             env=lambda u: 0.5 + 0.5 * math.sin(2 * math.pi * 0.019 * u))
    return loopify(out, fade), {"rms_db": -19.0, "ceiling_db": -6.0}


BGM_BUILDERS = {
    "tension": (bgm_tension, 32.0, "低频 drone，D 小调，缓慢脉动"),
    "ending_a": (bgm_ending_a, 36.0, "结局 A 收束，A 小调向大调靠拢"),
    "ending_b": (bgm_ending_b, 36.0, "结局 B 空洞，三全音 drone"),
}


# ---------------------------------------------------------------------------
# 加载 / 校验设计
# ---------------------------------------------------------------------------

def load_sources():
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    story = json.loads(STORY_PATH.read_text(encoding="utf-8"))
    story_nodes = {n["node_id"]: n for n in story["nodes"]}
    design_nodes = design["nodes"]

    errors = []
    if design.get("chapter_id") != story.get("chapter_id"):
        errors.append("chapter_id 不一致")
    if abs(float(design.get("target_lufs", 0)) - TARGET_LUFS) > 1e-6:
        errors.append("设计 target_lufs 与脚本 -16 不一致")

    for node in design_nodes:
        nid = node["node_id"]
        if nid not in story_nodes:
            errors.append(f"{nid}: storyboard 缺失")
            continue
        if node.get("voice") not in design.get("voices", {}):
            errors.append(f"{nid}: voice {node.get('voice')} 未定义")
        line = node.get("line", "")
        if line != story_nodes[nid].get("dialogue", ""):
            errors.append(f"{nid}: design line 与 storyboard dialogue 不一致")
        if node.get("bgm") and node["bgm"] not in design.get("bgm", {}).get("beds", {}):
            errors.append(f"{nid}: bgm {node.get('bgm')} 未定义")
        for sfx in node.get("sfx", []):
            if sfx["id"] not in SFX_BUILDERS:
                errors.append(f"{nid}: sfx {sfx['id']} 未实现")
    if errors:
        raise SystemExit("设计校验失败:\n  - " + "\n  - ".join(errors))
    return design, story, story_nodes


def resolve_selection(design, only_arg, allow_pending):
    all_ids = [n["node_id"] for n in design["nodes"]]

    def resolve(token):
        t = token.strip()
        if not t:
            return None
        if t in all_ids:
            return t
        low = t.lower()
        cands = [i for i in all_ids
                 if i.lower() == low
                 or i.lower().endswith("_" + low)
                 or low in i.lower()
                 or i.split("_")[1].lower() == low
                 or i.split("_")[1].lower() == ("s" + low.zfill(2))]
        cands = list(dict.fromkeys(cands))
        if len(cands) == 1:
            return cands[0]
        raise SystemExit(f"--only 无法唯一解析节点: {token}（候选: {cands or '无'}）")

    if only_arg:
        selected = []
        for token in only_arg.split(","):
            nid = resolve(token)
            if nid and nid not in selected:
                selected.append(nid)
    else:
        selected = [i for i in all_ids if i not in PENDING_RESHOOT]

    pending = [i for i in selected if i in PENDING_RESHOOT]
    if pending and not allow_pending:
        raise SystemExit(
            "拒绝处理正在重拍的节点: %s\n"
            "重拍完成后再跑，或显式加 --allow-pending:\n"
            "  python3 scripts/build_audio_chapter_01.py --only s01,s07,s08 --allow-pending"
            % ", ".join(pending)
        )
    return selected


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

def tts_paths(nid: str) -> tuple[Path, Path]:
    return TTS_DIR / f"{nid}.wav", TTS_DIR / f"{nid}.json"


def tts_cache_valid(nid, design, design_mtime, story_mtime, force=False) -> dict | None:
    if force:
        return None
    wav, meta_path = tts_paths(nid)
    if not wav.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if meta.get("line") != design["line"]:
        return None
    if meta.get("voice") != design.get("say_voice"):
        return None
    if int(meta.get("rate", -1)) != int(design["rate"]):
        return None
    if int(meta.get("wav_size", -1)) != wav.stat().st_size:
        return None
    if wav.stat().st_size < 2000:
        return None
    if wav.stat().st_mtime + 1e-6 < design_mtime or wav.stat().st_mtime + 1e-6 < story_mtime:
        return None
    if not meta.get("duration_sec"):
        return None
    return meta


def build_tts(nid, design, force=False):
    wav, meta_path = tts_paths(nid)
    voice = design["say_voice"]
    rate = int(design["rate"])
    line = design["line"]
    TTS_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tts_", dir=str(AUDIO_DIR)) as td:
        aiff = Path(td) / f"{nid}.aiff"
        tmpwav = Path(td) / f"{nid}.tmp.wav"
        p = run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), line], check=False)
        if p.returncode != 0:
            raise RuntimeError(f"say 失败 ({voice}): {(p.stderr or '')[-800:]}")
        if not aiff.exists() or aiff.stat().st_size < 1000:
            raise RuntimeError(f"say 未产出有效音频: {aiff}")
        ffmpeg([
            "-i", str(aiff),
            "-af", "highpass=f=70,acompressor=threshold=-24dB:ratio=3:attack=5:release=120:makeup=6,alimiter=limit=0.95:level=0",
            "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(tmpwav),
        ])
        maxv = measure_max_volume(tmpwav)
        if maxv < -60:
            raise RuntimeError(f"TTS 疑似静音: {nid} max_volume={maxv}")
        gain = -3.0 - maxv
        ffmpeg([
            "-i", str(tmpwav),
            "-af", f"volume={gain:.3f}dB,alimiter=limit=0.95:level=0",
            "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(wav),
        ])

    duration = probe_duration(wav)
    meta = {
        "node_id": nid,
        "line": line,
        "voice": voice,
        "rate": rate,
        "wav_size": wav.stat().st_size,
        "duration_sec": round(duration, 4),
        "peak_dbfs": -3.0,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def tts_plan(node, design, voices, design_mtime, story_mtime, force=False, dry=False):
    nid = node["node_id"]
    voice_key = node["voice"]
    vdef = voices[voice_key]
    entry = {
        "voice_key": voice_key,
        "say_voice": vdef["say_voice"],
        "rate": int(vdef["rate"]),
        "line": node["line"],
        "gain_db": float(node.get("tts_gain_db", 0.0)),
        "start_sec": float(node.get("start_sec", 0.0)),
        "path": str(tts_paths(nid)[0]),
        "status": "pending",
    }
    cached = tts_cache_valid(nid, {**node, **vdef}, design_mtime, story_mtime, force=force)
    if cached:
        entry.update({"status": "cached", "duration_sec": cached["duration_sec"]})
    elif dry:
        est = max(0.6, len(node["line"]) * 0.22)
        entry.update({"status": "to-build", "duration_sec": round(est, 2), "estimated": True})
    else:
        meta = build_tts(nid, {**node, **vdef}, force=force)
        entry.update({"status": "built", "duration_sec": meta["duration_sec"]})
    return entry


def fit_tts(entry, video_dur):
    """确保 TTS 不越过片尾：先轻微提速，再前移起点。"""
    start = entry["start_sec"]
    dur = entry.get("duration_sec", 0.0)
    tempo = 1.0
    avail = max(0.5, video_dur - start - 0.15)
    if dur > avail:
        tempo = min(1.35, dur / avail)
        new_dur = dur / tempo
        if start + new_dur > video_dur - 0.08:
            start = max(0.0, video_dur - new_dur - 0.08)
        if start + new_dur > video_dur:
            tempo = min(1.45, dur / max(0.4, video_dur - 0.08))
            start = 0.0
    entry["tempo"] = round(tempo, 6)
    entry["start_sec"] = round(start, 3)
    entry["fits"] = (start + dur / tempo) <= video_dur + 0.02
    return entry


# ---------------------------------------------------------------------------
# SFX / BGM 构建
# ---------------------------------------------------------------------------

def sfx_path(sid: str) -> Path:
    return SFX_DIR / f"{sid}.wav"


def build_sfx(sid: str, force=False) -> dict:
    builder, dur, desc = SFX_BUILDERS[sid]
    path = sfx_path(sid)
    meta_path = SFX_DIR / f"{sid}.json"
    script_mtime = Path(__file__).stat().st_mtime
    design_mtime = DESIGN_PATH.stat().st_mtime
    if (not force and path.exists() and path.stat().st_size > 2000
            and path.stat().st_mtime >= max(script_mtime, design_mtime) - 1e-6):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("duration_sec"):
                return meta
        except (OSError, json.JSONDecodeError):
            pass
    rng = random.Random(20261123 + sum(ord(c) for c in sid))
    samples, norm = builder(rng, dur)
    samples = apply_filters(samples, [("hp", 35.0, 0.7)])
    fade_edges(samples, 6 if dur > 2.0 else 3)
    samples = normalize(samples, **norm)
    write_wav(path, samples)
    meta = {
        "id": sid,
        "desc": desc,
        "duration_sec": round(len(samples) / SR, 4),
        "target_sec": dur,
        "sample_rate": SR,
        "channels": 1,
        "normalize": norm,
        "size_bytes": path.stat().st_size,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def build_bgm(bid: str, force=False) -> dict:
    builder, dur, desc = BGM_BUILDERS[bid]
    path = BGM_DIR / f"{bid}.wav"
    meta_path = BGM_DIR / f"{bid}.json"
    script_mtime = Path(__file__).stat().st_mtime
    if (not force and path.exists() and path.stat().st_size > 20000
            and path.stat().st_mtime >= script_mtime - 1e-6):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("duration_sec"):
                return meta
        except (OSError, json.JSONDecodeError):
            pass
    rng = random.Random(77000 + sum(ord(c) for c in bid))
    samples, norm = builder(rng, dur)
    samples = apply_filters(samples, [("hp", 25.0, 0.7)])
    fade_edges(samples, 10)
    samples = normalize(samples, **norm)
    write_wav(path, samples)
    meta = {
        "id": bid,
        "desc": desc,
        "duration_sec": round(len(samples) / SR, 4),
        "sample_rate": SR,
        "channels": 1,
        "loop": True,
        "normalize": norm,
        "size_bytes": path.stat().st_size,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


# ---------------------------------------------------------------------------
# 混音
# ---------------------------------------------------------------------------

def bgm_fades(node_id: str, bgm_id: str, dur: float) -> tuple[float, float]:
    if bgm_id == "tension":
        fi = 1.5 if node_id.startswith("ch01_s01") else 0.3
        fo = 2.0 if node_id.startswith("ch01_s10") else 0.4
    elif bgm_id == "ending_a":
        fi, fo = 0.8, min(2.5, dur * 0.4)
    else:
        fi, fo = 1.0, min(3.0, dur * 0.4)
    fi = max(0.05, min(fi, dur * 0.5))
    fo = max(0.1, min(fo, dur * 0.5))
    return fi, fo


def build_mix_graph(dur: float, tts: dict, sfx_list, bgm: dict, has_orig: bool):
    parts = []
    if has_orig:
        parts.append(
            f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={ORIG_GAIN_DB}dB[orig]"
        )
    else:
        parts.append(
            f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=0:{dur:.3f}[orig]"
        )

    idx = 1
    tts_chain = (
        f"[{idx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,"
        f"volume={tts['gain_db']}dB"
    )
    if tts.get("tempo", 1.0) > 1.001:
        tts_chain += f",atempo={tts['tempo']:.6f}"
    delay_ms = int(round(tts["start_sec"] * 1000))
    if delay_ms > 0:
        tts_chain += f",adelay={delay_ms}:all=1"
    tts_chain += (
        f",apad,atrim=0:{dur:.3f},asetpts=N/SR/TB,"
        f"pan=stereo|c0=c0|c1=c0,asplit=2[ttsmix][ttskey]"
    )
    parts.append(tts_chain)

    sfx_labels = []
    si = 2
    for s in sfx_list:
        chain = (
            f"[{si}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,"
            f"volume={s['gain_db']}dB,atrim=0:{s['mix_dur']:.3f}"
        )
        ms = int(round(s["at_sec"] * 1000))
        if ms > 0:
            chain += f",adelay={ms}:all=1"
        chain += (
            f",apad,atrim=0:{dur:.3f},asetpts=N/SR/TB,"
            f"pan=stereo|c0=c0|c1=c0[s{si}]"
        )
        parts.append(chain)
        sfx_labels.append(f"[s{si}]")
        si += 1

    if len(sfx_labels) == 1:
        parts.append(f"{sfx_labels[0]}anull[sfxbus]")
    else:
        parts.append(
            "".join(sfx_labels)
            + f"amix=inputs={len(sfx_labels)}:duration=longest:dropout_transition=0:normalize=0[sfxbus]"
        )

    bi = si
    fi, fo = bgm["fade_in_sec"], bgm["fade_out_sec"]
    fo_start = max(0.0, dur - fo)
    parts.append(
        f"[{bi}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"atrim=0:{dur:.3f},asetpts=N/SR/TB,volume={bgm['gain_db']}dB,"
        f"afade=t=in:st=0:d={fi:.3f},afade=t=out:st={fo_start:.3f}:d={fo:.3f}[bgmraw]"
    )
    parts.append(f"[bgmraw][ttskey]{SIDECHAIN}[bgmduck]")
    parts.append(
        f"[orig][ttsmix][sfxbus][bgmduck]amix=inputs=4:duration=longest:"
        f"dropout_transition=0:normalize=0,"
        f"alimiter=limit=0.9:level=0,atrim=0:{dur:.3f},asetpts=N/SR/TB[mix]"
    )
    return ";".join(parts)


def loudnorm_two_pass(pre: Path, out: Path) -> dict:
    m = measure_loudness(pre)
    if not m or m["input_i"] < -70:
        ffmpeg([
            "-i", str(pre), "-af", f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA=11",
            "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le", str(out),
        ])
    else:
        af = (
            f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA=11:"
            f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
            f"offset={m['target_offset']}:linear=true,"
            f"alimiter=limit={LIMIT_LINEAR:.6f}:level=0"
        )
        ffmpeg([
            "-i", str(pre), "-af", af,
            "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le", str(out),
        ])

    # 末尾 ±0.3 LU 校正
    for _ in range(2):
        mm = measure_loudness(out)
        if not mm or mm["input_i"] < -70:
            break
        delta = TARGET_LUFS - mm["input_i"]
        if abs(delta) <= 0.3:
            break
        tmp = out.with_suffix(".corr.wav")
        ffmpeg([
            "-i", str(out),
            "-af", f"volume={delta:.3f}dB,alimiter=limit={LIMIT_LINEAR:.6f}:level=0",
            "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le", str(tmp),
        ])
        os.replace(tmp, out)
    return measure_loudness(out) or {}


def ensure_raw(node_id: str, video_path: Path, state: dict) -> Path:
    raw = RAW_DIR / f"{node_id}.mp4"
    if raw.exists():
        return raw
    rec = state.get("nodes", {}).get(node_id) or {}
    if rec.get("status") == "ok":
        raise RuntimeError(
            f"{node_id}: raw 备份丢失但成片已混音，拒绝把混音成片当作原始素材备份"
        )
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video_path, raw)
    log(f"  [backup] {video_path.name} -> raw/{raw.name}")
    return raw


# ---------------------------------------------------------------------------
# 校验 / QC
# ---------------------------------------------------------------------------

def mux_audio(raw: Path, mix: Path, out: Path) -> None:
    ffmpeg([
        "-i", str(raw), "-i", str(mix),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
        "-movflags", "+faststart", str(out),
    ])


def refine_loudness(video_path: Path, mix_path: Path) -> dict | None:
    """以成片 ebur128 为准，微调音轨后重封一次，确保落在 -16±0.35 LU。"""
    eb = measure_ebur128(video_path)
    for _ in range(2):
        if not eb:
            return None
        delta = TARGET_LUFS - eb["lufs"]
        if abs(delta) <= 0.35:
            return eb
        tmp = mix_path.with_suffix(".trim.wav")
        ffmpeg([
            "-i", str(mix_path),
            "-af", f"volume={delta:.3f}dB,alimiter=limit={LIMIT_LINEAR:.6f}:level=0",
            "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le", str(tmp),
        ])
        os.replace(tmp, mix_path)
        # 重新从 raw 回填，视频流仍为 copy
        raw_path = RAW_DIR / f"{video_path.stem}.mp4"
        if raw_path.exists():
            mux_audio(raw_path, mix_path, video_path)
        eb = measure_ebur128(video_path)
    return eb


def verify_output(node_id: str, raw: Path, out: Path, mix: Path) -> tuple[dict, list, dict]:
    errors = []
    raw_info = probe(raw)
    out_info = probe(out)
    rv = next((s for s in raw_info["streams"] if s["codec_type"] == "video"), None)
    ov = next((s for s in out_info["streams"] if s["codec_type"] == "video"), None)
    oa = next((s for s in out_info["streams"] if s["codec_type"] == "audio"), None)

    raw_dur = float(raw_info["format"]["duration"])
    out_dur = float(out_info["format"]["duration"])

    if not ov:
        errors.append("成片缺视频流")
    else:
        if ov.get("codec_name") != "h264":
            errors.append(f"视频编码 {ov.get('codec_name')} != h264")
        if ov.get("width") != 832 or ov.get("height") != 480:
            errors.append(f"分辨率 {ov.get('width')}x{ov.get('height')} != 832x480")
    if not oa:
        errors.append("成片缺音频流")
    else:
        if str(oa.get("sample_rate")) != "48000":
            errors.append(f"音频采样率 {oa.get('sample_rate')} != 48000")
        if int(oa.get("channels", 0)) != 2:
            errors.append(f"音频声道 {oa.get('channels')} != 2")
        if oa.get("codec_name") != "aac":
            errors.append(f"音频编码 {oa.get('codec_name')} != aac")
    if abs(out_dur - raw_dur) > 0.06:
        errors.append(f"时长变化 {raw_dur:.3f} -> {out_dur:.3f}")
    if rv and ov and rv.get("nb_frames") and ov.get("nb_frames") and rv["nb_frames"] != ov["nb_frames"]:
        errors.append(f"视频帧数变化 {rv['nb_frames']} -> {ov['nb_frames']}")

    md5_raw = video_md5(raw)
    md5_out = video_md5(out)
    if md5_raw != md5_out:
        errors.append("视频流 MD5 不一致（未做到 -c:v copy）")

    loud = measure_loudness(mix)
    eb = measure_ebur128(out)
    astats = astats_summary(out)
    lufs = eb["lufs"] if eb else (loud.get("input_i") if loud else None)
    if lufs is None or lufs < -70:
        errors.append("整片响度测量失败/静音")
    elif abs(lufs - TARGET_LUFS) > 2.0:
        errors.append(f"响度 {lufs:.2f} LUFS 偏离 -16 超过 ±2 LU")
    if astats.get("peak_db") is not None and astats["peak_db"] < -40:
        errors.append(f"音频峰值 {astats['peak_db']} dBFS 过低，疑似静音")

    metrics = {
        "raw_duration_sec": round(raw_dur, 3),
        "final_duration_sec": round(out_dur, 3),
        "video_codec": ov.get("codec_name") if ov else None,
        "width": ov.get("width") if ov else None,
        "height": ov.get("height") if ov else None,
        "video_frames": int(ov["nb_frames"]) if ov and ov.get("nb_frames") else None,
        "video_md5": md5_out,
        "video_md5_match": md5_raw == md5_out,
        "audio_codec": oa.get("codec_name") if oa else None,
        "audio_sample_rate": int(oa["sample_rate"]) if oa and oa.get("sample_rate") else None,
        "audio_channels": int(oa["channels"]) if oa and oa.get("channels") else None,
        "lufs": round(lufs, 2) if lufs is not None else None,
        "lufs_delta": round((lufs - TARGET_LUFS), 2) if lufs is not None else None,
        "ebur128_lufs": round(eb["lufs"], 2) if eb else None,
        "loudnorm_lufs": round(loud["input_i"], 2) if loud else None,
        "true_peak_db": round((eb["true_peak_db"] if eb and eb.get("true_peak_db") is not None
                               else loud["input_tp"]), 2) if (eb or loud) else None,
        "lra": round((eb["lra"] if eb and eb.get("lra") is not None
                      else loud["input_lra"]), 2) if (eb or loud) else None,
        "astats_rms_db": astats.get("rms_db"),
        "astats_peak_db": astats.get("peak_db"),
        "size_bytes": out.stat().st_size,
        "mix_size_bytes": mix.stat().st_size,
    }
    return metrics, errors, loud or {}


def make_qc(node_id: str, raw: Path, mix: Path, dur: float) -> Path:
    QC_DIR.mkdir(parents=True, exist_ok=True)
    t = max(0.0, min(dur * 0.55, dur - 0.5))
    frame = QC_DIR / f".{node_id}_frame.png"
    wave = QC_DIR / f".{node_id}_wave.png"
    out = QC_DIR / f"{node_id}_frame_wave.png"
    ffmpeg([
        "-ss", f"{t:.3f}", "-i", str(raw), "-frames:v", "1",
        "-vf", "scale=832:440:force_original_aspect_ratio=decrease,"
               "pad=832:440:(ow-iw)/2:(oh-ih)/2:color=0x0b0f0e",
        str(frame),
    ])
    ffmpeg([
        "-i", str(mix), "-filter_complex",
        "aformat=channel_layouts=mono,showwavespic=s=832x240:colors=0x7FA88C:scale=sqrt",
        "-frames:v", "1", str(wave),
    ])
    ffmpeg([
        "-i", str(frame), "-i", str(wave), "-filter_complex",
        "[0:v]format=rgb24[a];[1:v]format=rgb24[b];[a][b]vstack=inputs=2[out]",
        "-map", "[out]", "-frames:v", "1", str(out),
    ])
    frame.unlink(missing_ok=True)
    wave.unlink(missing_ok=True)
    return out


def make_contact_sheet(paths, out: Path):
    if not paths:
        return
    args = []
    for p in paths:
        args += ["-i", str(p)]
    n = len(paths)
    cols = 3
    filters = []
    for i in range(n):
        filters.append(
            f"[{i}:v]scale=416:340:force_original_aspect_ratio=decrease,"
            f"pad=416:340:(ow-iw)/2:(oh-ih)/2:color=0x0b0f0e,format=rgb24[v{i}]"
        )
    concat_in = "".join(f"[v{i}]" for i in range(n))
    filters.append(f"{concat_in}concat=n={n}:v=1:a=0,tile={cols}x{math.ceil(n / cols)}:margin=4:padding=4[out]")
    ffmpeg([*args, "-filter_complex", ";".join(filters), "-map", "[out]", "-frames:v", "1", str(out)])


# ---------------------------------------------------------------------------
# 时间轴打印 / 报告
# ---------------------------------------------------------------------------

def print_timeline(node, video_dur, tts, sfx_plan, bgm_plan, design):
    log("")
    log(f"■ {node['node_id']}  {video_dur:.2f}s  voice={node['voice']}  bgm={node.get('bgm')}")
    log("   时间轴:")
    ev = []
    for s in sfx_plan:
        ev.append((s["at_sec"], f"SFX  {s['id']:<18} {s['at_sec']:5.2f}-{s['at_sec'] + s['dur_sec']:5.2f}s  {s['gain_db']:+.1f}dB"))
    ev.append((tts["start_sec"],
               f"TTS  {tts['voice_key']:<18} {tts['start_sec']:5.2f}-{tts['start_sec'] + tts['duration_sec'] / tts.get('tempo', 1.0):5.2f}s  "
               f"{tts['gain_db']:+.1f}dB  {tts.get('status', '')}"))
    ev.append((0.0, f"BGM  {bgm_plan['id']:<18} 0.00-{video_dur:5.2f}s  {bgm_plan['gain_db']:+.1f}dB  "
                    f"fade {bgm_plan['fade_in_sec']:.2f}/{bgm_plan['fade_out_sec']:.2f}"))
    ev.append((0.0, f"原声  video audio       0.00-{video_dur:5.2f}s  {ORIG_GAIN_DB:+.1f}dB"))
    for _, line in sorted(ev, key=lambda x: x[0]):
        log("     " + line)
    if tts.get("tempo", 1.0) > 1.001:
        log(f"     ! TTS 提速 {tts['tempo']:.3f}x 以适配片长")
    log(f"   台词: {node['line']}")


def write_report(state: dict, design: dict, selected, pending):
    rows = []
    for node in design["nodes"]:
        nid = node["node_id"]
        rec = state.get("nodes", {}).get(nid, {})
        if nid in pending:
            rows.append(f"| `{nid}` | — | — | — | — | 待重拍，未处理 |")
            continue
        m = rec.get("metrics") or {}
        if not m:
            continue
        ok = "OK" if rec.get("status") == "ok" else "FAIL"
        rows.append(
            f"| `{nid}` | {m.get('final_duration_sec', 0):.2f}s | {m.get('lufs', 0):.2f} | "
            f"{m.get('lufs_delta', 0):+.2f} | {m.get('audio_sample_rate')}Hz/"
            f"{m.get('audio_channels')}ch {m.get('audio_codec')} | "
            f"{m.get('size_bytes', 0) / 1024 / 1024:.2f} MB | "
            f"{'copy' if m.get('video_md5_match') else 'MISMATCH'} | {ok} |"
        )

    tts_rows = []
    for nid in selected:
        rec = state.get("nodes", {}).get(nid, {})
        t = rec.get("tts") or {}
        tts_rows.append(
            f"| `{nid}` | {t.get('voice_key', '')} | {t.get('start_sec', 0):.2f}s | "
            f"{t.get('duration_sec', 0):.2f}s | {t.get('tempo', 1.0):.2f}x | {t.get('status', '')} |"
        )

    summary = state.get("summary", {})
    lines = [
        "# 第一章音频混音报告（T-017）",
        "",
        f"> 生成时间：{state.get('generated_at')}",
        f"> 设计：`story/04_audio/audio_design_chapter_01.json`；分镜：`story/03_storyboards/chapter_01.json`",
        f"> 目标响度：{TARGET_LUFS:+.1f} LUFS（True Peak {TRUE_PEAK:+.1f} dBTP）；成片 {summary.get('ok', 0)} OK / "
        f"{summary.get('failed', 0)} FAIL / {summary.get('skipped_pending', 0)} 待重拍",
        "",
        "## 1. 九条成片实测",
        "",
        "| 节点 | 时长 | LUFS(ebur128) | 偏差 | 音轨 | 大小 | 视频流 | 状态 |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "## 2. TTS 时间轴",
        "",
        "| 节点 | 音色 | 起点 | 时长 | 提速 | 状态 |",
        "|---|---|---|---|---|---|",
        *tts_rows,
        "",
        "## 3. 合成方案",
        "",
        "### TTS",
        "- `say -v \"<voice>\" -r <rate>` → AIFF → 48k 单声道 WAV；`highpass=70` + 压缩/限幅，峰值归一化到 -3 dBFS；",
        "- 逐字使用分镜 `dialogue`，脚本启动时校验 design `line` 与 storyboard 完全一致；",
        "- 缓存键：台词/音色/语速/源文件 mtime；`--force-tts` 强制重做。",
        "",
        "### SFX（21 个调色板 id，纯 stdlib 合成）",
        "- 噪声塑形（brown/white + RBJ biquad 低通/带通/峰值）、正弦/锯齿、指数包络、简易延迟混响；",
        "- 每个 id 的基片时长 >= 设计中最长引用时长，混音时按 `dur_sec` 裁剪；",
        "- 19 个设计 id：room_tone / corridor_drag / peephole_metal / carpet_drag / knock_three / keys_jingle /",
        "  door_open_creak / heartbeat / door_lock_click / footsteps_hall / elevator_hum / elevator_ding /",
        "  phone_notify / police_siren_far / knock_hard / radio_squelch / gurney_wheels / delete_confirm / light_switch；",
        "- 2 个预留 id：door_close_soft / phone_vibrate。",
        "",
        "### BGM（3 条，低频 drone 为主）",
        "- `tension` 32s：D1/D2 + 小三级 + 五度，慢速 LFO 与 4.2s 次低频脉冲；",
        "- `ending_a` 36s：A 小调 drone + 稀疏钟音，结尾叠入 C# 向大调靠拢；",
        "- `ending_b` 36s：D + Ab 三全音 drone、空洞高频气声，无解决；",
        "- 首尾 1.0–1.2s 交叉淡化实现无缝循环，边缘再 10ms 淡化防爆音。",
        "",
        "### 混音链",
        "- 原声 `-20 dB` 压低；TTS 单独声道并 `asplit` 出 sidechain key；",
        "- `sidechaincompress`（threshold 0.04 / ratio 6 / attack 15ms / release 420ms）对 BGM 闪避；",
        "- 4 路 `amix normalize=0` → 两遍 `loudnorm I=-16:TP=-1.5:LRA=11` → AAC 回填 → 成片 `ebur128` 闭环微调；",
        "- 输出 48k 立体声 PCM24 母版，AAC 192k 回填；`-map 0:v -map 1:a -c:v copy -shortest`；",
        "",
        "## 4. 校验",
        "",
        "- 视频流：h264 / 832×480 / 帧数与视频流 MD5 与 `raw/` 完全一致；",
        "- 音频流：aac / 48000 Hz / 2ch；成片时长与原始视频差 <= 0.06s；",
        "- 响度：`ffmpeg -af ebur128=peak=true` 测量整片，并以成片 ebur128 闭环微调；`loudnorm` 交叉复核，偏差在 ±2 LU 内；",
        "- 非静音：`astats` RMS/Peak 与 `qc/*_frame_wave.png` 抽帧+波形对照图；",
        "- `node player/selftest.mjs` 见交付说明。",
        "",
        "## 5. 待重拍节点",
        "",
        "`ch01_s01_voiceover` / `ch01_s07_elevator` / `ch01_s08_groupchat` 本次按边界不处理。",
        "重拍替换 `assets/videos/<node>.mp4` 后，用一条命令补跑：",
        "",
        "```bash",
        "python3 scripts/build_audio_chapter_01.py --only s01,s07,s08 --allow-pending",
        "```",
        "",
        "脚本会为这三条新建 `assets/videos/raw/<node>.mp4` 备份，再走同一套 TTS/混音/校验。",
        "",
        "## 6. 已知问题 / 说明",
        "",
        "- 设计文件实际引用 19 个唯一 SFX id（45 条引用），与任务描述里的「21 个调色板 id」差 2；",
        "  脚本补齐 `door_close_soft`、`phone_vibrate` 两个预留 id，21 个全部落盘。",
        "- BGM/SFX 为算法合成，听感以「可信、不抢台词」为目标，不是采样级拟真；建议真人试听后微调 `gain_db`。",
        "- `s08` 警笛段额外 -2 dB 的规则已写入 `bgm` 增益计算，待该条重拍后生效。",
        "- 混音不重编码视频流；播放器未做任何修改。",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="T-017 第一章 TTS/SFX/BGM 与混音")
    ap.add_argument("--only", help="逗号分隔节点（短名 s02 或完整 node_id）")
    ap.add_argument("--dry-run", action="store_true", help="只打印时间轴，不写文件")
    ap.add_argument("--skip-existing", action="store_true", help="状态为 ok 且产物齐全时跳过")
    ap.add_argument("--force-tts", action="store_true", help="强制重做 TTS")
    ap.add_argument("--force-sfx", action="store_true", help="强制重做 SFX")
    ap.add_argument("--force-bgm", action="store_true", help="强制重做 BGM")
    ap.add_argument("--force", action="store_true", help="强制重做 TTS/SFX/BGM")
    ap.add_argument("--allow-pending", action="store_true", help="允许处理 s01/s07/s08（重拍完成后）")
    ap.add_argument("--no-qc", action="store_true", help="不生成抽帧+波形图")
    ap.add_argument("--verify-only", action="store_true", help="只复测成片，不重混")
    args = ap.parse_args(argv)

    design, story, story_nodes = load_sources()
    selected = resolve_selection(design, args.only, args.allow_pending)
    design_mtime = DESIGN_PATH.stat().st_mtime
    story_mtime = STORY_PATH.stat().st_mtime
    script_mtime = Path(__file__).stat().st_mtime

    log(f"章节: {design['chapter_id']}  设计节点: {len(design['nodes'])}  本次处理: {len(selected)}")
    log("处理节点: " + ", ".join(selected))
    pending = [n["node_id"] for n in design["nodes"] if n["node_id"] in PENDING_RESHOOT]
    log("待重拍跳过: " + ", ".join(pending))

    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    state.setdefault("nodes", {})

    # ---- dry-run：只打印时间轴 ----
    if args.dry_run:
        for nid in selected:
            node = next(n for n in design["nodes"] if n["node_id"] == nid)
            video_path = ROOT / story_nodes[nid]["video"]["video_path"]
            video_dur = probe_duration(video_path) if video_path.exists() else 0.0
            tts = tts_plan(node, design, design["voices"], design_mtime, story_mtime,
                           force=args.force_tts or args.force, dry=True)
            tts = fit_tts(tts, video_dur)
            sfx_plan = []
            for s in node.get("sfx", []):
                spec = SFX_BUILDERS[s["id"]]
                sfx_plan.append({
                    "id": s["id"], "at_sec": float(s["at_sec"]),
                    "dur_sec": float(s["dur_sec"]),
                    "gain_db": float(s["gain_db"]),
                    "source_dur_sec": spec[1],
                })
            bed = design["bgm"]["beds"][node["bgm"]]
            gain = float(bed["gain_db"]) + (-2.0 if nid.startswith("ch01_s08") else 0.0)
            fi, fo = bgm_fades(nid, node["bgm"], video_dur)
            bgm_plan = {"id": node["bgm"], "gain_db": gain,
                        "fade_in_sec": round(fi, 2), "fade_out_sec": round(fo, 2)}
            print_timeline(node, video_dur, tts, sfx_plan, bgm_plan, design)
        return 0

    # ---- 构建素材 ----
    if not args.verify_only:
        log("\n[1/3] 生成 21 个 SFX 调色板 ...")
        for sid in SFX_ORDER:
            meta = build_sfx(sid, force=args.force or args.force_sfx)
            log(f"  sfx  {sid:<18} {meta['duration_sec']:5.2f}s  {meta['size_bytes'] / 1024:7.1f} KB")
        log("\n[2/3] 生成 3 条 BGM ...")
        for bid in BGM_BUILDERS:
            meta = build_bgm(bid, force=args.force or args.force_bgm)
            log(f"  bgm  {bid:<18} {meta['duration_sec']:5.2f}s  {meta['size_bytes'] / 1024:7.1f} KB")

    failures = []
    skipped_existing = 0
    processed_count = 0
    started = time.time()

    for ni, nid in enumerate(selected, 1):
        node = next(n for n in design["nodes"] if n["node_id"] == nid)
        log(f"\n[{ni}/{len(selected)}] {nid}")
        if args.skip_existing and not args.verify_only and not args.force:
            old = state["nodes"].get(nid)
            vp = ROOT / story_nodes[nid]["video"]["video_path"]
            if (old and old.get("status") == "ok"
                    and old.get("script_mtime") == round(script_mtime, 3)
                    and vp.exists()
                    and (RAW_DIR / f"{nid}.mp4").exists()
                    and (MIX_DIR / f"{nid}.wav").exists()):
                log("  [skip-existing] 状态 ok 且产物齐全，跳过")
                state["nodes"][nid] = old
                skipped_existing += 1
                continue
        processed_count += 1
        rec = {
            "node_id": nid,
            "voice": node["voice"],
            "line": node["line"],
            "status": "pending",
            "errors": [],
            "script_version": SCRIPT_VERSION,
        }
        try:
            video_path = ROOT / story_nodes[nid]["video"]["video_path"]
            if not video_path.exists():
                raise RuntimeError(f"成片缺失: {video_path}")

            if args.verify_only:
                raw = RAW_DIR / f"{nid}.mp4"
                mix = MIX_DIR / f"{nid}.wav"
                out = video_path
                if not raw.exists() or not mix.exists():
                    raise RuntimeError("verify-only 需要 raw 备份与混音母版")
                old = state["nodes"].get(nid, {})
                rec = {**old, "errors": []}
            else:
                raw = ensure_raw(nid, video_path, state)
                raw_dur = probe_duration(raw)
                if raw_dur <= 0.5:
                    raise RuntimeError(f"raw 时长异常: {raw_dur}")

                # TTS
                tts = tts_plan(node, design, design["voices"], design_mtime, story_mtime,
                               force=args.force_tts or args.force)
                tts = fit_tts(tts, raw_dur)
                if not tts.get("fits"):
                    rec["errors"].append("TTS 无法在片长内完整放下")
                log(f"  TTS {tts['status']:<7} {tts['duration_sec']:.2f}s "
                    f"start={tts['start_sec']:.2f}s tempo={tts['tempo']:.2f}x  {tts['say_voice']}")
                rec["tts"] = tts

                # SFX 计划
                sfx_list = []
                for s in node.get("sfx", []):
                    src = sfx_path(s["id"])
                    if not src.exists():
                        raise RuntimeError(f"SFX 缺失: {src}")
                    src_dur = probe_duration(src)
                    mix_dur = min(float(s["dur_sec"]), max(0.05, min(src_dur, raw_dur - float(s["at_sec"]))))
                    sfx_list.append({
                        "id": s["id"],
                        "at_sec": float(s["at_sec"]),
                        "dur_sec": float(s["dur_sec"]),
                        "mix_dur": mix_dur,
                        "gain_db": float(s["gain_db"]),
                        "source_dur_sec": round(src_dur, 3),
                        "status": "ok",
                        "path": str(src),
                    })
                rec["sfx"] = sfx_list

                # BGM 计划
                bed = design["bgm"]["beds"][node["bgm"]]
                gain = float(bed["gain_db"])
                if nid.startswith("ch01_s08"):
                    gain -= 2.0
                fi, fo = bgm_fades(nid, node["bgm"], raw_dur)
                bgm = {
                    "id": node["bgm"],
                    "path": str(BGM_DIR / f"{node['bgm']}.wav"),
                    "gain_db": gain,
                    "fade_in_sec": round(fi, 3),
                    "fade_out_sec": round(fo, 3),
                    "note": bed.get("note", ""),
                    "status": "ok",
                }
                rec["bgm"] = bgm
                log(f"  SFX {len(sfx_list)} 条 / BGM {bgm['id']} {gain:+.1f}dB")

                # 混音
                MIX_DIR.mkdir(parents=True, exist_ok=True)
                mix = MIX_DIR / f"{nid}.wav"
                with tempfile.TemporaryDirectory(prefix="mix_", dir=str(AUDIO_DIR)) as td:
                    pre = Path(td) / "pre.wav"
                    inputs = ["-i", str(raw), "-i", tts["path"]]
                    for s in sfx_list:
                        inputs += ["-i", s["path"]]
                    inputs += ["-i", bgm["path"]]
                    graph = build_mix_graph(raw_dur, tts, sfx_list, bgm, has_orig=True)
                    ffmpeg(inputs + [
                        "-filter_complex", graph, "-map", "[mix]",
                        "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le", str(pre),
                    ])
                    loud = loudnorm_two_pass(pre, mix)
                log(f"  混音 {raw_dur:.2f}s  LUFS={loud.get('input_i', 0):.2f}  "
                    f"TP={loud.get('input_tp', 0):.2f}dB")

                # 回填（视频流 copy）+ 以成片 ebur128 闭环微调
                mux_audio(raw, mix, video_path)
                eb_final = refine_loudness(video_path, mix)
                out = video_path
                log(f"  回填 {out.name}  {out.stat().st_size / 1024 / 1024:.2f} MB"
                    + (f"  ebur128={eb_final['lufs']:.2f} LUFS" if eb_final else ""))

            metrics, errs, loud = verify_output(nid, raw, out, mix)
            rec["metrics"] = metrics
            rec["errors"].extend(errs)
            rec["loudness"] = {
                "lufs": metrics.get("lufs"),
                "delta": metrics.get("lufs_delta"),
                "ebur128_lufs": metrics.get("ebur128_lufs"),
                "loudnorm_lufs": metrics.get("loudnorm_lufs"),
                "true_peak_db": metrics.get("true_peak_db"),
                "lra": metrics.get("lra"),
                "method": "ffmpeg ebur128 (final) / loudnorm (cross-check)",
            }
            rec["video"] = {
                "raw": str(raw),
                "output": str(out),
                "duration_sec": metrics["final_duration_sec"],
                "size_bytes": metrics["size_bytes"],
            }
            rec["script_mtime"] = round(script_mtime, 3)
            rec["built_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

            if errs:
                rec["status"] = "failed"
                failures.append((nid, errs))
                log("  校验失败: " + "; ".join(errs))
            else:
                rec["status"] = "ok"
                log(f"  校验通过  {metrics['width']}x{metrics['height']} {metrics['video_codec']} / "
                    f"{metrics['audio_sample_rate']}Hz {metrics['audio_channels']}ch / "
                    f"LUFS {metrics['lufs']:.2f} ({metrics['lufs_delta']:+.2f}) / "
                    f"video md5 {'match' if metrics['video_md5_match'] else 'MISMATCH'}")

            if not args.no_qc:
                try:
                    rec["qc_image"] = str(make_qc(nid, raw, mix, metrics["final_duration_sec"]))
                except Exception as exc:  # QC 失败不阻断交付
                    rec["qc_error"] = str(exc)[-1000:]
                    log(f"  [warn] QC 图失败: {exc}")

        except Exception as exc:
            rec["status"] = "failed"
            rec["errors"].append(str(exc)[-2000:])
            failures.append((nid, [str(exc)[-1000:]]))
            log(f"  [ERROR] {exc}")

        state["nodes"][nid] = rec

    # 待重拍节点留痕
    for nid in pending:
        if nid not in state["nodes"] or state["nodes"][nid].get("status") not in ("ok", "failed"):
            state["nodes"][nid] = {
                "node_id": nid,
                "status": "skipped_pending_reshoot",
                "reason": "正在重拍替换，按任务边界不处理",
            }

    # 汇总
    all_ids = [n["node_id"] for n in design["nodes"]]
    ok_n = sum(1 for i in all_ids if state["nodes"].get(i, {}).get("status") == "ok")
    failed_n = sum(1 for i in all_ids if state["nodes"].get(i, {}).get("status") == "failed")
    skipped_n = sum(1 for i in all_ids if state["nodes"].get(i, {}).get("status") == "skipped_pending_reshoot")
    total_size = sum(state["nodes"].get(i, {}).get("metrics", {}).get("size_bytes", 0)
                     for i in all_ids if state["nodes"].get(i, {}).get("status") == "ok")
    state.update({
        "chapter_id": design["chapter_id"],
        "task": "T-017",
        "script": str(Path(__file__).relative_to(ROOT)),
        "script_version": SCRIPT_VERSION,
        "script_mtime": round(script_mtime, 3),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target_lufs": TARGET_LUFS,
        "true_peak": TRUE_PEAK,
        "source_files": {
            "audio_design": str(DESIGN_PATH.relative_to(ROOT)),
            "storyboard": str(STORY_PATH.relative_to(ROOT)),
        },
        "pending_reshoot": list(pending),
        "summary": {
            "nodes_total": len(all_ids),
            "ok": ok_n,
            "failed": failed_n,
            "skipped_pending": skipped_n,
            "processed_this_run": processed_count,
            "skipped_existing": skipped_existing,
            "ok_size_bytes": total_size,
            "failures": [{"node_id": n, "errors": e} for n, e in failures],
            "elapsed_sec": round(time.time() - started, 1),
        },
    })
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(state, design, selected, pending)

    # 汇总 QC 拼图
    if not args.no_qc and not args.verify_only:
        qc_paths = [Path(state["nodes"][i]["qc_image"]) for i in all_ids
                    if state["nodes"].get(i, {}).get("qc_image")
                    and Path(state["nodes"][i]["qc_image"]).exists()]
        if qc_paths:
            try:
                make_contact_sheet(qc_paths, QC_DIR / "qc_waveforms_chapter_01.png")
                log(f"\nQC 拼图: assets/audio/qc/qc_waveforms_chapter_01.png")
            except Exception as exc:
                log(f"[warn] QC 拼图失败: {exc}")

    log("\n" + "=" * 70)
    log(f"完成: OK {ok_n} / FAIL {failed_n} / 待重拍 {skipped_n}")
    if failures:
        for nid, errs in failures:
            log(f"  FAIL {nid}: {'; '.join(errs)}")
    log(f"状态: {STATE_PATH.relative_to(ROOT)}")
    log(f"报告: {REPORT_PATH.relative_to(ROOT)}")
    log("=" * 70)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
