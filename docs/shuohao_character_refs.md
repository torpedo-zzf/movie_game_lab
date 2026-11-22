# 周启明角色参考图优化（shuohao character-refs）

> 日期：2026-11-21 → 2026-11-22
> 触发：用户否决 16:9 锚点 v1，要求 **Codex 与 Agy 使用 shuohao-skill 优化**。
> 状态：**四视图完成，`check` exit 0，用户已确认锚点**；24 张首尾帧未开始。
> 费用：**$0**（本机 ComfyUI Qwen Image 2.1 / MPS，无云端调用）。

## 1. 采用的 skill

- 仓库：`vendor/shuohao-skills`（`eternityspring/shuohao-skills`，commit `8af10e0`，本地克隆，已加入 `.gitignore`）
- 使用 skill：**`skills/character-refs`**（shuohao 里唯一真出角色参考图的 skill）
- 规则：一组图只有一个根——**正面全身锚点**；其余视图只参考这张锚点。锚点未确认，派生图会被拒绝。
- 与旧 16:9 锚点的区别：这是 **2:3 / 4:5 / 白底**的角色参考图，不是最终分镜帧；适合给 H3 当参考图。

## 2. 分工

### Agy — 角色卡 intake

- 产出：`state/character_refs/zhou_qiming-intake.json`
- 依据：`story/01_bible/02_characters.md` 第 3 节 + 世界观年代。
- 关键补全：185cm / 85kg / 肩宽背厚、方脸宽下颌、左眼下 2mm 痣、灰黑 6mm 寸头、青灰胡茬、深蓝厚棉工装夹克（胸袋、左袖口磨白）、灰 polo、黑直筒裤、棕色工装靴、右胯七把黄铜钥匙、右手虎口 3cm 旧烫伤疤、左手无名指旧戒痕。
- 标记：`face` 眼型/唇形、`skin` 肤质、`backCue`、polo 领口状态标 `inferred`；其余 `stated`。
- `intake-check`：通过。

### Codex — 本地出图

- 配置：`character-refs config --model qwen --qwen-url http://127.0.0.1:8188 --confirm-anchor yes`
- 画风：`--look 写实`（`realistic-photo`）
- 资产：`assets/frames/character_refs/周启明/asset.json`
- 参数：Qwen Image 2.1（`qwen_image_2.1_int8_convrot` + `qwen3vl_8b` + `qwen_image_2.1_vae_bf16`），seed `20261124`，20 steps / cfg 2.5 / shift 3.1
- 报告：`assets/frames/character_refs/character-refs.html`

## 3. 四视图

| 视图 | 路径（相对 `assets/frames/character_refs/周启明/`） | 尺寸 | 耗时 | prompt_id |
|---|---|---:|---:|---|
| 正面全身（锚点） | `default/front-full.v1.png` | 1056×1584 | 349s | `50e8067f-3b0c-45c0-84ad-8715eb575a68` |
| 正脸大头照 | `default/face-front.v1.png` | 1376×1728 | ~22 min | `a0d8daa9-bec7-4d97-8a7d-3da77680ca4c` |
| 侧面 90°（面朝右） | `default/side-full.v1.png` | 832×1248 | 592s | `ef30bc9f-f929-48a8-b185-54047fde3348` |
| 背面 | `default/back-full.v1.png` | 832×1248 | 311s | `aacf175c-7304-4b7f-a6a3-483b6b1718b9` |

`check`：四视图全部 ✓，exit 0。

## 4. 自检与残留

相符：

- 42 岁中年感、185cm/85kg 的宽肩厚背粗脖；
- 方脸宽下颌、浓眉、眉间深竖纹、左眼下小黑痣（画面右）；
- 灰黑 6mm 寸头、发际线后移、青灰胡茬；
- 深蓝工装夹克两个胸袋 + 灰 polo（领口松一颗扣）、黑直筒裤 + 皮腰带 + 棕色工装靴；
- 正面/侧面/背面白底、无文字水印；
- 背面：寸头后脑、粗脖、夹克后背、右胯黄铜钥匙串（约 5 把）；
- 左手无名指旧戒痕在锚点可见。

残留偏差：

1. **磨白袖口左右不一致**：锚点与背面在人物**右**袖；侧面在近侧（人物**左**袖）；圣经要求左袖口。整套图与圣经仍不一致。
2. **虎口疤偏新伤**：锚点呈红色微凸，不像「多年愈合、平整略浅」；派生图不露手，未继承。
3. **钥匙约 4–5 把**：不是 7 把；侧面未出现钥匙。
4. 提示词内部有冲突：画风层固定 `empty hands, no props`，反向词又含 `props`，与腰间钥匙相抵。
5. 大头照脸型比锚点略窄，但五官组合可认。

> 用户已在 2026-11-21 明确选择「1：用这张作锚点」，以上偏差按接受处理；若后续需要严格贴合圣经，再出锚点 v2。

## 5. MPS 兼容补丁（vendor，仅本地）

ComfyUI 在本机以 `--gpu-only` 运行，`TextEncodeQwenImageEditPlus` 会把参考图缩到 384² 预览，`common_upscale(..., "area")` 走 MPS 的 adaptive pool，要求尺寸整除，派生图必挂。直接换 `TextEncodeQwenImage21` 后又踩了两个坑：

- 用 `qwen3.5_9b...pe_i2i` 当 CLIP、用 `EmptySD3LatentImage`（16 通道）当采样 latent → 纯噪声；
- Qwen 2.1 原生编辑节点输出的是 **64 通道 latent**，必须把 `KSampler.latent_image` 接到 `TextEncodeQwenImage21` 的第三路输出。

最终对 `vendor/shuohao-skills/skills/character-refs/scripts/models.mjs` 的 `qwenWorkflow` 派生分支做了 6 处本地补丁：

1. `TextEncodeQwenImageEditPlus` → `TextEncodeQwenImage21`；
2. CLIP 用主编码器 `qwen3vl_8b_int8_convrot`，不用 pe_i2i；
3. 参考图走扁平键 `images.image_N`（autogrow 在 API 里不是嵌套对象）；
4. `KSampler.latent_image = ['pos', 2]`，删 `EmptySD3LatentImage` 与独立 `neg`；
5. 4:5 先把锚点顶部裁 1056×1320 作参考；2:3 用完整锚点；
6. `qwenGenerate` 轮询上限 15 → 20 分钟。

锚点文生图路径、输出尺寸常量、seed、提示词模板均未动。64 通道计算慢：1376×1728 约 64–70 秒/步，832×1248 约 25–30 秒/步。

## 6. 下一步

1. 把 `front-full.v1.png` 作为周启明**唯一角色锚点**；旧 `assets/frames/anchors/zhou_qiming_anchor.png` 降为备选/对比图。
2. 用四视图给 H3 做参考，按「角色/场景分组」生成 24 张 16:9 首尾帧；首帧优先参考锚点，末帧参考本镜首帧。
3. 24 帧全部验收后，再执行已批准的 T-014a（H3 1 条 7s 480p 校准）。
4. 若要把袖口/疤/钥匙修到严格贴合圣经，出锚点 v2（约 6 分钟），派生图会全部标过期。

## 7. 复现命令

```bash
cd vendor/shuohao-skills/skills/character-refs
node scripts/character-refs.mjs config --model qwen \
  --qwen-url http://127.0.0.1:8188 --confirm-anchor yes --show
node scripts/character-refs.mjs intake-check ../../../state/character_refs/zhou_qiming-intake.json
node scripts/character-refs.mjs new ../../../state/character_refs/zhou_qiming-intake.json \
  --out ../../../assets/frames/character_refs --look 写实
node scripts/character-refs.mjs gen "../../../assets/frames/character_refs/周启明/asset.json" --seed 20261124
node scripts/character-refs.mjs check "../../../assets/frames/character_refs/周启明/asset.json"
node scripts/character-refs.mjs render "../../../assets/frames/character_refs/周启明/asset.json" \
  --out ../../../assets/frames/character_refs/character-refs.html
```

## 8. 沈砚 / 苏敏四视图（2026-11-22）

在周启明之后，同一套 `character-refs` + 本机 Qwen 2.1 补齐了沈砚、苏敏。`check` 均 exit 0。

| 角色 | 锚点 seed | 锚点 | 大头照 | 侧面 | 背面 |
|---|---:|---:|---:|---:|---:|
| 沈砚 | 20261121 | 353s | 250s | 323s | 242s |
| 苏敏 | 20261123 | 358s | 254s | 245s | 241s |

路径：`assets/frames/character_refs/沈砚/default/`、`assets/frames/character_refs/苏敏/default/`；联系表 `assets/frames/character_refs/contact_sheet.png`。

已知偏差：

- **沈砚**：正面锚点有银色监听耳机挂脖，但大头照/侧面/背面没有把耳机画出来；帽兜在锚点与派生图之间也有「立起/放下」的差异。耳机是标志物，四视图一致性不完整。
- **苏敏**：四视图全脸/全身只是内部一致性参考；成片仍按圣经只取右手、右眼与部分黑发。全脸观感偏 38–40 岁（设定 31），泪痣/三珠手链/右食指咬痕在对应视图可见。
- **周启明**：沿用第 4 节的袖口/旧疤/钥匙偏差。

若要严格一致：可只重出沈砚的 face/side/back（约 15 分钟，加强「silver headphones hanging around his neck, clearly visible」），苏敏可重出 face（约 5 分钟，脸更年轻）。不影响已完成的 24 帧。
