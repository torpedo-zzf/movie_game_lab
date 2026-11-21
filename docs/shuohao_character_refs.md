# 周启明角色参考图优化（shuohao character-refs）

> 日期：2026-11-21
> 触发：用户否决 16:9 锚点 v1（`assets/frames/anchors/zhou_qiming_anchor.png` 的上一版），要求 **Codex 与 Agy 使用 shuohao-skill 优化**。
> 状态：**候选锚点待用户确认**；未生成派生图，24 张首尾帧未开始。
> 费用：**$0**（本机 ComfyUI Qwen Image 2.1 / MPS）。

## 1. 采用的 skill

- 仓库：`vendor/shuohao-skills`（`eternityspring/shuohao-skills`，commit `8af10e0`，本地克隆，已加入 `.gitignore`）
- 使用 skill：**`skills/character-refs`**（shuohao 里唯一真出角色参考图的 skill）
- 关键规则：一组图只有一个根——**正面全身锚点**；其余视图只参考这张锚点。锚点未确认，派生图会被拒绝。
- 与项目原有 16:9 锚点的区别：这是一张 **2:3 / 1056×1584 / 白底**的角色参考图，不是最终分镜帧；适合给 H3 当参考图，也便于后续派生大头照、侧面、背面。

## 2. 分工

### Agy — 角色卡 intake

- 产出：`state/character_refs/zhou_qiming-intake.json`
- 依据：`story/01_bible/02_characters.md` 第 3 节 + 世界观年代。
- 关键补全：`185cm / 85kg / 肩宽背厚 / 脖子粗`、方脸宽下颌、左眼下 2mm 痣、灰黑 6mm 寸头、青灰胡茬、深蓝厚棉工装夹克（胸袋、左袖口磨白）、灰 polo、黑直筒裤、棕色工装靴、右胯七把黄铜钥匙、右手虎口 3cm 旧烫伤疤、左手无名指旧戒痕。
- 标记：`face` 的眼型/唇形、`skin` 的肤质、`backCue`、polo 领口状态标 `inferred`；其余标 `stated`。
- `intake-check`：通过。

### Codex — 本地出图

- 配置：`character-refs config --model qwen --qwen-url http://127.0.0.1:8188 --confirm-anchor yes`
- 画风：`--look 写实`（`realistic-photo`）
- 资产：`assets/frames/character_refs/周启明/asset.json`
- 锚点：`assets/frames/character_refs/周启明/default/front-full.v1.png`
- 参数：Qwen Image 2.1（`qwen_image_2.1_int8_convrot` + `qwen3vl_8b` + `qwen_image_2.1_vae_bf16`），seed `20261124`，20 steps / cfg 2.5 / shift 3.1，prompt_id `50e8067f-3b0c-45c0-84ad-8715eb575a68`
- 耗时：349 秒（约 5 分 49 秒）
- 检查门：`check` exit 0；1056×1584、2:3、四边近白、≤20MB。
- 报告：`assets/frames/character_refs/character-refs.html`

## 3. 自检结论

相符：

- 42 岁中年感、185cm/85kg 的宽肩厚背粗脖；
- 方脸宽下颌、浓眉、眉间深竖纹、左眼下小黑痣（画面右）；
- 灰黑 6mm 寸头、发际线后移、青灰胡茬；
- 深蓝工装夹克两个胸袋 + 灰 polo（领口松一颗扣）、黑直筒裤 + 皮腰带 + 棕色工装靴；
- 白底、无文字水印、正面全身含头脚留白、空手自然垂放；
- 左手无名指可见一圈发白旧戒痕。

偏差（锚点根图问题，派生图会继承）：

1. **磨白袖口在错的手**：磨白起毛出现在画面左＝人物**右**袖；圣经要求左袖口（画面右）。
2. **虎口疤偏新伤**：位置大致对，但呈红色微凸，不像「多年愈合、平整略浅」。
3. **钥匙约 4–5 把**：不是 7 把；成叠遮挡，数量不可读。
4. 提示词内部有冲突：画风层固定 `empty hands, no props`，反向词又含 `props`，与腰间钥匙相抵。

## 4. 下一步

1. 用户确认当前锚点（或要求 v2 修袖口/疤/钥匙）。
2. 确认后 Codex 执行：
   ```bash
   node vendor/shuohao-skills/skills/character-refs/scripts/character-refs.mjs confirm \
     "assets/frames/character_refs/周启明/asset.json"
   node vendor/shuohao-skills/skills/character-refs/scripts/character-refs.mjs gen \
     "assets/frames/character_refs/周启明/asset.json"
   ```
   生成 `face-front`、`side-full`、`back-full` 三张派生图。
3. 用这组参考图回做 16:9 定妆照/首尾帧；24 帧全部验收后再进入 T-014a H3 校准。

## 5. 复现命令

```bash
cd vendor/shuohao-skills/skills/character-refs
node scripts/character-refs.mjs config --model qwen \
  --qwen-url http://127.0.0.1:8188 --confirm-anchor yes --show
node scripts/character-refs.mjs intake-check ../../../state/character_refs/zhou_qiming-intake.json
node scripts/character-refs.mjs new ../../../state/character_refs/zhou_qiming-intake.json \
  --out ../../../assets/frames/character_refs --look 写实
node scripts/character-refs.mjs gen "../../../assets/frames/character_refs/周启明/asset.json" --seed 20261124
node scripts/character-refs.mjs check "../../../assets/frames/character_refs/周启明/asset.json"
```
