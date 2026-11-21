#!/usr/bin/env python3
"""调用本地 ComfyUI API 批量生成 MiniMax H3 分镜视频并回填 JSON。

成本确认闸门（硬规则）：
  1. 先扫描待生成节点，打印《视频成本预估单》；
  2. 未确认前绝不调用 ComfyUI /prompt：
       - --dry-run   只出预估单；
       - 交互终端   输入 CONFIRM 才继续；
       - --yes       代表已获得明确确认（供总控转述用户后使用）；
       - 非交互环境且未给 --yes 时直接拒绝。
  3. 确认后先把记录写入 state/task_board.json 的 approvals，再逐条排队；
     写入失败则拒绝提交。重跑或超出预估 10% 必须重新确认。

审批记录采用读-合并-原子替换，只增改 approvals 数组，不覆盖看板其他字段。
approvals 记录字段约定见 README.md。
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASK_BOARD_PATH = PROJECT_ROOT / "state" / "task_board.json"
COMFYUI_URL = (os.environ.get("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
H3_CLASS_MARKER = "MiniMaxH3"
DEFAULT_DURATION_SEC = 5.0
DEFAULT_RETRY_RATE = 0.2
HTTP_TIMEOUT_SEC = 60.0


@dataclass
class PendingNode:
    node_id: str
    duration_sec: float
    resolution: str
    prompt: str


@dataclass
class CostEstimate:
    items: list[PendingNode]
    cost_per_sec: float | None
    cost_unit: str
    retry_rate: float

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def total_duration(self) -> float:
        return sum(item.duration_sec for item in self.items)

    @property
    def resolution_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.resolution] = counts.get(item.resolution, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def resolution_summary(self) -> str:
        counts = self.resolution_counts
        if len(counts) == 1:
            return next(iter(counts))
        return "mixed"

    @property
    def base_cost(self) -> float | None:
        if self.cost_per_sec is None:
            return None
        return self.total_duration * self.cost_per_sec

    @property
    def retry_count(self) -> int:
        return math.ceil(self.count * self.retry_rate)

    @property
    def retry_duration(self) -> float:
        return self.total_duration * self.retry_rate

    @property
    def retry_cost(self) -> float | None:
        base = self.base_cost
        return None if base is None else base * self.retry_rate

    @property
    def total_cost_cap(self) -> float | None:
        base = self.base_cost
        if base is None:
            return None
        return base + (self.retry_cost or 0.0)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"需要数字: {value}") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return number


def _retry_rate(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"需要数字: {value}") from exc
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("重试预算比例必须在 0 到 1 之间")
    return number


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _asset_exists(value: str) -> bool:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.is_file()


def _workflow_defaults(workflow: dict) -> dict:
    """从 API 工作流的 H3 节点读取分辨率/时长默认值。"""
    if not isinstance(workflow, dict):
        return {}
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if H3_CLASS_MARKER not in str(node.get("class_type") or ""):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        defaults: dict = {}
        resolution = inputs.get("resolution")
        if isinstance(resolution, str) and resolution.strip():
            defaults["resolution"] = resolution.strip()
        duration = inputs.get("duration_seconds")
        if (
            isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and duration > 0
        ):
            defaults["duration_seconds"] = float(duration)
        return defaults
    return {}


def collect_pending(
    data: dict,
    workflow: dict,
    *,
    resolution_override: str | None,
    default_duration: float | None,
) -> tuple[list[PendingNode], list[str]]:
    """扫描需要生成的节点；已有可读 video_path 的节点跳过。"""
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("章节 JSON 缺少 nodes 数组")

    defaults = _workflow_defaults(workflow)
    fallback_resolution = defaults.get("resolution", "480p")
    fallback_duration = (
        default_duration
        if default_duration is not None
        else defaults.get("duration_seconds", DEFAULT_DURATION_SEC)
    )

    pending: list[PendingNode] = []
    skipped: list[str] = []

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("node_id")
        if not isinstance(node_id, str) or not node_id.strip():
            continue
        video = node.get("video")
        if not isinstance(video, dict):
            raise ValueError(f"节点 {node_id} 缺少 video 对象")

        video_path = video.get("video_path")
        if isinstance(video_path, str) and video_path.strip() and _asset_exists(video_path):
            skipped.append(node_id)
            continue

        prompt = video.get("video_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"节点 {node_id} 的 video.video_prompt 为空，无法提交生成")

        duration = video.get("duration_sec")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration <= 0
        ):
            duration = fallback_duration

        resolution = resolution_override
        if not resolution:
            node_resolution = video.get("resolution")
            if isinstance(node_resolution, str) and node_resolution.strip():
                resolution = node_resolution.strip()
            else:
                resolution = fallback_resolution

        pending.append(
            PendingNode(
                node_id=node_id,
                duration_sec=float(duration),
                resolution=resolution,
                prompt=prompt,
            )
        )

    return pending, skipped


def _format_cost(value: float | None, unit: str) -> str:
    if value is None:
        return "待核实"
    return f"{value:.2f} {unit}"


def print_estimate(
    estimate: CostEstimate,
    chapter_path: Path,
    workflow_path: Path,
    skipped: list[str],
) -> None:
    unit = estimate.cost_unit
    print()
    print("=" * 78)
    print("视频成本预估单（MiniMax H3）")
    print("=" * 78)
    print(f"章节文件: {chapter_path}")
    print(f"工作流:   {workflow_path}")
    skipped_note = f"；已跳过 {len(skipped)} 个已有视频" if skipped else ""
    print(f"待生成节点: {estimate.count} 个{skipped_note}")
    print("-" * 78)
    print("节点清单:")
    for index, item in enumerate(estimate.items, start=1):
        node_cost = (
            None
            if estimate.cost_per_sec is None
            else item.duration_sec * estimate.cost_per_sec
        )
        print(
            f"  {index:>2}. {item.node_id:<30} "
            f"{item.duration_sec:>4.1f}s  {item.resolution:<5}  "
            f"{_format_cost(node_cost, unit)}"
        )
    print("-" * 78)

    durations = sorted({round(item.duration_sec, 2) for item in estimate.items})
    duration_text = ", ".join(f"{duration:g}s" for duration in durations)
    print(f"单条时长: {duration_text}")
    resolutions = ", ".join(
        f"{resolution} × {count}"
        for resolution, count in estimate.resolution_counts.items()
    )
    print(f"分辨率分布: {resolutions}")
    print(f"总条数: {estimate.count} 条")
    print(f"总时长: {estimate.total_duration:.1f} 秒")

    if estimate.cost_per_sec is None:
        print("计费口径: 待核实（未传 --cost-per-sec；请按 Comfy Cloud 控制台实际单价填写）")
        print("预计总成本: 待核实（仅已知基础用量，不编造单价）")
    else:
        print(f"计费口径: {estimate.cost_per_sec:.2f} {unit}/秒")
        print(f"基础预估: {_format_cost(estimate.base_cost, unit)}")

    retry_detail = (
        f"最多 +{estimate.retry_count} 条 / +{estimate.retry_duration:.1f} 秒"
    )
    if estimate.retry_cost is not None:
        retry_detail += f" / +{_format_cost(estimate.retry_cost, unit)}"
    print(f"失败重试预算: {estimate.retry_rate * 100:.0f}%（{retry_detail}）")
    print(f"预计总成本上限: {_format_cost(estimate.total_cost_cap, unit)}")
    print("-" * 78)
    print("说明: 任何重跑、补片、换分辨率，或实际用量超出基础预估 10%，都必须重新确认。")
    print("=" * 78)


def _request_confirmation(args: argparse.Namespace) -> tuple[bool, str, str]:
    if args.yes:
        return True, "cli:--yes", "确认生成（--yes）"
    if not sys.stdin.isatty():
        print("[REFUSED] 当前不是交互终端，且未提供 --yes；默认只出预估单，未提交。")
        print("          请在终端输入 CONFIRM，或在总控/用户明确确认后使用 --yes。")
        return False, "", ""
    try:
        answer = input("确认上述成本后请输入 CONFIRM 继续（其他任意输入取消）: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[REFUSED] 未获得确认，已取消。")
        return False, "", ""
    if answer != "CONFIRM":
        print("[REFUSED] 未获得 CONFIRM 确认，已取消。")
        return False, "", ""
    return True, "interactive:CONFIRM", "确认生成（CONFIRM）"


def _read_task_board() -> dict:
    if not TASK_BOARD_PATH.exists():
        return {}
    try:
        board = _load_json(TASK_BOARD_PATH)
    except json.JSONDecodeError as exc:
        raise ValueError(f"state/task_board.json 不是合法 JSON: {exc}") from exc
    if not isinstance(board, dict):
        raise ValueError("state/task_board.json 顶层必须是对象")
    return board


def _write_task_board(board: dict) -> None:
    TASK_BOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = TASK_BOARD_PATH.with_name(TASK_BOARD_PATH.name + ".tmp")
    tmp_path.write_text(
        json.dumps(board, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(TASK_BOARD_PATH)


def _upsert_approval(record: dict) -> None:
    """按 approval_id 增改记录；保留看板其他字段。"""
    board = _read_task_board()
    approvals = board.get("approvals", [])
    if approvals is None:
        approvals = []
    if not isinstance(approvals, list):
        raise ValueError("state/task_board.json 的 approvals 必须是数组")
    approvals = [
        item
        for item in approvals
        if not (
            isinstance(item, dict)
            and item.get("approval_id") == record.get("approval_id")
        )
    ]
    approvals.append(record)
    board["approvals"] = approvals
    _write_task_board(board)


def _build_approval(
    estimate: CostEstimate,
    args: argparse.Namespace,
    chapter_path: Path,
    workflow_path: Path,
    confirmed_by: str,
    user_reply: str,
) -> dict:
    approval_id = args.approval_id or (
        "APR-"
        + datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        + "-"
        + uuid.uuid4().hex[:6]
    )
    estimated = {
        "resolution": estimate.resolution_summary,
        "resolutions": estimate.resolution_counts,
        "nodes": estimate.count,
        "node_ids": [item.node_id for item in estimate.items],
        "total_duration_sec": round(estimate.total_duration, 2),
        "unit_price": (
            estimate.cost_per_sec
            if estimate.cost_per_sec is not None
            else "待核实"
        ),
        "cost_unit": estimate.cost_unit,
        "estimated_cost": (
            round(estimate.base_cost, 2)
            if estimate.base_cost is not None
            else "待核实"
        ),
        "retry_budget": estimate.retry_count,
        "retry_budget_sec": round(estimate.retry_duration, 2),
        "retry_budget_cost": (
            round(estimate.retry_cost, 2)
            if estimate.retry_cost is not None
            else "待核实"
        ),
        "total_cost_cap": (
            round(estimate.total_cost_cap, 2)
            if estimate.total_cost_cap is not None
            else "待核实"
        ),
    }
    now = _now()
    return {
        "approval_id": approval_id,
        "task_id": args.task_id,
        "stage": "批量生视频",
        "kind": "minimax_h3_video_batch",
        "status": "submitting",
        "requested_at": now,
        "confirmed_at": now,
        "confirmed_by": confirmed_by,
        "user_reply": user_reply,
        "chapter_file": str(chapter_path),
        "workflow_file": str(workflow_path),
        "estimated": estimated,
        "submitted": {"nodes": 0, "total_duration_sec": 0.0, "cost": 0.0},
        "actual": {"nodes": 0, "total_duration_sec": 0.0, "cost": 0.0},
        "failed_nodes": [],
    }


def _prepare_workflow(template: dict, item: PendingNode) -> dict:
    """深拷贝模板并注入 prompt / resolution / duration_seconds。"""
    workflow = copy.deepcopy(template)

    h3_ids = [
        node_id
        for node_id, node in workflow.items()
        if isinstance(node, dict)
        and H3_CLASS_MARKER in str(node.get("class_type") or "")
    ]
    target_ids = h3_ids or list(workflow.keys())

    injected = False
    for node_id in target_ids:
        node = workflow.get(node_id)
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if not isinstance(inputs.get("prompt"), str):
            continue
        inputs["prompt"] = item.prompt
        if isinstance(inputs.get("resolution"), str):
            inputs["resolution"] = item.resolution
        if isinstance(inputs.get("duration_seconds"), (int, float)) and not isinstance(
            inputs.get("duration_seconds"), bool
        ):
            inputs["duration_seconds"] = int(round(item.duration_sec))
        injected = True

    if not injected:
        raise ValueError("工作流中未找到可注入 prompt 的节点，请检查 API 格式导出")
    return workflow


def _request_json(
    url: str,
    *,
    payload: dict | None = None,
    timeout: float = HTTP_TIMEOUT_SEC,
) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 {url}: {exc.reason}") from exc
    result = json.loads(body)
    if not isinstance(result, dict):
        raise RuntimeError(f"{url} 返回的不是 JSON 对象")
    return result


def queue_prompt(workflow: dict) -> str:
    payload = _request_json(
        f"{COMFYUI_URL}/prompt",
        payload={"prompt": workflow},
    )
    prompt_id = payload.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id:
        raise RuntimeError(f"/prompt 未返回 prompt_id: {payload}")
    return prompt_id


def wait_for_completion(prompt_id: str, poll_interval: float = 3.0) -> dict:
    while True:
        history = _request_json(f"{COMFYUI_URL}/history/{prompt_id}")
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(poll_interval)


def _finish_approval(
    record: dict,
    status: str,
    submitted: dict,
    actual: dict,
    failed_nodes: list[str],
    error: str | None = None,
) -> None:
    record["status"] = status
    record["submitted"] = submitted
    record["actual"] = actual
    record["failed_nodes"] = failed_nodes
    record["finished_at"] = _now()
    if error:
        record["error"] = error
    try:
        _upsert_approval(record)
    except (OSError, ValueError) as exc:
        print(f"[警告] 审批记录更新失败: {exc}")


def run_batch(
    chapter_path: Path,
    workflow_path: Path,
    args: argparse.Namespace,
) -> int:
    try:
        data = _load_json(chapter_path)
        template = _load_json(workflow_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[ERROR] 无法读取输入文件: {exc}")
        return 1
    if not isinstance(data, dict):
        print("[ERROR] 章节 JSON 顶层必须是对象")
        return 1
    if not isinstance(template, dict):
        print("[ERROR] 工作流 JSON 顶层必须是对象")
        return 1

    try:
        pending, skipped = collect_pending(
            data,
            template,
            resolution_override=args.resolution,
            default_duration=args.default_duration,
        )
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 1

    if not pending:
        print("[SKIP] 没有待生成节点：所有节点都已有可读 video_path。")
        return 0

    estimate = CostEstimate(
        items=pending,
        cost_per_sec=args.cost_per_sec,
        cost_unit=args.cost_unit,
        retry_rate=args.retry_rate,
    )
    print_estimate(estimate, chapter_path, workflow_path, skipped)

    if args.dry_run:
        print("\n[DRY-RUN] 仅输出预估单，未调用 ComfyUI /prompt，也未写入审批记录。")
        return 0

    confirmed, confirmed_by, user_reply = _request_confirmation(args)
    if not confirmed:
        return 2

    record = _build_approval(
        estimate,
        args,
        chapter_path,
        workflow_path,
        confirmed_by,
        user_reply,
    )
    try:
        _upsert_approval(record)
    except (OSError, ValueError) as exc:
        print(f"[REFUSED] 无法写入审批记录到 {TASK_BOARD_PATH}: {exc}")
        print("          未提交任何视频任务。")
        return 2
    print(
        f"[APPROVAL] 已记录 {record['approval_id']}；"
        f"确认方式: {confirmed_by}；开始提交 {estimate.count} 条。"
    )

    node_map = {
        node.get("node_id"): node
        for node in data.get("nodes", [])
        if isinstance(node, dict)
    }
    submitted_count = 0
    submitted_duration = 0.0
    failed_nodes: list[str] = []

    try:
        for index, item in enumerate(pending, start=1):
            print(f"[QUEUE {index}/{estimate.count}] {item.node_id} ...")
            workflow = _prepare_workflow(template, item)
            prompt_id = queue_prompt(workflow)
            wait_for_completion(prompt_id, args.poll_interval)
            print(f"[DONE] {item.node_id} 完成 (prompt_id={prompt_id})")

            node = node_map.get(item.node_id)
            if isinstance(node, dict):
                video = node.get("video")
                if not isinstance(video, dict):
                    video = {}
                    node["video"] = video
                video["video_path"] = f"assets/videos/{item.node_id}.mp4"

            submitted_count += 1
            submitted_duration += item.duration_sec
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        failed_nodes = [
            item.node_id for item in pending[submitted_count:]
        ]
        status = "partial" if submitted_count else "failed"
        actual_cost: float | str
        if estimate.cost_per_sec is None:
            actual_cost = "待核实"
        else:
            actual_cost = round(submitted_duration * estimate.cost_per_sec, 2)
        _finish_approval(
            record,
            status,
            {
                "nodes": submitted_count,
                "total_duration_sec": round(submitted_duration, 2),
                "cost": actual_cost,
            },
            {
                "nodes": submitted_count,
                "total_duration_sec": round(submitted_duration, 2),
                "cost": actual_cost,
            },
            failed_nodes,
            error=str(exc),
        )
        print(f"[ERROR] 批量提交中断: {exc}")
        print("[提示] 重跑前必须重新走成本确认闸门。")
        return 1

    actual_cost = (
        "待核实"
        if estimate.cost_per_sec is None
        else round(submitted_duration * estimate.cost_per_sec, 2)
    )
    submitted = {
        "nodes": submitted_count,
        "total_duration_sec": round(submitted_duration, 2),
        "cost": actual_cost,
    }

    try:
        chapter_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        _finish_approval(
            record,
            "partial",
            submitted,
            submitted,
            [],
            error=f"视频已提交，但章节 JSON 写回失败: {exc}",
        )
        print(f"[ERROR] 视频已提交，但章节 JSON 写回失败: {exc}")
        return 1

    _finish_approval(record, "completed", submitted, submitted, [])
    print(f"[ALL DONE] 已提交 {submitted_count} 条；章节 JSON 已回填 video_path。")
    print("[注意] 脚本只写路径，不下载/搬运视频；请确认文件已归档到 assets/videos/。")
    print(f"[APPROVAL] 用量已记录到 {TASK_BOARD_PATH}（approvals）。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MiniMax H3 批量生视频（带成本确认闸门，默认拒绝未确认提交）。",
    )
    parser.add_argument("chapter_json", help="章节剧情图 JSON")
    parser.add_argument("workflow_json", help="ComfyUI 导出的 API 格式工作流 JSON")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印《视频成本预估单》，不提交、不写审批记录",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="已获得总控/用户明确确认，跳过 CONFIRM 交互（仍会记录审批）",
    )
    parser.add_argument(
        "--cost-per-sec",
        type=_positive_float,
        default=None,
        help="每秒计费单价（积分/秒）；未知时不要传，预估单写“待核实”",
    )
    parser.add_argument(
        "--cost-unit",
        default="积分",
        help="成本单位（默认：积分）",
    )
    parser.add_argument(
        "--retry-rate",
        type=_retry_rate,
        default=DEFAULT_RETRY_RATE,
        help="失败重试预算比例（默认 0.2，即 20%%）",
    )
    parser.add_argument(
        "--resolution",
        choices=("480p", "720p"),
        default=None,
        help="覆盖所有待生成节点的分辨率；默认读取节点或工作流",
    )
    parser.add_argument(
        "--default-duration",
        type=_positive_float,
        default=None,
        help="节点缺少 duration_sec 时的兜底时长（秒）",
    )
    parser.add_argument(
        "--poll-interval",
        type=_positive_float,
        default=3.0,
        help="轮询 /history 的间隔秒数（默认 3）",
    )
    parser.add_argument(
        "--task-id",
        default=None,
        help="关联 state/task_board.json 的任务 id，如 T-014",
    )
    parser.add_argument(
        "--approval-id",
        default=None,
        help="自定义 approval_id（默认自动生成 APR-<时间>-<随机>）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_batch(
        Path(args.chapter_json),
        Path(args.workflow_json),
        args,
    )


if __name__ == "__main__":
    sys.exit(main())
