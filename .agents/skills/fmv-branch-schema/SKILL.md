---
name: fmv-branch-schema
description: 用于编写或评审互动影游的章节剧情图 JSON。当 Agy 要设计分支结构、确定节点类型与 node_id、设计道具经济、撰写首尾帧与 video_prompt，或对话需要判断某个剧情图能否通过 scripts/validate_graph.py 时使用。该 Skill 逐字段解释 schema/story_graph.schema.json 并给出 8 节点最小示例。
---

# 剧情图编写规范（fmv-branch-schema）

## 0. 适用与交付物
用于 `story/03_storyboards/chapter_XX.json` 的编写与自检。
真实 schema 以 `schema/story_graph.schema.json` 为唯一准绳；本 Skill 是操作说明，冲突时以 schema 与校验器为准。

## 1. 顶层字段（4 个，全部必填）
- `chapter_id`：字符串，必须与目录/资产路径一致，如 `chapter_01`。同一项目内唯一。
- `title`：对玩家显示的章节名，如 `第一章：夜班门禁`。
- `start_node`：入口 `node_id`，必须真实存在于 `nodes`，否则校验失败。
- `nodes`：节点数组，至少 1 个；**每个节点 id 全局唯一**。

## 2. 节点字段
必填三项：`node_id`、`node_type`、`video`。
- `node_id`：字符串，命名见第 4 节。
- `node_type`：枚举 `video_play` / `choice_branch` / `item_discovery` / `qte_event` / `ending`，见第 3 节。
- `speaker`：可选，说话人；旁白写 `旁白`。
- `dialogue`：可选，单句台词，建议 ≤ 28 字（播放器字幕一行放得下，具体以 `player/` 实现为准）。
- `video`：对象，必填 `first_frame_prompt` 与 `video_prompt`。
  - `first_frame_prompt`：首帧静帧描述，用于生图。
  - `last_frame_prompt`：可选，末帧描述；用于首尾帧模式，必须能与下一节点首帧视觉衔接。
  - `video_prompt`：运动描述，见第 6 节。
  - `duration_sec`：数字，单镜时长；建议 4–6，关键镜 ≤ 8。
  - `first_frame_path` / `last_frame_path` / `video_path`：字符串，**由 Codex 回填**，Agy 不填。
- `interaction`：非 `ending` 节点必填（校验器强制），`ending` 可省略。
  - `default_next_node`（必填）：超时/无操作/默认推进目标，必须存在。
  - `trigger_time_sec`：选项弹出的时间点，应小于 `duration_sec`。
  - `timeout_sec`：无操作等待时长；到时走 `default_next_node`。
  - `options`：数组，每项必填 `option_id`、`label`、`next_node`；可选 `required_items`、`grant_items`（道具 id 字符串数组）。

## 3. 节点类型选用指南
| 类型 | 用途 | 关键配置 | 注意 |
|---|---|---|---|
| `video_play` | 纯叙事/对话推进 | `default_next_node` | 默认类型；90% 的镜头用它 |
| `choice_branch` | 玩家二选一/三选一 | `options` + `default_next_node` | 每支 2–3 个选项；默认项也必须是合法分支 |
| `item_discovery` | 拾取/获得道具 | 选项里 `grant_items`，`default_next_node` 为"错过"分支 | 让玩家有得有失，不强塞 |
| `qte_event` | 限时反应 | `trigger_time_sec` + `timeout_sec` 兜底 | QTE 失败不应直接死档，除非是设计好的结局 |
| `ending` | 章节终止 | 无 `interaction` | 每个结局节点仍需 `video` 两段提示词 |

运行时语义（QTE 判定窗口、道具栏展示）由 `player/` 实现决定，当前脚手架未实现，**具体行为待核实**；写 JSON 时只依赖 schema 已定义的字段。

## 4. node_id 命名约定
- 主干：`ch<两位章号>_s<两位场景号>_<语义短名>`，如 `ch01_s03_trust`。
- 结局：`ch01_s06_end_caught`、`ch01_s07_end_escape`；结局 id 带 `end` 便于统计。
- 分支并存时用同一场景号 + 语义后缀，如 `ch01_s03_trust` / `ch01_s03_doubt`，重汇后继续递增。
- 选项：`opt_trust`、`opt_alone`；全章唯一，不要 `opt_a` 重复。
- 道具：`item_<小写英文>`，如 `item_brass_key`；同一道具全项目同名。
- 禁止：中文 id、空格、自增纯数字（`1`、`2`）、改稿后复用旧 id（会造成资产覆盖）。

## 5. 道具经济：grant/require 闭环
1. 列一张表：道具 id → 哪条路径 `grant_items` → 哪些选项 `required_items`。
2. 每个 `required_items` 里的道具，必须至少有一条**可达**路径能 grant；且 grant 发生在 require 之前。
3. 防死锁三查：会不会"要求 A 才能拿到 A"；会不会两个分支互相要求对方道具；结局前是否还有未消费的必需道具。
4. 道具只在 `options` 上流转（schema 没有节点级 grant 字段）；因此 `item_discovery` 也要靠选项发放。
5. 漏拿道具必须仍有出路：给 require 选项一个不需要道具的 `default_next_node` 或备选选项。

## 6. 首尾帧提示词 vs video_prompt
| 维度 | `first_frame_prompt` / `last_frame_prompt` | `video_prompt` |
|---|---|---|
| 内容 | 静态画面：主体、服装、表情、构图、景别、光位、色温、场景陈设 | 时间过程：动作、镜头运动、节奏、光变、转场 |
| 词性 | 名词短语堆叠，像摄影 brief | 动词驱动，一句一个动作，按时序写 |
| 人物 | 固定角色描述块（发色/服装/标志物），便于锚定 | 只写动作与情绪变化，不重复外观 |
| 镜头 | 明确"中景/特写/广角、平视/俯拍" | 明确"缓推/横移/手持跟拍/固定" |
| 衔接 | 末帧应≈下一节点首帧（机位、光、服化一致） | 结尾落在末帧构图，避免"飞出去" |
| 长度 | 40–80 字 | 30–60 字，≤ 2 个镜头动作 |

同一角色跨节点复用同一段外观描述（与角色 Bible 完全一致），只改镜头与场景；这是后续生图一致性的前提。

## 7. 最小章节示例（8 节点，应能通过校验）
```json
{
  "chapter_id": "chapter_01",
  "title": "第一章：夜班门禁",
  "start_node": "ch01_s01_open",
  "nodes": [
    {"node_id": "ch01_s01_open", "node_type": "video_play", "speaker": "旁白",
     "dialogue": "凌晨两点，整栋楼只剩走廊尽头那一盏灯。",
     "video": {"first_frame_prompt": "深夜写字楼走廊，冷白顶灯，尽头一扇磨砂玻璃门，广角，无人", "last_frame_prompt": "同机位推近，门缝透出暖黄光", "video_prompt": "镜头缓慢前推，顶灯轻微闪烁，尘埃在光束中浮动", "duration_sec": 5.0},
     "interaction": {"trigger_time_sec": 4.2, "default_next_node": "ch01_s02_choice"}},
    {"node_id": "ch01_s02_choice", "node_type": "choice_branch", "speaker": "林晚",
     "dialogue": "门后面，好像有人。",
     "video": {"first_frame_prompt": "林晚站在走廊中央，右手握工牌，侧身回望，中景", "last_frame_prompt": "林晚停在门前，手抬起一半", "video_prompt": "林晚向前两步又停住，镜头轻微横移跟拍", "duration_sec": 5.0},
     "interaction": {"trigger_time_sec": 3.0, "timeout_sec": 6.0, "default_next_node": "ch01_s03_trust", "options": [{"option_id": "opt_trust", "label": "相信守夜人", "next_node": "ch01_s03_trust"}, {"option_id": "opt_alone", "label": "独自调查", "next_node": "ch01_s03_doubt"}]}},
    {"node_id": "ch01_s03_trust", "node_type": "video_play", "speaker": "老陈",
     "dialogue": "别开那扇门。上个月也有人这么干。",
     "video": {"first_frame_prompt": "守夜人老陈从阴影里走出，手电光扫过墙面，过肩中景", "last_frame_prompt": "老陈把手电压低，光斑落在配电箱上", "video_prompt": "老陈走近，手电光柱扫过墙面后停在配电箱", "duration_sec": 5.0},
     "interaction": {"trigger_time_sec": 4.0, "default_next_node": "ch01_s04_key"}},
    {"node_id": "ch01_s03_doubt", "node_type": "video_play", "speaker": "林晚",
     "dialogue": "配电箱……为什么是开着的？",
     "video": {"first_frame_prompt": "林晚独自蹲在配电箱前，手机电筒照亮锁孔，低角度中景", "last_frame_prompt": "箱门完全打开，箱内纸张被风掀起", "video_prompt": "她伸手拉开箱门，手机光晃过箱内，镜头随之压低", "duration_sec": 5.0},
     "interaction": {"trigger_time_sec": 4.0, "default_next_node": "ch01_s04_key"}},
    {"node_id": "ch01_s04_key", "node_type": "item_discovery", "speaker": "林晚",
     "dialogue": "一把黄铜钥匙，压在电费单下面。",
     "video": {"first_frame_prompt": "配电箱半开，一枚黄铜钥匙压在电费单上，微距特写，暖黄光", "last_frame_prompt": "钥匙被拿走，箱内只剩一张纸", "video_prompt": "手指入画捏起钥匙，金属反光划过镜头", "duration_sec": 4.0},
     "interaction": {"trigger_time_sec": 2.8, "default_next_node": "ch01_s06_end_caught", "options": [{"option_id": "opt_take_key", "label": "拿走钥匙", "grant_items": ["item_brass_key"], "next_node": "ch01_s05_door"}]}},
    {"node_id": "ch01_s05_door", "node_type": "choice_branch", "speaker": "林晚",
     "dialogue": "开，还是不开？",
     "video": {"first_frame_prompt": "林晚站在磨砂玻璃门前，钥匙举到锁孔前，正面中景", "last_frame_prompt": "门被推开一条缝，暖光溢出照亮侧脸", "video_prompt": "钥匙插入、转动，门缝扩大，光从缝里溢出", "duration_sec": 5.0},
     "interaction": {"trigger_time_sec": 3.5, "timeout_sec": 5.0, "default_next_node": "ch01_s06_end_caught", "options": [{"option_id": "opt_unlock", "label": "用黄铜钥匙开门", "required_items": ["item_brass_key"], "next_node": "ch01_s07_end_escape"}]}},
    {"node_id": "ch01_s06_end_caught", "node_type": "ending", "speaker": "旁白",
     "dialogue": "监控画面定格在空无一人的走廊。",
     "video": {"first_frame_prompt": "保安室监控屏幕墙，画面定格在空走廊，冷蓝光", "last_frame_prompt": "屏幕逐个变黑", "video_prompt": "雪花闪动，屏幕从右到左逐个熄灭", "duration_sec": 4.0}},
    {"node_id": "ch01_s07_end_escape", "node_type": "ending", "speaker": "林晚",
     "dialogue": "天台上，风是暖的。",
     "video": {"first_frame_prompt": "天台上，林晚跨出门槛，夜风掀起衣角，城市灯海背景，广角", "last_frame_prompt": "林晚背影融入灯海，天空泛白", "video_prompt": "镜头跟随她走向栏杆，缓慢转向城市灯海", "duration_sec": 5.0}}
  ]
}
```
示例逻辑：`open → choice →(trust|doubt)→ key → door →(escape|caught)`；钥匙由 `opt_take_key` 发放、由 `opt_unlock` 消耗，两条结局都可达，无孤岛、无道具死锁。

## 8. 自检与交付
- 跑 `python3 scripts/validate_graph.py story/03_storyboards/chapter_01.json`（项目根目录执行）；建议加 `--strict`（WARN 也算失败）或 `--json`（结构化输出供管线用）。
- 当前校验项：顶层/节点字段、`node_type` 枚举、`video` 两段提示词、`ending` 不得有后续、非 `ending` 必须有 `interaction`、next 引用存在、`option_id` 节点内唯一、至少一个 `ending`、每个可达节点都能到结局、`required_items` 必须被可达节点的 `grant_items` 覆盖。
- 不可达孤岛（`W_ISLAND`）与"授予但未使用"的道具（`W_ITEM_UNUSED`）记 WARN，默认不阻断但应清零；`--strict` 下退出码 1。通过后再交总控，不要自行批量生图。
- 常犯错：结局节点漏写 `video`；`trigger_time_sec` 大于 `duration_sec`；选项指向拼错的 id；只写 `dialogue` 忘写 `video_prompt`。
