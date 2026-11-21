---
name: comfyui-minimax-h3-pipeline
description: 用于通过本地 ComfyUI API 批量生成 MiniMax H3 首尾帧分镜视频。当需要导出 API 工作流、运行 scripts/batch_minimax_h3.py、核对 H3 节点输入、做分辨率/时长预算、处理失败重试与 JSON 回填，或在批量生产前确认校验与成本闸门时使用。
---

# MiniMax H3 视频管线（comfyui-minimax-h3-pipeline）

## 0. 适用与前置事实
用于 `story/03_storyboards/chapter_XX.json` → `assets/videos/*.mp4` 的批量生产。本机 ComfyUI `127.0.0.1:8188`（0.46.1，H3 节点已注册）、`imagegen` CLI 缺失、ffmpeg 9.0.2。
脚本 `scripts/batch_minimax_h3.py` 为 stdlib-only，勿引入第三方依赖。

## 1. 两道硬门禁
**A 剧情图**：`python3 scripts/validate_graph.py story/03_storyboards/chapter_01.json --strict` 退出码 0（WARN 也算未过）。
**B 成本**：每次提交（含重跑、补片、换分辨率）前出预估单，总控转述用户并取得明确肯定；沉默/超时/模糊=未确认；未确认严禁 `/prompt`，不允许“先跑一条试试”。脚本层由第 4 节闸门兜底。

## 2. 成本预估单与 approvals
预估单字段：节点清单、单条时长、分辨率分布、总条数、总时长、计费口径、基础预估、失败重试预算（默认 20%）、预计总成本上限；未传 `--cost-per-sec` 时单价与金额显示“待核实”。
确认记录写入 `state/task_board.json` 的 `approvals`（脚本读-合并-原子替换，按 `approval_id` 去重，字段与 README.md 对齐）：
```json
{
  "approval_id": "APR-20261121T223000+0800-a1b2c3", "task_id": "T-014",
  "stage": "批量生视频", "kind": "minimax_h3_video_batch",
  "status": "submitting | completed | partial | failed",
  "requested_at": "2026-11-21T22:30:00+08:00", "confirmed_at": "2026-11-21T22:31:00+08:00",
  "confirmed_by": "interactive:CONFIRM | cli:--yes", "user_reply": "确认生成（CONFIRM）",
  "chapter_file": "story/03_storyboards/chapter_01.json", "workflow_file": "comfyui/minimax_h3_api.json",
  "estimated": {"resolution": "480p", "resolutions": {"480p": 6}, "nodes": 6, "node_ids": ["ch01_s01_open"],
                "total_duration_sec": 28.0, "unit_price": 1.5, "cost_unit": "积分", "estimated_cost": 42.0,
                "retry_budget": 2, "retry_budget_sec": 5.6, "retry_budget_cost": 8.4, "total_cost_cap": 50.4},
  "submitted": {"nodes": 0, "total_duration_sec": 0.0, "cost": 0.0},
  "actual": {"nodes": 0, "total_duration_sec": 0.0, "cost": 0.0},
  "failed_nodes": []
}
```
单价未知时 `unit_price`/`estimated_cost`/`retry_budget_cost`/`total_cost_cap` 写“待核实”；实际用量超基础预估 10% 或需重跑时须重新确认（流程规则，脚本不自动拦截），并让脚本自动生成新 `approval_id`，不要覆盖旧记录。

## 3. ComfyUI API 工作流导出
1. 在 UI 搭通 H3 工作流并跑通一条样例。
2. 菜单 **Workflow → Export (API)**；旧版需在设置开启 *Enable Dev mode Options* 后用 **Save (API Format)**。
3. 得到扁平 JSON `{"<node_id>": {"class_type": "...", "inputs": {...}}}`；UI 版 workflow 不能直接喂脚本。
4. 文件放项目内（建议 `comfyui/minimax_h3_api.json`，目录尚未创建，属占位）。
5. 生成节点应为 `ComfyCloudMiniMaxH3FirstLastFrameToVideoNode`；输出 mp4 的落盘位置以本机 output 目录为准（待核实）。

## 4. 脚本用法与真实行为
```bash
python3 scripts/batch_minimax_h3.py story/03_storyboards/chapter_01.json comfyui/minimax_h3_api.json --dry-run
python3 scripts/batch_minimax_h3.py ... --yes --cost-per-sec 1.5 --cost-unit 积分 --resolution 480p --task-id T-014
```
- 必填两参：章节 JSON、API 工作流 JSON；`--dry-run` 只打印预估单，不写审批、不排队、不产生费用。
- 参数：`--cost-per-sec`（未知别传）、`--cost-unit`（默认积分）、`--retry-rate`（默认 0.2）、`--resolution 480p|720p`（覆盖全部待生成节点）、`--default-duration`、`--poll-interval`、`--task-id`、`--approval-id`、`--yes`。
- 确认：交互终端输入精确 `CONFIRM`；非交互且无 `--yes` 时只出单并返回退出码 2；`--yes` 表示已获用户明确确认（`confirmed_by=cli:--yes`）。
- 确认后先写 `approvals`，写入失败则拒绝提交（退出码 2）；随后逐条 `/prompt` 并轮询 `/history`。
- 注入：深拷贝模板，只改 `class_type` 含 `MiniMaxH3` 的节点（模板无 H3 时才退回全部节点）的 `prompt`；`resolution`、`duration_seconds`（取整）仅在对应输入存在时改写。无可注入节点则报错；多个 H3 节点会被注入同一提示词，应只保留一个。
- 跳过：`video_path` 非空且本地文件存在则 `[SKIP]`；重跑/补片前先清理对应路径或文件，让脚本重新纳入预估。
- 结束：回填 `assets/videos/<node_id>.mp4` 并覆盖章节 JSON；审批记录更新 `status=completed|partial|failed` 与 `submitted`/`actual`/`failed_nodes`。
- 退出码：0 成功/仅出单/无待生成；1 输入或执行错误；2 未确认或审批写入失败。

仍保留的缺口：
- `/history` 轮询无总超时，只能人工中断；不下载/搬运视频，`video_path` 可能指向未归档文件；`ending` 节点也会回填路径。
- 无逐节点重试；中断时已提交的仍计费，重跑必须重新过闸门。

## 5. H3 节点输入
`ComfyCloudMiniMaxH3FirstLastFrameToVideoNode` 的输入（以节点 UI 实际显示为准）：

| 输入 | 类型 | 说明 |
|---|---|---|
| `first_frame` | IMAGE | 首帧，通常接 `LoadImage`；图片需放入 ComfyUI 的 input 目录（或使用其上传机制，待核实） |
| `prompt` | STRING | 取 `video.video_prompt`，只写运动/镜头/时序 |
| `seed` | INT | 固定后便于复现；重跑换 seed 属于新成本 |
| `aspect_ratio` | 枚举 | `16:9` / `9:16` 等，取值以节点选项为准（待核实） |
| `resolution` | 枚举 | `480p` / `720p` 等，取值待核实；与预算表一致 |
| `duration_seconds` | INT | 与 JSON `duration_sec` 对齐，节点可接受范围待核实 |

`last_frame` 的输入名与是否可选**待核实**：以导出的 API JSON 实际键名为准，不要凭本 Skill 猜。

## 6. 首尾帧 → 视频：两段式流程
1. 首帧图 → 末帧图（生图阶段产出，同角色锚定、同机位、末态构图）。
2. 校验首/末帧同分辨率、同画幅、主体位置不跳变；模板接好 `first_frame` 与末帧输入。
3. `prompt` 描述“从首帧到末帧发生什么”；每镜先出 480p 单条验收动作与衔接，再决定是否 720p 重跑（重跑=新成本）。
4. 无末帧时：节点若支持仅首帧模式则用之，否则补生成末帧；不要把首帧复制为末帧硬凑（画面几乎静止），是否支持仅首帧模式**待核实**。

## 7. 分辨率 / 时长预算
| 档位 | 典型像素 | 用途 | 备注 |
|---|---|---|---|
| 480p | 854×480 | 草稿、动作/QTE 时序验证、内部审片 | 迭代首选 |
| 720p | 1280×720 | 终版、关键情绪镜、预告 | 像素约为 480p 的 2.25 倍，耗时与成本同步上升 |

- 成本近似与“条数 × 时长 × 分辨率系数”成正比；实际单价以 Comfy Cloud 账单/控制台为准，本 Skill 不写具体金额（待核实）。
- 单镜 4–6s 为主，情绪镜可到 8s，超过 8s 拆镜；同一章不要混用分辨率交付，草稿与终版分目录或加后缀（约定待定）。

## 8. 失败重试与 JSON 回填
- 连接失败（`URLError`/拒绝连接）：先确认 ComfyUI 进程与 8188 端口，再重试；不要在未确认原因时重复排队。
- `/prompt` 返回 400：工作流校验失败，多为模型未加载、输入缺失、`first_frame` 文件名不存在；修模板，不要原样重试。
- `/history` 长时间无记录：脚本无总超时，人工 `Ctrl-C`；确认队列无残留再重排。
- 产物黑屏/闪烁/人物崩坏：换 seed 重跑，单节点最多 2 次；每次重跑计入成本，超预估 10% 需重新确认；连续 2 次失败回报总控。

回填规范：
1. 只写 `video.first_frame_path`、`last_frame_path`、`video_path`，不改 `video_prompt`/`dialogue`/`interaction`。
2. 路径必须真实存在且可播放（`ffprobe -v error -show_entries format=duration -of csv=p=0 <mp4>`）；脚本只写路径，归档需人工或补脚本完成。
3. 保持 UTF-8、2 空格缩进；回填后重跑 `validate_graph.py --strict`，把实际条数/时长/积分写进 `approvals.actual`；不要手工批量改 id。

## 9. 生产前检查清单
- [ ] 门禁 A：`validate_graph.py --strict` 退出码 0；门禁 B：`approvals` 中有明确确认，预估单与实际范围一致。
- [ ] 首/末帧齐备，命名 `assets/frames/<chapter_id>/<node_id>_first|last.png`。
- [ ] API 工作流 JSON 已导出为 API 格式，H3 节点 ID 与模板映射已核对。
- [ ] `duration_sec`、`resolution` 与预算表一致；重试预算、归档方式已就绪，避免“路径已写、文件没到”。
- [ ] 记录 `prompt_id`、seed、耗时、实际积分，便于对账与超支复查。

## 10. 边界
- Agy 只提供提示词与剧情图，**不触发** `/prompt`；Codex 负责提交、归档、回填。
- 不改 `story/` 叙事内容；不伪造校验通过或成本确认；不编造端点、参数与单价；脚本保持 stdlib-only，新增能力走任务单由 Codex 实现。
