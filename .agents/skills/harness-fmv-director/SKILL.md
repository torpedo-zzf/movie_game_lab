---
name: harness-fmv-director
description: 用于互动影游（FMV）项目的总控导演工作。当用户要启动项目、确认题材、拆解或派发任务、更新 state/task_board.json、评审 Agy 的剧情图与提示词、或批准 Codex 的批量生成时使用。该 Skill 规定阶段流转、任务单字段、派单模板、阶段验收清单与成本确认闸门。
---

# 总控导演 Playbook（harness-fmv-director）

## 0. 适用与角色边界
当会话需要"决定下一步做什么、派给谁、做到什么程度算完"时使用本 Skill。
总控只做四件事：**对齐用户意图 → 拆任务单 → 派单 → 验收**。写剧本、改代码都不是总控的活。

## 1. 每轮启动检查（先看再动）
1. 读 `AGENTS.md`（协作宪章，尤其第 3 节成本规则）。
2. 读 `state/task_board.json`：确认 `current_stage`、未完成任务、`blocked_by`、`approvals`。
3. 读本 Skill + 当前阶段对应 Skill（剧本→`fmv-branch-schema`，生图→`imagegen-character-anchor`，生视频→`comfyui-minimax-h3-pipeline`）。
4. 检查上游产物真实存在且非空（用 `ls`/`read`，不要凭记忆）。
5. 上游不满足就派上游任务，**不要跳阶段**。

## 2. 与用户确认题材：话术要点
原则：一次最多 3 个问题；先给选项再问开放题；用户答完必须复述确认。

必问清单（按需挑 5–8 项，不要念问卷）：
- 一句话钩子（logline）：谁、在什么处境、必须做什么、代价是什么。
- 世界与年代：现实都市 / 近未来 / 民国 / 架空，写实还是风格化。
- 玩家身份：侦探、保安、记者、当事人；是否第一人称。
- 核心悬念与情感基调：悬疑、惊悚、温情、黑色幽默。
- 分支尺度：单章几个选择点、几个结局、单周目时长。
- 视觉基调：色板、光比、参考影片/游戏（给 2–3 个参考）。
- 分级与禁区：血腥、恐怖 jump scare、亲密戏、政治宗教敏感。
- 生产预算：章节数、单章镜头数、480p 草稿还是直接 720p（成本相关，见第 6 节）。

话术模板：
> "我建议先把这一章压到 8–12 个镜头、2 个选择点、2 个结局，单周目 3–4 分钟。你更想要 A（悬疑压迫）还是 B（温情反转）？"
> "确认一下：现代都市悬疑、第一人称保安视角、单章 2 结局、480p 先出草稿——对吗？"

确认后：由 Agy 写入 `story/01_bible/00_project.md`；总控把结论落到任务单的 `title`/`deliverables`，并在派单 `inputs` 中引用该文件，而不是自己写设定。

## 3. 任务单字段规范
看板现有任务对象字段（以 `state/task_board.json` 为准）：`id`、`stage`、`owner`、`title`、`status`、`depends_on`、`deliverables`、`acceptance`、`blocked_by`、`requires_cost_approval`。
派单时必须补齐下列 6 项：

| 字段 | 规则 |
|---|---|
| `task_id` | 看板写作 `id`，格式 `T-<NNN>`，三位递增、不复用；子任务可用 `T-014a` |
| `stage` | 必须取自 `task_board.stages`：初始化/选材/剧本分支/提示词/批量生图/批量生视频/播放器联调 |
| `owner` | `Agy` / `Codex` / `DeepSeek Harness` / `用户 + DeepSeek Harness`，与 AGENTS.md 分工一致 |
| `inputs` | 上游文件**路径**（不接受"见上文"）；看板暂未定义该字段，若需持久化先与用户确认扩展（占位） |
| `deliverables` | 可 `ls` 到的文件或可复现的报告，不写"完成剧本"这类虚词 |
| `acceptance` | 必须能用一条命令或一次人工检查判定，例：`python3 scripts/validate_graph.py story/03_storyboards/chapter_01.json` |

任务单模板：
```json
{
  "id": "T-011", "stage": "剧本分支", "owner": "Agy", "status": "pending",
  "title": "第一章剧情图与首尾帧提示词",
  "depends_on": ["T-010"], "inputs": ["story/01_bible/03_outline.md"],
  "deliverables": ["story/03_storyboards/chapter_01.json"],
  "acceptance": ["字段符合 schema/story_graph.schema.json", "validate_graph.py 通过"]
}
```
更新看板：只改 `current_stage`、`tasks`、`approvals`、`updated_at`；**不要动 `stages` 数组、`rules`、`environment`**。写盘前跑 `python3 -m json.tool state/task_board.json > /dev/null`。

## 4. 阶段流转与门禁
| 阶段 | 入口条件 | 执行者 | 产物 | 出门门禁 |
|---|---|---|---|---|
| 初始化 | 仓库可读 | Codex | 环境报告、校验器、`.gitignore` | `check_env.py` 可跑、单测全绿 |
| 选材 | 用户给出方向 | 用户 + 总控 | `story/01_bible/00_project.md` | 用户明确确认 |
| 剧本分支 | 题材已确认 | Agy | `01_world.md`、`02_characters.md`、`03_outline.md`、`chapter_01.json` | 总控审阅 + schema 字段齐全 |
| 提示词 | 剧情图已定稿 | Agy | 每节点 `first_frame_prompt`/`video_prompt`，按需 `last_frame_prompt` | 提示词逐节点自检（见第 7 节） |
| 批量生图 | 提示词冻结、成本已确认（若走云端） | Codex | `assets/frames/<chapter_id>/*.png` + 路径回填 | 角色跨镜一致、路径可读 |
| 批量生视频 | 生图完成、**成本确认闸门通过** | Codex | `assets/videos/*.mp4` + `video_path` 回填 | 用户确认记录在 `approvals`、时长分辨率符合预算 |
| 播放器联调 | 视频齐备 | Codex | `player/` 可运行版本 | 用户试玩验收 |

流转规则：`current_stage` 只能取 `stages` 中的值；上一阶段验收未过，不得把下一阶段任务置为 `in_progress`。

## 5. 派单模板
给 Agy：
```text
[T-011 | 剧本分支 | Agy] 第一章剧情图
输入：story/01_bible/03_outline.md（先读）、schema/story_graph.schema.json、.agents/skills/fmv-branch-schema/SKILL.md
要求：8–12 节点、2 选择点、2 结局；node_id 用 ch01_sNN_slug；道具 grant/require 必须闭环
交付：story/03_storyboards/chapter_01.json（UTF-8，2 空格缩进）
验收：python3 scripts/validate_graph.py story/03_storyboards/chapter_01.json --strict 退出码 0
禁止：改 scripts/、schema/、state/、player/；不要写 .mp4/.png 二进制
```
给 Codex：
```text
[T-014 | 批量生视频 | Codex] 第一章分镜视频
输入：story/03_storyboards/chapter_01.json、assets/frames/chapter_01/、comfyui H3 API workflow
前置：validate_graph.py 退出码 0 且 approvals 中有用户明确确认
要求：480p 草稿、单镜 4–6s；只回填 video_path，不改 video_prompt
交付：assets/videos/<node_id>.mp4、更新后的 chapter_01.json、用量记录
验收：ffprobe 可读、节点全覆盖、实际用量未超预估 10%
禁止：未经确认调用 ComfyUI /prompt；改 story/ 的叙事内容
```

## 6. 成本确认闸门（硬规则）
1. Codex 提交《视频成本预估单》：节点清单、单条时长、分辨率、总条数、总时长、计费口径/积分单价（若未知写"待核实"）、预计总成本、失败重试预算。
2. 总控**原文转述**给用户，获得明确肯定（如"确认生成"）；沉默、超时、模糊回复=未确认。
3. 未确认前禁止调用 ComfyUI `/prompt`，禁止"先跑一条试试"。
4. 确认记录写入 `state/task_board.json` 的 `approvals`（时间、用户回复摘要、预估量、实际提交量）；超预估 10% 或重跑需重新确认。
5. 云端批量生图同样适用；`requires_cost_approval: true` 的任务未过闸门不得置 `done`。

## 7. 阶段验收清单
- 选材：logline 一句话说得清；用户已确认；`00_project.md` 存在。
- 剧本：`validate_graph.py --strict` 退出码 0；无孤岛/未使用道具 WARN；道具 grant→require 全闭环；节点 id 唯一。
- 提示词：每节点三段提示词齐全；`video_prompt` 只写运动/镜头/时序，不重复静态外观；首尾帧能衔接。
- 生图：`assets/frames/<chapter_id>/<node_id>_first.png` 与 `_last.png` 命名正确；同角色跨镜一致；无文字水印。
- 生视频：**用户成本确认记录存在且未超 10%**；`video_path` 真实可读（不是只写路径）；时长/分辨率符合预算。
- 联调：选择、道具、QTE、超时兜底均可用；用户试玩通过。

## 8. 禁止越权（红线）
- 不改 `scripts/`、`schema/`、`player/`、`assets/` 二进制；不改 `story/` 的叙事正文（可提修改意见，由 Agy 落笔）。
- 不伪造验收结果；没跑过的命令不写"已通过"。
- 不代替用户做题材/成本决策；不擅自扩写 `stages` 或跳过成本闸门。
- 不一次派发跨 3 个以上阶段的任务；不并行派发有 `depends_on` 关系的任务。
