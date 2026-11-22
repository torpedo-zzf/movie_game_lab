#!/usr/bin/env python3
"""Minimal local configuration for the MiniMax H3 API.

The API key lives in `.env.local` at the project root (gitignored, chmod 600).
No third-party dependencies.

Usage:
    python3 scripts/minimax_config.py show
    python3 scripts/minimax_config.py set-key
    python3 scripts/minimax_config.py check
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env.local"
DEFAULT_BASE = "https://metaso.cn/api/minimax"


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def save_env(base: str, key: str) -> None:
    ENV_PATH.write_text(
        "# MiniMax H3 API (metaso proxy)\n"
        f"MINIMAX_BASE_URL={base}\n"
        f"MINIMAX_API_KEY={key}\n",
        encoding="utf-8",
    )
    os.chmod(ENV_PATH, 0o600)


def mask(key: str) -> str:
    if not key:
        return "(未配置)"
    if len(key) <= 10:
        return key[:2] + "***"
    return f"{key[:6]}…{key[-4:]}"


def request_balance(base: str, key: str) -> tuple[int, str]:
    url = base.rstrip("/") + "/v2/credits/balance"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return 0, f"network error: {exc}"


def cmd_show() -> int:
    env = parse_env(ENV_PATH)
    base = env.get("MINIMAX_BASE_URL", DEFAULT_BASE)
    key = env.get("MINIMAX_API_KEY", "")
    print(f"config file : {ENV_PATH}")
    print(f"base url    : {base}")
    print(f"api key     : {mask(key)}")
    print(f"file mode   : {oct(ENV_PATH.stat().st_mode & 0o777)}" if ENV_PATH.exists() else "file mode   : (missing)")
    return 0


def cmd_set_key() -> int:
    env = parse_env(ENV_PATH)
    base = env.get("MINIMAX_BASE_URL", DEFAULT_BASE)
    print(f"base url: {base}")
    key = getpass.getpass("MiniMax API key (输入不回显): ").strip()
    if not key:
        print("空 key，未写入。", file=sys.stderr)
        return 2
    save_env(base, key)
    print(f"已写入 {ENV_PATH}（chmod 600）；用 check 验证。")
    return 0


def cmd_check() -> int:
    env = parse_env(ENV_PATH)
    base = env.get("MINIMAX_BASE_URL", DEFAULT_BASE)
    key = env.get("MINIMAX_API_KEY", "")
    if not key:
        print(f"未配置 API key。先运行：python3 scripts/minimax_config.py set-key", file=sys.stderr)
        return 2
    status, body = request_balance(base, key)
    print(f"GET {base.rstrip('/')}/v2/credits/balance -> HTTP {status}")
    try:
        data = json.loads(body)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(body[:1000])
    return 0 if status == 200 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="MiniMax H3 local API key configuration")
    parser.add_argument("command", choices=["show", "set-key", "check"])
    args = parser.parse_args()
    if args.command == "show":
        return cmd_show()
    if args.command == "set-key":
        return cmd_set_key()
    return cmd_check()


if __name__ == "__main__":
    raise SystemExit(main())
