#!/usr/bin/env python3
"""validate_graph.py 的单元测试。

运行：python3 -m unittest scripts/test_validate_graph.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_graph import render_human, validate_file  # noqa: E402


def _video() -> dict:
    return {
        "first_frame_prompt": "深夜走廊，冷白顶灯，广角",
        "last_frame_prompt": "推近磨砂玻璃门，门缝透出暖光",
        "video_prompt": "镜头缓慢前推，顶灯轻微闪烁",
        "duration_sec": 5.0,
    }


def _node(
    node_id: str,
    node_type: str = "video_play",
    *,
    next_node: str | None = None,
    options: list[dict] | None = None,
    video: dict | None = None,
) -> dict:
    node = {
        "node_id": node_id,
        "node_type": node_type,
        "video": video or _video(),
    }
    if node_type != "ending":
        interaction: dict = {}
        if next_node is not None:
            interaction["default_next_node"] = next_node
        if options is not None:
            interaction["options"] = options
        node["interaction"] = interaction
    return node


def _graph(nodes: list[dict], start_node: str = "start") -> dict:
    return {
        "chapter_id": "chapter_test",
        "title": "测试章节",
        "start_node": start_node,
        "nodes": nodes,
    }


def _valid_graph() -> dict:
    return _graph(
        [
            _node("start", next_node="branch"),
            _node(
                "branch",
                "choice_branch",
                next_node="end_good",
                options=[
                    {
                        "option_id": "opt_take",
                        "label": "拿走钥匙",
                        "next_node": "end_good",
                        "grant_items": ["item_key"],
                    },
                    {
                        "option_id": "opt_leave",
                        "label": "用钥匙离开",
                        "next_node": "end_bad",
                        "required_items": ["item_key"],
                    },
                ],
            ),
            _node("end_good", "ending"),
            _node("end_bad", "ending"),
        ]
    )


class ValidateGraphTest(unittest.TestCase):
    def _validate(self, data: dict):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chapter.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return validate_file(path)

    def test_valid_graph_passes_and_prints_counts(self) -> None:
        result = self._validate(_valid_graph())

        self.assertTrue(result.ok, [issue.message for issue in result.errors])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.node_count, 4)
        self.assertEqual(result.ending_count, 2)
        self.assertEqual(result.reachable_count, 4)

        text = render_human(result)
        self.assertIn("节点数: 4", text)
        self.assertIn("结局数: 2", text)
        self.assertIn("[OK]", text)

    def test_unknown_next_node_fails(self) -> None:
        graph = _graph(
            [
                _node("start", next_node="ghost"),
                _node("end", "ending"),
            ]
        )
        result = self._validate(graph)

        self.assertFalse(result.ok)
        codes = {issue.code for issue in result.errors}
        self.assertIn("E_NEXT_UNKNOWN", codes)
        self.assertTrue(
            any("ghost" in issue.message for issue in result.errors),
            [issue.message for issue in result.errors],
        )

    def test_missing_required_item_fails(self) -> None:
        graph = _graph(
            [
                _node(
                    "start",
                    next_node="end",
                    options=[
                        {
                            "option_id": "opt_open",
                            "label": "开门",
                            "next_node": "end",
                            "required_items": ["item_key"],
                        }
                    ],
                ),
                _node("end", "ending"),
            ]
        )
        result = self._validate(graph)

        self.assertFalse(result.ok)
        codes = {issue.code for issue in result.errors}
        self.assertIn("E_ITEM_MISSING", codes)
        self.assertTrue(
            any("item_key" in issue.message for issue in result.errors),
            [issue.message for issue in result.errors],
        )

    def test_island_is_warning_not_error(self) -> None:
        graph = _graph(
            [
                _node("start", next_node="end"),
                _node("end", "ending"),
                _node("island", next_node="end"),
            ]
        )
        result = self._validate(graph)

        self.assertTrue(result.ok, [issue.message for issue in result.errors])
        self.assertEqual(result.errors, [])
        self.assertEqual([issue.code for issue in result.warnings], ["W_ISLAND"])
        self.assertIn("island", result.warnings[0].message)
        self.assertEqual(result.reachable_count, 2)

    def test_graph_without_ending_fails(self) -> None:
        graph = _graph(
            [
                _node("start", next_node="loop"),
                _node("loop", next_node="start"),
            ]
        )
        result = self._validate(graph)

        self.assertFalse(result.ok)
        codes = {issue.code for issue in result.errors}
        self.assertIn("E_NO_ENDING", codes)
        self.assertEqual(result.ending_count, 0)

    def test_dead_end_cycle_fails(self) -> None:
        graph = _graph(
            [
                _node(
                    "start",
                    "choice_branch",
                    next_node="end",
                    options=[
                        {
                            "option_id": "opt_safe",
                            "label": "直接离开",
                            "next_node": "end",
                        },
                        {
                            "option_id": "opt_trap",
                            "label": "走进循环",
                            "next_node": "cycle_a",
                        },
                    ],
                ),
                _node("cycle_a", next_node="cycle_b"),
                _node("cycle_b", next_node="cycle_a"),
                _node("end", "ending"),
            ]
        )
        result = self._validate(graph)

        self.assertFalse(result.ok)
        codes = {issue.code for issue in result.errors}
        self.assertIn("E_DEAD_END", codes)
        dead_end = next(issue for issue in result.errors if issue.code == "E_DEAD_END")
        self.assertIn("cycle_a", dead_end.message)
        self.assertIn("cycle_b", dead_end.message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
