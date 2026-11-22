#!/usr/bin/env python3
"""Local Alibaba Cloud OSS configuration (stdlib only).

Stores OSS credentials in `.env.local` (gitignored, chmod 600), next to the
MiniMax key. Never prints the secret.

Usage:
    python3 scripts/oss_config.py show
    python3 scripts/oss_config.py set
    python3 scripts/oss_config.py check
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import os
import sys
import urllib.error
import urllib.request
from email.utils import formatdate
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env.local"
KEYS = ["OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_BUCKET", "OSS_ENDPOINT", "OSS_PUBLIC_BASE_URL", "OSS_DIR_PREFIX"]


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


def save_env(values: dict[str, str]) -> None:
    lines = ["# MiniMax H3 + Alibaba Cloud OSS local secrets"]
    for key in ["MINIMAX_BASE_URL", "MINIMAX_API_KEY", *KEYS]:
        if values.get(key):
            lines.append(f"{key}={values[key]}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(ENV_PATH, 0o600)


def mask(value: str) -> str:
    if not value:
        return "(未配置)"
    if len(value) <= 8:
        return value[:2] + "***"
    return f"{value[:4]}…{value[-4:]}"


def endpoint_host(endpoint: str) -> str:
    host = endpoint.strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def sign(method: str, secret: str, bucket: str, key: str, content_type: str, date: str, expires: int | None = None) -> str:
    if expires is not None:
        string_to_sign = f"{method}\n\n\n{expires}\n/{bucket}/{key}"
    else:
        string_to_sign = f"{method}\n\n{content_type}\n{date}\n/{bucket}/{key}"
    digest = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def cmd_show() -> int:
    env = parse_env(ENV_PATH)
    print(f"config file : {ENV_PATH}")
    print(f"access key  : {mask(env.get('OSS_ACCESS_KEY_ID', ''))}")
    print(f"secret      : {mask(env.get('OSS_ACCESS_KEY_SECRET', ''))}")
    print(f"bucket      : {env.get('OSS_BUCKET', '(未配置)')}")
    print(f"endpoint    : {env.get('OSS_ENDPOINT', '(未配置)')}")
    print(f"public base : {env.get('OSS_PUBLIC_BASE_URL', '(未配置，使用 bucket.endpoint)')}")
    print(f"dir prefix  : {env.get('OSS_DIR_PREFIX', '(未配置)')}")
    return 0


def cmd_set() -> int:
    env = parse_env(ENV_PATH)
    print("按提示录入；Secret 不回显。留空表示保留原值。")
    access_id = input(f"AccessKey ID [{mask(env.get('OSS_ACCESS_KEY_ID', ''))}]: ").strip()
    if access_id:
        env["OSS_ACCESS_KEY_ID"] = access_id
    secret = getpass.getpass("AccessKey Secret（不回显，留空保留）: ").strip()
    if secret:
        env["OSS_ACCESS_KEY_SECRET"] = secret
    bucket = input(f"Bucket 名称 [{env.get('OSS_BUCKET', '')}]: ").strip()
    if bucket:
        env["OSS_BUCKET"] = bucket
    endpoint = input(f"Endpoint，如 oss-cn-hangzhou.aliyuncs.com [{env.get('OSS_ENDPOINT', '')}]: ").strip()
    if endpoint:
        env["OSS_ENDPOINT"] = endpoint
    public_base = input(f"自定义域名/公网前缀（可留空）[{env.get('OSS_PUBLIC_BASE_URL', '')}]: ").strip()
    if public_base:
        env["OSS_PUBLIC_BASE_URL"] = public_base
    dir_prefix = input(f"OSS 目录前缀 [{env.get('OSS_DIR_PREFIX', 'movie_game_lab')}]: ").strip()
    env["OSS_DIR_PREFIX"] = dir_prefix or env.get("OSS_DIR_PREFIX") or "movie_game_lab"
    missing = [k for k in ["OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_BUCKET", "OSS_ENDPOINT"] if not env.get(k)]
    if missing:
        print(f"还缺：{', '.join(missing)}；未写入。", file=sys.stderr)
        return 2
    save_env(env)
    print(f"已写入 {ENV_PATH}（chmod 600）。运行 check 验证。")
    return 0


def cmd_check() -> int:
    env = parse_env(ENV_PATH)
    missing = [k for k in ["OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_BUCKET", "OSS_ENDPOINT"] if not env.get(k)]
    if missing:
        print(f"未配置：{', '.join(missing)}；先运行 set。", file=sys.stderr)
        return 2
    host = endpoint_host(env["OSS_ENDPOINT"])
    bucket = env["OSS_BUCKET"]
    url = f"https://{bucket}.{host}/"
    date = formatdate(usegmt=True)
    signature = sign("HEAD", env["OSS_ACCESS_KEY_SECRET"], bucket, "", "", date)
    req = urllib.request.Request(url, method="HEAD", headers={
        "Date": date,
        "Authorization": f"OSS {env['OSS_ACCESS_KEY_ID']}:{signature}",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"HEAD {url} -> HTTP {resp.status}；认证与 Bucket 可用。")
            return 0
    except urllib.error.HTTPError as exc:
        print(f"HEAD {url} -> HTTP {exc.code}；{exc.read().decode('utf-8', errors='replace')[:300]}")
        return 1
    except urllib.error.URLError as exc:
        print(f"网络错误：{exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Alibaba Cloud OSS local configuration")
    parser.add_argument("command", choices=["show", "set", "check"])
    args = parser.parse_args()
    return {"show": cmd_show, "set": cmd_set, "check": cmd_check}[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
