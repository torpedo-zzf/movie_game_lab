# 播放器交付与联调报告（T-015）

> 日期：2026-11-23
> 实现：Codex（纯静态、零依赖、零构建）
> 数据：`story/03_storyboards/chapter_01.json`；视频：`assets/videos/ch01_*.mp4`（12/12）

## 1. 交付物

| 文件 | 作用 |
|---|---|
| `player/index.html` | 开始屏、16:9 画幅、字幕栏、选择卡、结局卡、道具 HUD、错误屏、调试面板、s08 群聊叠层 |
| `player/player.css` | 影院暗色视觉、倒计时/选项/结局、120ms 切镜、390×844 竖屏底部抽屉 |
| `player/player.js` | 章节加载、状态机、视频预加载与切换、分支/超时、道具、缺失兜底、s08 叠层、调试 API |
| `player/README.md` | 启动、键位、状态机、切镜模式、兜底与已知限制 |
| `player/selftest.mjs` | 零依赖静态自检（剧情图引用/可达/资产/HTML↔JS id/可选 ffprobe） |

## 2. 启动

```bash
cd /Users/yul/work/games/movie_game_lab
python3 -m http.server 8123
# http://127.0.0.1:8123/player/
```

## 3. 验证结果

- `node --check player/player.js` → OK。
- `node player/selftest.mjs` → **PASS 13/13**：12 节点、2 选择点、4 选项、next_node 全部存在、12/12 可达、2 结局可达、12 条视频与首帧齐备、59 个 id 对齐、无 CDN、ffprobe 全部 h264+aac 832×480。
- 无头 Chromium 端到端 **53/53**：s01→s02→s03；s03 选开门→s04→s06，超时→s05→s06；s06→s10 连续；s10 选交录音→s11 结局 A，超时→s12 结局 B；重玩/回到第一个选择；`?advance=trigger` 下 s01 6.16s 切镜；`?missing=` 首帧兜底；s08 0–3s 群聊叠层；390×844 无横向溢出、选项 340×50 可点；`~` 调试面板可跳 12 节点。
- 正常路径 0 console error（唯一 error 来自故意 mock 的 404 兜底测试）。

## 4. 关键实现

- 状态机 `loading → playing → choosing → transitioning → ended`，非法迁移只告警。
- 选择节点在 `trigger_time_sec` 弹卡，环形倒计时按 `timeout_sec`，超时走 `default_next_node`。
- 预加载下一节点，新视频就绪后 120ms 交叉淡入，保留旧帧不黑屏。
- 视频缺失：HEAD 预检 + `error` 双保险，显示首帧 + 「视频生成中」，用分镜时长合成时间轴继续流程。
- s08 群聊叠层：0–3s 显示「7楼业主群 / 周启明 / 704 好像出事，已经报警 / 23:47」，3s 后 350ms 淡出，补足视频里的乱码文字。
- 道具闭环：`grant_items` 入包、`required_items` 置灰并显示「缺少：xxx」（本章无道具，合成章节 13/13 通过）。

## 5. 待决策

1. **默认切镜节奏**：当前默认 `ended`（每条完整播完，全章约 92.5s，保留片尾揭示）；`?advance=trigger` 按分镜 `trigger_time_sec` 切镜（全章约 84s，符合分镜节奏）。需要导演试玩后定默认值。
2. **是否补拍**：s08（手机乱码/内部硬切）、s07（电梯 7F 信息弱）、s01（影调与其余镜头不一致）。3 条约 180 credits ≈ $0.45，需要重新出单确认（AGENTS.md 第 3 节）。

## 6. 已知限制

- 未在真机 iOS Safari / Android Chrome 实测；已做 `playsinline`、`100dvh`、安全区适配。
- 音频、音量、字幕节奏需真人试玩确认；headless 测试静音。
- 无 localStorage 存档、暂停/全屏、字幕开关（规格未要求）。
- 「回到第一个选择」会清空道具（本章无影响）。
