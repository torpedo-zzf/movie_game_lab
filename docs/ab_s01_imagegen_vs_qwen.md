# s01 关键帧 A/B：Codex 内置 imagegen vs Qwen-Image 2.1

> 日期：2026-11-22
> 目的：验证「Codex 内置 imagegen 出关键帧，是否让 H3 视频效果更好」。
> 变量控制：同一个节点 `ch01_s01_voiceover`、同一段 H3 prompt、同一 MiniMax H3 直连 480p / 7s / adaptive。

## 1. 两组输入

| 组 | 首末帧来源 | 参考图 | 备注 |
|---|---|---|---|
| A · Qwen | `scripts/gen_frames.py`，Qwen-Image 2.1 ref 模式，16 步 | `shen_yan_anchor.png` | 已有 24 帧管线；首帧正面、末帧侧身贴门 |
| B · Codex | Codex 内置 `$imagegen`，16:9 提示，1672×941 后缩到 854×480 | 锚点 + 首帧（末帧生成时） | 图 1 角色锚点；末帧额外挂首帧保同房间同光位 |

Codex 版首末帧：`assets/frames/chapter_01/_ab_codex/`；OSS 前缀 `movie_game_lab/ab_codex/`。

## 2. 成本

| 项 | 值 |
|---|---|
| Codex 生图 | 2 张（订阅额度，约 2/25；token 33.8k + 18.5k） |
| H3 A 组（Qwen 帧） | 53.44 credits，task `2124521845248765952` |
| H3 B 组（Codex 帧） | 53.44 credits，task `2124525420619771904` |
| 合计 | **106.88 credits**；余额 11605 → 11498.12 |
| 重试 | 0 |

## 3. 抽帧对比

对比图：`assets/videos/ab_s01_compare.png`（上排 Qwen 版，下排 Codex 版；列 0.1s / 3.5s / 7.0s）。

- **Qwen 版**：首帧正常；3.5s 变成**背影沿走廊走**，不是“摘耳机/转头看门”；7s 回到门边但构图与首帧差异大。
- **Codex 版**：首帧正常；3.5s 是**侧身靠向门、手伸向门把**；7s 仍贴门、手在门把附近。中段伪影消失，动作连续。
- 画质取向：Codex 版更亮、更“商业人像”，背景杂物（挂钩、包、植物）更多；Qwen 版更暗、更干净、更接近夜戏电影感。

## 4. 结论

**B（Codex 关键帧）在动作连续性和末帧贴合上明显胜出；A（Qwen）在夜景干净度/电影感上更稳。**

原因不是 H3 变了，而是 B 的首末帧机位、房间、光位、动作幅度更接近，H3 不需要自己编“走廊背影”。这验证了「关键帧设计 > 单纯画质」的判断。

建议：

1. **s01 及类似“人物连续动作”镜头**：优先用 Codex imagegen 出首末帧（挂锚点 + 首帧参考），再进 H3；
2. **常规批量/需要 seed 复现/额度紧张**：继续 Qwen ref 模式；
3. **空镜/hero/复杂光位**：Codex imagegen；
4. 24 帧全用 Codex 仍受 Plus ~25 张额度限制，混合是默认；
5. 故事板：只把起/止帧喂 H3，中间姿态用于 prompt 或拆段，不要喂多格故事板。

## 5. 复现

```bash
# Codex 首帧
codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check \
  -i assets/frames/anchors/shen_yan_anchor.png - < prompt.txt
# 末帧额外挂首帧
# 上传 OSS（前缀 ab_codex）
python3 scripts/oss_upload.py <png> --prefix ab_codex --check
# H3 1 条
python3 scripts/minimax_h3_generate.py --approval-id <ID> \
  --node ch01_s01_voiceover \
  --first-key movie_game_lab/ab_codex/<first>.png \
  --last-key movie_game_lab/ab_codex/<last>.png \
  --resolution 480p --duration 7 \
  --out assets/videos/ab_codex_s01_480p.mp4 --confirm CONFIRM
```
