# 《猫眼之后》互动播放器（T-015）

纯静态、零依赖、零构建的 FMV 播放器，把 `chapter_01` 从 `ch01_s01_voiceover` 跑到两个结局：

- **结局 A · 交出录音**：`ch01_s10_choice` 选择「开门，把录音交给警察」→ `ch01_s11_end_testify`
- **结局 B · 删掉录音**：选择「关灯，删掉录音，装作睡着」或超时 → `ch01_s12_end_silence`

## 1. 启动

在**仓库根目录**起一个静态服务（任意端口，下面以 8123 为例）：

```bash
cd /Users/yul/work/games/movie_game_lab
python3 -m http.server 8123
```

浏览器打开：

```text
http://127.0.0.1:8123/player/
```

> 规格里的 `python3 -m http.server 8000` 同样可用，换成 `http://127.0.0.1:8000/player/` 即可。
>
> `file://` 直接双击 `index.html` 会降级：浏览器禁止 fetch 本地章节 JSON，页面会显示启动 `http.server` 的指引。

## 2. 文件

| 文件 | 作用 |
| --- | --- |
| `player/index.html` | 页面骨架：开始屏、画幅、字幕、选择卡、结局卡、道具 HUD、调试面板、错误屏 |
| `player/player.css` | 影院暗色视觉、16:9 letterbox、字幕/选项/结局样式、390×844 移动端断点 |
| `player/player.js` | 章节加载、状态机、视频切换与预加载、分支/超时、道具、缺失兜底、调试面板 |
| `player/selftest.mjs` | 零依赖静态自检：剧情图引用、可达性、资产文件、HTML/JS 引用、可选 ffprobe |
| `player/README.md` | 本文件 |

播放器只读以下数据，不写 `story/`、`schema/`、`state/`、`assets/`：

- `../story/03_storyboards/chapter_01.json`
- `../assets/videos/<video_path>`
- `../assets/frames/chapter_01/<node_id>_first.png`（视频缺失时的占位图）

## 3. 操作

| 输入 | 行为 |
| --- | --- |
| 点击「开始播放」 | 解锁音频并进入 `start_node`（浏览器自动播放策略要求一次用户手势） |
| 鼠标 / 触屏点选项 | 选中后 120ms 反馈再切镜 |
| 数字键 `1`–`9` | 选择对应选项（第一章为 `1` / `2`） |
| `~`（反引号 `` ` `` 同上） | 打开 / 关闭调试面板 |
| `Esc` | 关闭调试面板 |
| `Space` | 视频缺失、处于首帧占位时「跳过等待」 |

右上角是道具 HUD：`grant_items` 入包，`required_items` 不满足时选项置灰并显示「缺少：xxx」。第一章没有道具，HUD 显示「空」。

## 4. 状态机与流程

```text
loading → playing → choosing → transitioning → ended
```

- `loading`：拉章节 JSON、预检视频。fetch 失败显示错误屏，不静默。
- `playing`：播放当前节点，字幕淡入（`speaker` + `dialogue`），底部安全区显示。
- `choosing`：到达 `choice_branch` 的 `trigger_time_sec` 弹选项，环形倒计时按 `timeout_sec` 走；最后 1 秒脉冲；超时走 `default_next_node` 并记录 `timeout`。
- `transitioning`：销毁旧 `<video>`，创建新 `<video>`；预加载下一节点，120ms 交叉淡入（旧帧保留，不黑屏）。选项确认有 120ms 反馈，超时默认有 160ms 反馈。
- `ended`：`ending` 节点视频播完后显示结局卡（结局标题、路径摘要、重玩、回到第一个选择）。
- 非法迁移只 `console.warn` 并忽略，不改变当前状态。
- `video.ended` 一律走 `default_next_node`；`choice_branch` 未选择时同样走默认。
- 路径以 `node_id` 列表记录，选择/超时会写入对应选项标签，结局卡可展开查看。

### 4.1 切镜模式：`ended`（默认）与 `trigger`

规格 3.3/3.4 要求非选择节点「播完再走 `default_next_node`」，而验收 6.1 写了「s01 播放至 6.0s 自动进入 s02」。两者冲突：

- 默认 `ended`：每个镜头完整播放，**保留 s02 贴猫眼、s04 地毯下手指等末帧揭示**；s01 实际 7.3s 播完进 s02。
- `?advance=trigger`：非选择节点到达 `trigger_time_sec` 即切镜，可复现验收 6.1 的 6.0s；代价是砍掉每条片子最后约 1.3s，可能看不到关键末帧。
- 调试面板的「切镜模式」按钮可随时切换；`window.__mvPlayer.setAdvanceMode('trigger'|'ended')` 亦可。

选择节点不受该模式影响：永远在 `trigger_time_sec` 弹选项。

## 5. 视频缺失兜底

1. 载入章节后用 `HEAD` 预检每条 `video_path`；`?missing=` 可强制模拟缺失。
2. 缺失 / 404 / 解码失败 / 6s 内未就绪：显示该节点 `first_frame_path` + 左上角「视频生成中」角标 + 「首帧占位，流程可继续」。
3. 用 `video.duration_sec` 合成时间轴继续跑：到 `trigger_time_sec` 照样弹选项、倒计时、超时走默认；片尾照样推进/进结局。
4. `Space` 或「跳过等待」可直接推进；缺失节点同样可被调试面板跳转。
5. 若视频在播放中途失效，保留当前播放进度切换到首帧兜底，不退出流程。

手动复现：

```text
http://127.0.0.1:8123/player/?missing=ch01_s01_voiceover,ch01_s02_peephole
http://127.0.0.1:8123/player/?missing=all
```

## 6. 已知处理

- **s08 群聊叠层（2026-11-23 成片质检补充）**：`ch01_s08_groupchat` 的 0–3s 是 AI 生成的手机聊天特写，屏幕文字是乱码。播放器在该节点叠加真实 HTML 群聊 UI：群名「7楼业主群」、发送者「周启明」、消息「704 好像出事，已经报警」、时间 23:47。**仅 0–3s 显示，3s 后 350ms 淡出**；位置在画面右侧下三分之一，字幕在画幅下方独立栏，不遮挡字幕。其他节点不叠加。
- **字幕不压在画面上**：画幅用 16:9 letterbox，字幕放在画幅下方的独立栏，避免遮挡人物面部；移动端竖屏同样如此。
- **选择时台词可读**：全屏 scrim 会压暗底部字幕，因此选择卡内同步显示当前 `speaker` + `dialogue`。
- **开始屏必须点一次**：解决浏览器带声音自动播放限制；后续切镜由同一用户手势链解锁。
- **预加载**：进入节点后对默认下一节点 / 两个选项目标设置 `preload="auto"` 的隐藏 `<video>`，切镜用 120ms 交叉淡入。
- **HEAD 预检**：本地 `python3 -m http.server` 支持 HEAD；若服务器返回 405/501 或网络异常，会回退到 `<video>` 的 `error` 事件判定，不误判为缺失。
- **QTE / item_discovery**：第一章未使用。`qte_event` 若配置了选项，按选择节点处理；`item_discovery` 可通过选项的 `grant_items` 发道具；额外兼容可选的节点级 `grant_items`。
- **道具文案**：`item_*` id 有内置中文映射（黄铜钥匙、录音、手机等），未知 id 自动去掉 `item_` 前缀显示。

## 7. 调试

按 `~` 打开左侧调试面板：

- 当前状态 / 节点 / 类型 / 播放计时 / `trigger_time_sec` 与 `timeout_sec` / 切镜模式 / 道具 / 路径长度；
- 12 个节点一键跳转（带 ✓ / 缺 / ? 视频可用性标记）；
- 「切镜模式」「重置到 s01」「清空道具」；
- 已走路径列表。

只读调试 API（自动化验收用）：

```js
window.__mvPlayer.state          // loading | playing | choosing | transitioning | ended
window.__mvPlayer.node           // 当前 node_id
window.__mvPlayer.path           // 已走 node_id 数组
window.__mvPlayer.items          // 道具 id 数组
window.__mvPlayer.advanceMode    // ended | trigger
window.__mvPlayer.jumpTo('ch01_s10_choice')
window.__mvPlayer.setAdvanceMode('trigger')
```

URL 参数：

| 参数 | 说明 |
| --- | --- |
| `?advance=trigger` | 非选择节点到 `trigger_time_sec` 即切镜（验收 6.1 字面行为） |
| `?advance=ended` | 显式指定播完再切（默认） |
| `?missing=id1,id2` | 强制这些节点走首帧占位 |
| `?missing=all` | 全部节点走首帧占位 |

## 8. 自检

```bash
node --check player/player.js
node player/selftest.mjs
```

`selftest.mjs` 会检查：12 节点 / 2 选择点 / 2 结局、所有 `next_node` 存在、全节点可达且都能到结局、12 条视频与 12 张首帧存在、`player/` 文件齐全、HTML/JS id 对齐、无 CDN 依赖；本机有 `ffprobe` 时还会核对 h264+aac / 832×480 / 时长。

## 9. 已知限制 / 待真人验收

- **待用户试玩**：实际观感、音量、字幕节奏、选项是否遮挡关键动作，需要真人在桌面与手机上过一遍；本地已用 headless Chromium 跑通主路径、双结局、超时、缺失兜底与 390×844 布局。
- **未在真机 iOS Safari / Android Chrome 验证**：已做 `playsinline`、`100dvh`、`env(safe-area-inset-*)` 兼容，但仍建议手机实测。
- **s08 视频本身的乱码文字仍在画面里**：HTML 群聊叠层是「补信息」而非擦除原画面；最终修法仍是 V2 重拍（见 `docs/video_batch_report_ch01.md`）。
- **默认 `ended` 模式与验收 6.1 的 6.0s 字面值不一致**：见 4.1；`?advance=trigger` 可切换。需要导演确认哪个是最终节奏。
- **无持久化**：刷新即重开；未做 localStorage 存档、字幕开关、暂停/全屏控件（规格未要求）。
- **「回到第一个选择」会清空道具**：第一章无道具，无影响；后续章节若有前置道具，需要在回退时重放路径上的 `grant_items`。
- **未做音频淡入淡出**：切镜为硬切 + 120ms 画面淡入，音频随 `<video>` 直接切换。
