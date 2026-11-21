#!/usr/bin/env python3
"""校验互动影游章节剧情图。

检查内容：
  1. 顶层结构、节点字段、node_type、video 提示词；
  2. ending 节点不得有后续；非 ending 节点必须有 interaction；
  3. 所有 next 引用存在，option_id 在节点内唯一；
  4. 从 start_node 的连通性（不可达孤岛记 WARN）；
  5. 至少一个 ending，且每个可达节点都能到达某个 ending；
  6. 道具闭环：required_items 必须被可达节点的 grant_items 覆盖。

用法：
  python3 scripts/validate_graph.py <chapter.json>
  python3 scripts/validate_graph.py <chapter.json> --json
  python3 scripts/validate_graph.py <chapter.json> --strict

退出码：0 通过（WARN 默认不阻断）；1 存在 ERROR，或 --strict 下存在 WARN。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NODE_TYPES = (
    "video_play",
    "choice_branch",
    "item_discovery",
    "qte_event",
    "ending",
)


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    node_id: str | None = None

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "node_id": self.node_id}


@dataclass
class ValidationResult:
    source: str
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    node_count: int = 0
    ending_count: int = 0
    reachable_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_error(self, code: str, message: str, node_id: str | None = None) -> None:
        self.errors.append(Issue(code, message, node_id))

    def add_warning(self, code: str, message: str, node_id: str | None = None) -> None:
        self.warnings.append(Issue(code, message, node_id))

    def as_dict(self) -> dict:
        return {
            "file": self.source,
            "ok": self.ok,
            "node_count": self.node_count,
            "ending_count": self.ending_count,
            "reachable_count": self.reachable_count,
            "errors": [issue.as_dict() for issue in self.errors],
            "warnings": [issue.as_dict() for issue in self.warnings],
        }


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    """只返回合法的非空字符串；结构错误由字段校验单独报告。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if _is_nonempty_str(item)]


def _valid_options(node: dict) -> list[dict]:
    interaction = node.get("interaction")
    if not isinstance(interaction, dict):
        return []
    options = interaction.get("options")
    if not isinstance(options, list):
        return []
    return [option for option in options if isinstance(option, dict)]


def validate_graph(data: Any, source: str = "<memory>") -> ValidationResult:
    """校验已解析的剧情图对象，返回结构化结果。"""
    result = ValidationResult(source=source)

    if not isinstance(data, dict):
        result.add_error("E_TOP_LEVEL", "剧情图根节点必须是 JSON 对象")
        return result

    for key in ("chapter_id", "title", "start_node"):
        if not _is_nonempty_str(data.get(key)):
            result.add_error("E_FIELD", f"缺少或非法的顶层字段: {key}（需为非空字符串）")

    nodes_raw = data.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        result.add_error("E_NODES", "nodes 必须为非空数组")
        return result

    nodes: dict[str, dict] = {}
    for index, raw in enumerate(nodes_raw):
        if not isinstance(raw, dict):
            result.add_error("E_NODE_SHAPE", f"nodes[{index}] 必须是对象")
            continue
        node_id = raw.get("node_id")
        if not _is_nonempty_str(node_id):
            result.add_error("E_NODE_ID", f"nodes[{index}] 缺少有效的 node_id")
            continue
        if node_id in nodes:
            result.add_error("E_NODE_DUP", f"node_id 重复: {node_id}", node_id)
            continue
        nodes[node_id] = raw

    result.node_count = len(nodes)
    if not nodes:
        return result

    # ---- 节点字段结构 ----
    for node_id, node in nodes.items():
        node_type = node.get("node_type")
        if node_type not in NODE_TYPES:
            result.add_error(
                "E_NODE_TYPE",
                f"节点 {node_id} 的 node_type 非法: {node_type!r}",
                node_id,
            )

        video = node.get("video")
        if not isinstance(video, dict):
            result.add_error("E_VIDEO", f"节点 {node_id} 缺少 video 对象", node_id)
        else:
            for field_name in ("first_frame_prompt", "video_prompt"):
                if not _is_nonempty_str(video.get(field_name)):
                    result.add_error(
                        "E_VIDEO_PROMPT",
                        f"节点 {node_id} 的 video.{field_name} 不能为空",
                        node_id,
                    )

        interaction = node.get("interaction")
        if node_type == "ending":
            if isinstance(interaction, dict):
                has_next = _is_nonempty_str(interaction.get("default_next_node")) or bool(
                    _valid_options(node)
                )
                if has_next:
                    result.add_error(
                        "E_ENDING_HAS_NEXT",
                        f"ending 节点 {node_id} 不得配置后续节点",
                        node_id,
                    )
            continue

        if not isinstance(interaction, dict):
            result.add_error(
                "E_MISSING_INTERACTION",
                f"非 ending 节点 {node_id} 缺少 interaction",
                node_id,
            )
            continue

        if not _is_nonempty_str(interaction.get("default_next_node")):
            result.add_error(
                "E_DEFAULT_NEXT_MISSING",
                f"节点 {node_id} 缺少 default_next_node",
                node_id,
            )

        raw_options = interaction.get("options", [])
        if raw_options is None:
            raw_options = []
        if not isinstance(raw_options, list):
            result.add_error(
                "E_OPTIONS_TYPE",
                f"节点 {node_id} 的 options 必须是数组",
                node_id,
            )
            raw_options = []

        seen_option_ids: set[str] = set()
        for option_index, option in enumerate(raw_options):
            if not isinstance(option, dict):
                result.add_error(
                    "E_OPTION_SHAPE",
                    f"节点 {node_id} 的 options[{option_index}] 必须是对象",
                    node_id,
                )
                continue

            option_id = option.get("option_id")
            if not _is_nonempty_str(option_id):
                result.add_error(
                    "E_OPTION_ID",
                    f"节点 {node_id} 的 options[{option_index}] 缺少有效 option_id",
                    node_id,
                )
            elif option_id in seen_option_ids:
                result.add_error(
                    "E_OPTION_DUP",
                    f"节点 {node_id} 的 option_id 重复: {option_id}",
                    node_id,
                )
            else:
                seen_option_ids.add(option_id)

            if not _is_nonempty_str(option.get("label")):
                result.add_error(
                    "E_OPTION_LABEL",
                    f"节点 {node_id} 的选项 {option_id or option_index} 缺少 label",
                    node_id,
                )
            if not _is_nonempty_str(option.get("next_node")):
                result.add_error(
                    "E_OPTION_NEXT_MISSING",
                    f"节点 {node_id} 的选项 {option_id or option_index} 缺少 next_node",
                    node_id,
                )

            for field_name in ("required_items", "grant_items"):
                value = option.get(field_name)
                if value is not None and (
                    not isinstance(value, list)
                    or any(not _is_nonempty_str(item) for item in value)
                ):
                    result.add_error(
                        "E_ITEM_TYPE",
                        f"节点 {node_id} 的选项 {option_id or option_index} "
                        f"{field_name} 必须是非空字符串数组",
                        node_id,
                    )

    # ---- 引用完整性与有向边 ----
    edges: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for node_id, node in nodes.items():
        if node.get("node_type") == "ending":
            continue
        interaction = node.get("interaction")
        if not isinstance(interaction, dict):
            continue

        pointers: list[tuple[str, str]] = []
        default_next = interaction.get("default_next_node")
        if _is_nonempty_str(default_next):
            pointers.append(("default_next_node", default_next))
        for option in _valid_options(node):
            next_node = option.get("next_node")
            if _is_nonempty_str(next_node):
                label = option.get("option_id") or "未命名选项"
                pointers.append((f"选项 {label}", next_node))

        for label, target in pointers:
            if target not in nodes:
                result.add_error(
                    "E_NEXT_UNKNOWN",
                    f"节点 {node_id} 的 {label} 指向不存在的节点: {target}",
                    node_id,
                )
            else:
                edges[node_id].add(target)

    # ---- 起始节点与连通性 ----
    start_node = data.get("start_node")
    start_valid = _is_nonempty_str(start_node) and start_node in nodes
    if _is_nonempty_str(start_node) and start_node not in nodes:
        result.add_error("E_START_MISSING", f"start_node 不存在: {start_node}")

    reachable: set[str] = set()
    if start_valid:
        stack = [start_node]
        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            stack.extend(target for target in edges[current] if target not in reachable)
    result.reachable_count = len(reachable)

    for node_id in sorted(set(nodes) - reachable):
        result.add_warning(
            "W_ISLAND",
            f"不可达孤岛节点: {node_id}",
            node_id,
        )

    # ---- 结局存在性与可达性 ----
    endings = {
        node_id for node_id, node in nodes.items() if node.get("node_type") == "ending"
    }
    result.ending_count = len(endings)

    if not endings:
        result.add_error("E_NO_ENDING", "剧情图至少需要一个 ending 节点")
    elif reachable:
        reverse_edges: dict[str, set[str]] = {node_id: set() for node_id in nodes}
        for source_node, targets in edges.items():
            for target in targets:
                reverse_edges[target].add(source_node)

        can_reach_ending = set(endings)
        stack = list(endings)
        while stack:
            current = stack.pop()
            for previous in reverse_edges[current]:
                if previous not in can_reach_ending:
                    can_reach_ending.add(previous)
                    stack.append(previous)

        dead_ends = sorted(reachable - can_reach_ending)
        if dead_ends:
            result.add_error(
                "E_DEAD_END",
                "以下可达节点无法到达任何结局（死胡同或无出口环）: "
                + ", ".join(dead_ends),
            )

    # ---- 道具闭环 ----
    required_items: dict[str, set[str]] = {}
    granted_items: dict[str, set[str]] = {}

    for node_id, node in nodes.items():
        for option in _valid_options(node):
            for item in _string_list(option.get("required_items")):
                required_items.setdefault(item, set()).add(node_id)
            if node_id in reachable:
                for item in _string_list(option.get("grant_items")):
                    granted_items.setdefault(item, set()).add(node_id)

    for item in sorted(required_items):
        if item not in granted_items:
            sources = ", ".join(sorted(required_items[item]))
            result.add_error(
                "E_ITEM_MISSING",
                f"道具「{item}」被需要，但没有任何可达节点授予（需要节点: {sources}）",
            )

    for item in sorted(granted_items):
        if item not in required_items:
            sources = ", ".join(sorted(granted_items[item]))
            result.add_warning(
                "W_ITEM_UNUSED",
                f"道具「{item}」已授予但从未被 required_items 使用（授予节点: {sources}）",
            )

    return result


def validate_file(filepath: str | Path) -> ValidationResult:
    path = Path(filepath)
    result = ValidationResult(source=str(path))
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        result.add_error("E_FILE_NOT_FOUND", f"文件不存在: {path}")
        return result
    except (OSError, UnicodeDecodeError) as exc:
        result.add_error("E_FILE_READ", f"无法读取文件 {path}: {exc}")
        return result

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        result.add_error(
            "E_JSON",
            f"JSON 解析失败（第 {exc.lineno} 行第 {exc.colno} 列）: {exc.msg}",
        )
        return result

    return validate_graph(data, source=str(path))


def render_human(result: ValidationResult) -> str:
    lines = [
        f"校验文件: {result.source}",
        f"节点数: {result.node_count} | 结局数: {result.ending_count} | "
        f"可达节点: {result.reachable_count}",
    ]

    if result.errors:
        lines.extend(["", f"错误 ({len(result.errors)}):"])
        for issue in result.errors:
            lines.append(f"  [ERROR] {issue.message}  ({issue.code})")

    if result.warnings:
        lines.extend(["", f"警告 ({len(result.warnings)}):"])
        for issue in result.warnings:
            lines.append(f"  [WARN]  {issue.message}  ({issue.code})")

    lines.append("")
    if result.ok:
        suffix = f"，警告 {len(result.warnings)} 条" if result.warnings else ""
        lines.append(
            f"[OK] 校验通过：{result.node_count} 个节点，"
            f"{result.ending_count} 个结局{suffix}。"
        )
    else:
        lines.append(
            f"[FAIL] 校验失败：{len(result.errors)} 个错误，"
            f"{len(result.warnings)} 个警告。"
        )
    return "\n".join(lines)


def validate_chapter(filepath: str) -> bool:
    """兼容旧调用方：校验并打印人类可读结果，返回是否通过。"""
    result = validate_file(filepath)
    print(render_human(result))
    return result.ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验互动影游章节剧情图的结构、连通性、结局与道具闭环。",
    )
    parser.add_argument("filepath", help="章节剧情图 JSON 路径")
    parser.add_argument(
        "--json",
        action="store_true",
        help="只输出结构化 JSON 结果（便于管线调用）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="将 WARN（孤岛/未使用道具）也视为失败",
    )
    args = parser.parse_args(argv)

    result = validate_file(args.filepath)

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_human(result))

    if not result.ok:
        return 1
    if args.strict and result.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
