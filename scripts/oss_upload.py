#!/usr/bin/env python3
"""Upload a local image to Alibaba Cloud OSS and print a presigned URL.

Stdlib only. Reads OSS credentials from `.env.local` (see oss_config.py).
The bucket can stay private: the printed URL carries an OSS V1 signature and
is valid for `--ttl` seconds (default 7 days).

Usage:
    python3 scripts/oss_upload.py assets/frames/chapter_01/ch01_s01_voiceover_first.png
    python3 scripts/oss_upload.py <file> --prefix movie_game_lab/frames --ttl 86400 --check
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import formatdate
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env.local"


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


def host_of(endpoint: str) -> str:
    host = endpoint.strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def signature(secret: str, string_to_sign: str) -> str:
    digest = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def upload(env: dict[str, str], source: Path, key: str) -> dict:
    bucket = env["OSS_BUCKET"]
    host = host_of(env["OSS_ENDPOINT"])
    url = f"https://{bucket}.{host}/{urllib.parse.quote(key, safe='/')}"
    content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    data = source.read_bytes()
    date = formatdate(usegmt=True)
    sig = signature(env["OSS_ACCESS_KEY_SECRET"], f"PUT\n\n{content_type}\n{date}\n/{bucket}/{key}")
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Date": date,
        "Content-Type": content_type,
        "Authorization": f"OSS {env['OSS_ACCESS_KEY_ID']}:{sig}",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        etag = resp.headers.get("ETag", "")
        status = resp.status
    return {"url": url, "status": status, "etag": etag, "bytes": len(data), "content_type": content_type}


def presign(env: dict[str, str], key: str, ttl: int) -> str:
    bucket = env["OSS_BUCKET"]
    host = host_of(env["OSS_ENDPOINT"])
    expires = int(time.time()) + ttl
    sig = signature(env["OSS_ACCESS_KEY_SECRET"], f"GET\n\n\n{expires}\n/{bucket}/{key}")
    query = urllib.parse.urlencode({
        "OSSAccessKeyId": env["OSS_ACCESS_KEY_ID"],
        "Expires": expires,
        "Signature": sig,
    })
    return f"https://{bucket}.{host}/{urllib.parse.quote(key, safe='/')}?{query}"


def check_url(url: str) -> tuple[int, int]:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, int(resp.headers.get("Content-Length") or 0)
    except urllib.error.HTTPError as exc:
        return exc.code, 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload a file to Alibaba Cloud OSS")
    parser.add_argument("file", type=Path)
    parser.add_argument("--prefix", default="movie_game_lab/frames")
    parser.add_argument("--name", default=None, help="OSS object name; defaults to source filename")
    parser.add_argument("--ttl", type=int, default=7 * 24 * 3600)
    parser.add_argument("--check", action="store_true", help="HEAD the generated URL")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"文件不存在：{args.file}", file=sys.stderr)
        return 2
    env = parse_env(ENV_PATH)
    missing = [k for k in ["OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_BUCKET", "OSS_ENDPOINT"] if not env.get(k)]
    if missing:
        print(f"OSS 未配置：{', '.join(missing)}；先运行 python3 scripts/oss_config.py set", file=sys.stderr)
        return 2

    key = f"{args.prefix.strip('/')}/{args.name or args.file.name}"
    try:
        result = upload(env, args.file, key)
    except urllib.error.HTTPError as exc:
        print(f"上传失败 HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"网络错误：{exc}", file=sys.stderr)
        return 1

    url = presign(env, key, args.ttl)
    result.update({"key": key, "presigned_url": url, "expires_in": args.ttl})
    if args.check:
        status, length = check_url(url)
        result["check_http"] = status
        result["check_bytes"] = length
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
