# 互动影游项目三方协作规范 (AGENTS.md)

## 1. 角色与权限边界
- **DeepSeek Harness (总控导演 / Orchestrator)**：
  - 唯一与用户直接沟通需求、确认题材与分支走向的入口。
  - 负责将用户意图拆解为标准任务单，更新 `state/task_board.json`，并分别向 Agy 和 Codex 派发指令。
  - 严禁直接修改底层代码或大段重写剧本，专注任务拆解、依赖检查与阶段验收。
- **Agy (叙事与视觉设计 / Creative Lead)**：
  - 负责 `story/` 目录下的题材选材、世界观、角色圣经、分支剧本编写、分镜设计以及 `imagegen` / `MiniMax H3` 提示词编写。
  - 产出的分支结构必须严格符合 `schema/story_graph.schema.json`。
- **Codex (工程与本地管线执行 / Technical Lead)**：
  - 负责 `scripts/`、`schema/`、`player/` 与 `assets/`。
  - 负责校验 Agy 产出的剧情图连通性（无死链、道具闭环），调用本地 `imagegen` 与 `ComfyUI (MiniMax H3)` API 批量生产媒体资产，并开发互动视频播放器。

## 2. 核心流水线流转规则 (Pipeline)
1. **立项与选材**：用户 <-> DeepSeek Harness 确认题材 -> 派单 Agy 生成 `story/01_bible/`。
2. **分支与分镜**：Agy 编写章节分支节点与首尾帧提示词 -> 输出至 `story/03_storyboards/chapter_XX.json`。
3. **工程校验**：DeepSeek Harness 派单 Codex 运行 `scripts/validate_graph.py`，检查分支死锁与道具触发条件。
4. **资产批量生成**：校验通过后，Codex 依次执行本地 `imagegen`（生成首尾帧）与 `ComfyUI MiniMax H3`（生成分镜视频），并将文件路径回填至 JSON。**提交任何视频生成任务前，必须先通过「成本确认闸门」（见第 3 节）。**
5. **联调预览**：Codex 更新 `player/` 播放器配置，交付用户试玩验收。

## 3. 成本确认硬规则（视频生成）
- 每次（含重跑、补片、换分辨率）提交 MiniMax H3 视频任务前，Codex 必须先提交《视频成本预估单》：节点清单、单条时长、分辨率、总条数、总时长、计费口径（Comfy Cloud 积分/单价）、预计总成本与失败重试预算。
- 总控必须把预估单转述给用户，并获得**明确肯定答复**（如“确认生成”）；沉默、超时、含糊回复一律视为未确认。
- 未确认前严禁调用 ComfyUI `/prompt` 排队，不允许先跑一条“试试看”。
- 确认记录（时间、用户回复摘要、预估量、实际提交量）写入 `state/task_board.json` 的 `approvals`；实际用量超出预估 10% 或需要重跑时，必须重新确认。
- 产生云端费用的批量生图同样适用本规则。
