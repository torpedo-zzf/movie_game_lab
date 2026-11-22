# 《视频成本预估单》第一章全量（T-014 / APR-20261122-VID-005）

> 提出：2026-11-22 23:43 +08:00
> 状态：**待用户确认**（未确认前不调用 `/v2/video_generation`）
> 供应商：MiniMax H3 直连 API（metaso.cn 代理）
> 机器可读版：`state/cost_estimate_full_batch_ch01.json`

## 1. 范围

- **11 条**分镜视频（`ch01_s01_voiceover` 已于 APR-20261122-VID-004 完成，不重复计费）。
- 分辨率 **480p**，比例 `adaptive`（跟随首帧 16:9），`fast_mode=false`。
- 每条首末帧来自 OSS：`movie_game_lab/frames/<node>_first.png` / `_last.png`。
- 总时长 **84 秒**。

## 2. 节点清单

| # | 节点 | 类型 | 时长 | 预估 credits |
|---|---|---|---|---|
| 1 | `ch01_s02_peephole` | video_play | 8s | 61.07 |
| 2 | `ch01_s03_knock` | choice_branch | 8s | 61.07 |
| 3 | `ch01_s04_open` | video_play | 8s | 61.07 |
| 4 | `ch01_s05_listen` | video_play | 8s | 61.07 |
| 5 | `ch01_s06_lock` | video_play | 7s | 53.44 |
| 6 | `ch01_s07_elevator` | video_play | 7s | 53.44 |
| 7 | `ch01_s08_groupchat` | video_play | 7s | 53.44 |
| 8 | `ch01_s09_second_knock` | video_play | 8s | 61.07 |
| 9 | `ch01_s10_choice` | choice_branch | 8s | 61.07 |
| 10 | `ch01_s11_end_testify` | ending | 7s | 53.44 |
| 11 | `ch01_s12_end_silence` | ending | 8s | 61.07 |
| | **合计** | | **84s** | **641.25** |

## 3. 计费口径

- 依据：APR-20261122-VID-003 实测 **7s / 480p / 2 张输入图 = 53.44 credits**，折算约 **7.63 credits/秒**。
- 官方口径「基础费 + 素材费 + 输出费」；8s 按线性外推 ≈ 61 credits，实际可能更低，因此另给上限。
- 1 credit 按 **$0.0025** 折算（非正式账单，仅作预算参考）。

## 4. 预计总成本

| 项 | credits | 约 USD |
|---|---|---|
| 基础生成（11 条 / 84s） | 641 | **$1.60** |
| 失败重试预算（20%，约 2 条 / 15s） | 128 | $0.32 |
| **合计上限（cap）** | **800** | **$2.00** |

参考：s01 已用 53.44 credits（$0.13）；本章含 s01 合计上限约 **$2.13**。
当前余额 **11498.12 credits**，本单占余额约 7%。

## 5. 失败与重试规则

1. 单条失败/超时：只重跑**失败节点**，同一条最多重试 1 次，计入重试预算。
2. 实际基础用量超预估 **10%**（> 705 credits）或需要换方案重跑：**立即停手，重新出单确认**。
3. 触达 cap（800 credits）即停止，不再提交。
4. 失败不并发补片；按节点顺序重跑，避免余额与并发限制。

## 6. 提交方式

- 顺序单条提交，逐条回填 `chapter_01.json` 的 `video.video_path`：

```bash
python3 scripts/minimax_h3_generate.py \
  --approval-id APR-20261122-VID-005 \
  --node <node_id> --resolution 480p --duration <7|8> \
  --out assets/videos/<node_id>.mp4 --confirm CONFIRM
```

- 每条完成后 `ffprobe` 校验（时长 7/8s、854×480）并记录余额变化。
- 实际用量与异常写入 `state/task_board.json` 的 `approvals`。

## 7. 已完成的前置检查

- `python3 scripts/validate_graph.py story/03_storyboards/chapter_01.json --strict` → **exit 0**（12 节点 / 2 结局 / 全可达）。
- 22 张首末帧已上传 OSS 并 HEAD 200（2026-11-22 23:42）。
- OSS 签名 URL、MiniMax key、余额查询均已验证。

## 8. 需要用户确认的一句话

> **「确认生成 11 条」**

沉默、超时、含糊回复（如「看着办」）一律视为**未确认**；收到明确肯定答复后才提交第一条。
