---
name: imagegen-character-anchor
description: 用于互动影游中生成角色锚定图与每个分镜的首尾帧。当需要建立角色 Bible、固定角色外观、编写中英双语生图提示词、沿用种子与参考图、按 assets/frames 规范落盘或验收跨镜一致性时使用。该 Skill 也说明本地 imagegen CLI 缺失时改用 ComfyUI 的降级路径。
---

# 角色一致性锚定（imagegen-character-anchor）

## 0. 适用与现状
当 Agy 要写角色设定、为 `chapter_XX.json` 的每个节点产出首/末帧、或 Codex 要批量生图后做一致性验收时使用。
**现状**：本机未发现本地 `imagegen` CLI（`command -v imagegen` 无输出，`task_board.environment.imagegen_cli = false`）。因此：
- 主路径（`imagegen` 命令与参数）**待核实/占位**，不要凭记忆编造参数。
- 降级路径：本机 ComfyUI（`127.0.0.1:8188`，已探活）跑 txt2img / img2img 工作流；节点 ID 与模型名以本机实际工作流为准，**待核实**。
- 生图若产生云端费用，同样受成本确认闸门约束（见 `comfyui-minimax-h3-pipeline` 第 1 节）。

## 1. 角色 Bible 必备字段
写在 `story/01_bible/02_characters.md`，每个角色一节，字段不可缺：

| 字段 | 内容要求 |
|---|---|
| `character_id` | 英文小写，如 `lin_wan`，用于资产与提示词引用 |
| 姓名/代号 | 中文名 + 英文拼写，台词称呼统一 |
| 年龄/体型 | 具体数字（28 岁、170cm、偏瘦），不要"年轻" |
| 面部锚点 | 脸型、眉眼、鼻、唇、肤色、痣/疤（3–5 个可辨识特征） |
| 发型/发色 | 长度、分缝、扎法、色号（如 `#2B1B17` 深栗） |
| 服装 | 分内/外/鞋/配饰，材质（呢料、尼龙）、颜色 hex、磨损细节 |
| 色彩方案 | 主色 2 + 辅色 1 + 点缀 1，附 hex；与场景色温的关系 |
| 标志物 | 必须反复出现的 1 件物件（工牌、黄铜钥匙、旧打火机） |
| 表情/体态基线 | 惯用表情、站姿、手部习惯（如总捏工牌角） |
| 禁止漂移项 | 眼镜有无、刘海方向、左右手伤疤、外套扣法 |
| 锚定资产 | `assets/frames/anchors/<character_id>_anchor.png`，以及 seed/工作流记录 |

## 2. 锚定图生成流程（6 步）
1. 写完 Bible，冻结"角色描述块"（80–120 字，中文一段、英文一段，逐字复用）。
2. 生成正面半身锚定图：纯灰/中性背景、均匀布光、中性表情，先不管场景。
3. 同一角色再出 3/4 侧与全身各 1 张，确认脸、发型、服装在换角度后仍一致。
4. 选定 1 张作为**唯一锚定图**，记录 seed、模型/工作流、参考强度到 Bible 表格。
5. 逐节点生成首帧：锚定图作参考 + 角色描述块 + 该镜场景/景别/光位；末帧同理并约束机位。
6. 全章抽检：把同角色所有帧拼看，检查脸型、发色、服装、标志物；不合格的只重跑该张。

## 3. 提示词模板（中英双语）
角色描述块（每镜逐字复用，只换 `{}` 内不换句式）：
```text
【角色块·中】{姓名}，{年龄}岁，{脸型与眉眼}，{发型发色}，穿{服装与材质}，主色{hex}/{hex}，随身{标志物}。
【角色块·英】{name}, {age}, {face features}, {hair}, wearing {outfit with material}, palette {hex}/{hex}, carrying {signature prop}.
```
首帧（正面锚定图）：
```text
中：角色锚定图，{角色块·中}，纯中性灰背景，正面半身，柔和均匀布光，写实电影质感，35mm，浅景深，无文字无水印。
英：character reference sheet, {角色块·英}, plain neutral grey backdrop, front-facing half body, soft even lighting, cinematic photorealism, 35mm, shallow depth of field, no text, no watermark.
```
分镜首帧：
```text
中：{角色块·中}，{景别}，{机位/角度}，位于{场景}，{时间与光源}，{构图留白}，16:9 电影静帧。
英：{角色块·英}, {shot size}, {camera angle}, in {location}, {time and key light}, {composition with negative space}, 16:9 cinematic still.
```
分镜末帧：在首帧模板后追加"与首帧同机位、同光位；画面状态为{末态}；为该镜的结束构图"。
负面词（固定一段，勿每镜改写）：`多余手指, 手部畸形, 双眼不对称, 文字, 水印, logo, 过饱和, 塑料皮肤, 双人重复, 服装不一致, 现代电子设备乱入`。
生成参数（steps/cfg/采样器/参考强度）以本机工作流默认值为准，**待核实**后回填 Bible。

## 4. 资产命名与落盘路径
| 资产 | 路径 |
|---|---|
| 角色锚定图 | `assets/frames/anchors/<character_id>_anchor.png` |
| 节点首帧 | `assets/frames/<chapter_id>/<node_id>_first.png` |
| 节点末帧 | `assets/frames/<chapter_id>/<node_id>_last.png` |
| 分镜视频 | `assets/videos/<node_id>.mp4`（与 `batch_minimax_h3.py` 写回一致） |
| 弃稿/试稿 | `assets/frames/<chapter_id>/_wip/<node_id>_first_v2.png`（约定，待 Codex 确认） |

规则：`chapter_id` 必须逐字等于 JSON 顶层 `chapter_id`（如 `chapter_01`）；`node_id` 必须逐字等于 JSON；只用小写英文、数字、下划线；PNG 不转 JPG；覆盖前先确认该帧未被 `first_frame_path` 引用。

## 5. 种子与参考图复用策略
- 一角色一主 seed：锚定图 seed 写进 Bible；同角色派生镜头沿用同 seed 区间，场景变化优先改提示词而非 seed。
- 参考图优先级：角色锚定图 > 同角色上一镜首帧 > 同场景无人物空镜；不要拿别的角色当参考。
- 只在三种情况下换 seed：构图持续崩坏、参考图导致脸漂移、需要全新景别；换后记录原因。
- 一次只改一个变量：先 seed，再参考强度，再提示词；否则无法判断是哪项起效。
- 末帧不靠"视频最后一帧反推"生成（会累积漂移），除非明确降级并记录。

## 6. 降级路径：ComfyUI 生图
1. 启动 ComfyUI（本机已装 Comfy Desktop，API 默认 `http://127.0.0.1:8188`）；探活：`curl -s http://127.0.0.1:8188/system_stats`（若 404 说明版本接口不同，待核实）。
2. 在 UI 中搭好 txt2img 工作流，加载锚定图参考则用 img2img/reference 类节点（具体节点名依本机安装，待核实）。
3. 用 **Export (API)** 导出工作流 JSON（旧版需在设置开启 Dev mode 才有 Save (API Format)）。
4. 输出目录与命名以 ComfyUI 自身保存规则为准；生成后按第 4 节重命名并归档到 `assets/frames/`，不要直接引用 ComfyUI 临时输出路径。
5. 批量脚本当前只覆盖视频管线，**图片批量脚本待 Codex 提供（占位）**；未提供前逐张生成并登记。

## 7. 验收清单
- [ ] 同一角色跨镜：脸型、发色、刘海方向、服装、标志物一致；无"换脸/换衣"。
- [ ] 构图：16:9；主体不贴边；上方或下方留字幕/选项安全区；关键道具在画面内可辨。
- [ ] 分辨率：720p 终版 ≥ 1280×720；480p 草稿约 854×480（以 H3 节点实际输出为准）；同章内不混用（`sips -g pixelWidth -g pixelHeight <png>` 可查）。
- [ ] 画面干净：无文字、水印、logo、多余肢体、重复人物。
- [ ] 衔接：本镜末帧与下一镜首帧的机位、光位、服化能对得上，剪接不跳。
- [ ] 路径：文件名与 JSON `node_id` 一一对应，`first_frame_path`/`last_frame_path` 可被读取。
- [ ] 记录：seed、参考图、工作流版本已回填 Bible；弃稿在 `_wip/`。

## 8. 边界
- 只写 `story/` 与（经 Codex 执行的）`assets/frames/`；不改 `scripts/`、`schema/`、`player/`。
- 不擅自覆盖已验收帧；不虚构 `imagegen` 命令；不确定的参数标注"待核实"。
- 云端生图前先过成本闸门，未确认不批量提交。
