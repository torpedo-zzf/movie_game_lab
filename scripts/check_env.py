#!/usr/bin/env python3
"""互动影游脚手架环境自检（仅标准库）。

检查 Python、ffmpeg/ffprobe、node/npm、ComfyUI 可达性、MiniMax H3 节点注册与
imagegen CLI，并输出人类可读检查表、写入 state/env_report.json。

退出码：
  0  必需项全部通过（ComfyUI / imagegen 等缺失只记 WARN）
  1  必需项（Python / ffmpeg / ffprobe）未通过
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / "state" / "env_report.json"
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
H3_NODE = "ComfyCloudMiniMaxH3FirstLastFrameToVideoNode"
HTTP_TIMEOUT = 3.0

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
STATUS_LABEL = {PASS: "[通过]", WARN: "[警告]", FAIL: "[失败]"}

_VERSION_RE = re.compile(r"version\s+([^\s]+)", re.IGNORECASE)


@dataclass
class CheckResult:
    """单项检查结果。required 为 True 时失败会影响进程退出码。"""

    name: str
    status: str
    required: bool
    detail: str
    version: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _run(command: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str] | None:
    """执行命令；找不到可执行文件或超时返回 None。"""
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _parse_version(text: str) -> str:
    match = _VERSION_RE.search(text)
    if match:
        return match.group(1)
    return _first_line(text) or "未知"


def check_python() -> CheckResult:
    current = platform.python_version()
    ok = sys.version_info[:2] >= (3, 9)
    detail = f"Python {current}（要求 >=3.9）"
    return CheckResult("Python", PASS if ok else FAIL, True, detail, current)


def check_tool(name: str, *, required: bool, args: tuple[str, ...] = ("-version",)) -> CheckResult:
    path = shutil.which(name)
    if not path:
        return CheckResult(
            name,
            FAIL if required else WARN,
            required,
            "未在 PATH 中找到可执行文件",
        )

    proc = _run([path, *args])
    if proc is None:
        return CheckResult(name, FAIL if required else WARN, required, f"无法执行: {path}")

    output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    if proc.returncode != 0:
        return CheckResult(
            name,
            FAIL if required else WARN,
            required,
            f"命令返回码 {proc.returncode}: {_first_line(output) or path}",
        )

    version = _parse_version(output)
    detail = _first_line(output) or f"版本 {version}"
    return CheckResult(name, PASS, required, detail, version)


def _http_json(url: str, timeout: float = HTTP_TIMEOUT) -> tuple[dict | None, str | None]:
    """GET 一个 JSON 对象；失败时返回 (None, 原因)。"""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "movie-game-lab-check-env/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, dict):
            return None, "响应不是 JSON 对象"
        return data, None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        reason = getattr(exc, "reason", None) or str(exc) or exc.__class__.__name__
        return None, str(reason)


def check_comfyui(base_url: str) -> CheckResult:
    stats, error = _http_json(f"{base_url}/system_stats")
    if stats is None:
        return CheckResult(
            "ComfyUI",
            WARN,
            False,
            f"{base_url} 不可达（{error}）；可用 COMFYUI_URL 覆盖",
        )

    system = stats.get("system")
    version = ""
    if isinstance(system, dict):
        version = str(system.get("comfyui_version") or "")
    detail = f"{base_url} 可达" + (f"（ComfyUI {version}）" if version else "")
    return CheckResult("ComfyUI", PASS, False, detail, version or None)


def check_h3_node(base_url: str, comfyui: CheckResult) -> CheckResult:
    if comfyui.status != PASS:
        return CheckResult("MiniMax H3 节点", WARN, False, "ComfyUI 不可达，跳过节点检测")

    info, error = _http_json(f"{base_url}/object_info/{H3_NODE}")
    if info is None:
        return CheckResult(
            "MiniMax H3 节点",
            WARN,
            False,
            f"无法读取 /object_info（{error}）",
        )
    if H3_NODE in info:
        return CheckResult("MiniMax H3 节点", PASS, False, f"已注册 {H3_NODE}")
    return CheckResult(
        "MiniMax H3 节点",
        WARN,
        False,
        f"未找到 {H3_NODE}，请确认 ComfyUI 版本或自定义节点已安装",
    )


def check_imagegen() -> CheckResult:
    path = shutil.which("imagegen")
    if path:
        return CheckResult("imagegen CLI", PASS, False, f"已找到: {path}")
    return CheckResult(
        "imagegen CLI",
        WARN,
        False,
        "未在 PATH 中找到；可手动准备首尾帧后继续 ComfyUI 流程",
    )


def collect_checks() -> tuple[list[CheckResult], str]:
    base_url = (os.environ.get("COMFYUI_URL") or DEFAULT_COMFYUI_URL).rstrip("/")
    checks = [
        check_python(),
        check_tool("ffmpeg", required=True),
        check_tool("ffprobe", required=True),
        check_tool("node", required=False, args=("--version",)),
        check_tool("npm", required=False, args=("--version",)),
    ]
    comfyui = check_comfyui(base_url)
    checks.extend([comfyui, check_h3_node(base_url, comfyui), check_imagegen()])
    return checks, base_url


def build_report(checks: list[CheckResult], base_url: str, ok: bool) -> dict:
    warnings = sum(1 for item in checks if item.status == WARN)
    failures = sum(1 for item in checks if item.status == FAIL)
    required = [item for item in checks if item.required]
    passed_required = sum(1 for item in required if item.status == PASS)
    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ok": ok,
        "comfyui_url": base_url,
        "summary": {
            "checks_total": len(checks),
            "required_total": len(required),
            "required_passed": passed_required,
            "warnings": warnings,
            "failures": failures,
        },
        "checks": [item.as_dict() for item in checks],
    }


def write_report(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = REPORT_PATH.with_name(REPORT_PATH.name + ".tmp")
    tmp_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(REPORT_PATH)


def print_report(checks: list[CheckResult], base_url: str, ok: bool) -> None:
    print()
    print("互动影游脚手架 · 环境自检")
    print("=" * 72)
    print(f"ComfyUI 地址: {base_url}")
    print("-" * 72)
    for item in checks:
        requirement = "必需" if item.required else "可选"
        print(f"{STATUS_LABEL[item.status]} {item.name:<16} [{requirement}] {item.detail}")
    print("-" * 72)

    required = [item for item in checks if item.required]
    passed_required = sum(1 for item in required if item.status == PASS)
    warnings = [item for item in checks if item.status == WARN]
    failures = [item for item in checks if item.status == FAIL]
    print(
        f"必需项: {passed_required}/{len(required)} 通过；"
        f"警告: {len(warnings)} 项；失败: {len(failures)} 项"
    )
    if ok:
        print("[OK] 环境可用于剧本校验与媒体生产。")
    else:
        print("[FAIL] 必需项未通过，请先修复后再运行管线。")

    if any(item.name == "imagegen CLI" and item.status == WARN for item in checks):
        print("提示: 缺少 imagegen 时可手动准备首尾帧，再用 ComfyUI 首尾帧工作流继续。")
    if any(item.name == "ComfyUI" and item.status == WARN for item in checks):
        print("提示: ComfyUI 不可达不影响剧本校验；启动后重跑本脚本即可。")


def main() -> int:
    checks, base_url = collect_checks()
    required_failures = [item for item in checks if item.required and item.status != PASS]
    ok = not required_failures

    print_report(checks, base_url, ok)

    report = build_report(checks, base_url, ok)
    try:
        write_report(report)
        print(f"报告已写入: {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    except OSError as exc:
        print(f"[警告] 报告写入失败: {exc}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
