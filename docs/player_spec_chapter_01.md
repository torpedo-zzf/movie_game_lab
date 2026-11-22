# 互动播放器联调规格（T-015 / chapter_01）

> 目标：打开 `player/index.html` 就能把《猫眼之后》第一章从头玩到两个结局。
> 技术约束：**纯静态、零依赖、零构建**；只读 `story/03_storyboards/chapter_01.json`。
> 资产：`assets/videos/<node_id>.mp4`（854×480 或 832×480，h264+aac）。

## 1. 运行方式

```bash
# 仓库根目录
python3 -m http.server 8000
# 浏览器打开 http://127.0.0.1:8000/player/
```

不允许依赖 npm / CDN / 框架；`file://` 直开可降级（fetch 失败时提示启动 http.server）。

## 2. 数据契约

- 章节文件：`../story/03_storyboards/chapter_01.json`（相对 `player/`）。
- 起始节点：`start_node`。
- 节点字段：`node_id`、`node_type`、`speaker`、`dialogue`、`video.video_path`、`interaction`。
- `node_type`：`video_play` / `choice_branch` / `item_discovery` / `qte_event` / `ending`。
- 选项字段：`option_id`、`label`、`next_node`、可选 `required_items` / `grant_items`。
- 缺失 `video_path` 或文件不存在：显示 `first_frame_path` 作为封面 + 「视频生成中」角标，仍可推进（供边生成边联调）。

## 3. 播放流程

1. 载入章节 → 从 `start_node` 开始。
2. 播放当前节点 `<video>`，同时显示 `speaker` + `dialogue` 字幕（淡入，底部安全区）。
3. `time.sec >= interaction.trigger_time_sec` 时：
   - `choice_branch`：弹出选项面板 + `timeout_sec` 倒计时环；超时自动走 `default_next_node`，并记录 `timeout`。
   - 其余类型：不打断，播完走 `default_next_node`。
4. `video.ended` → 跳 `default_next_node`（`choice_branch` 未选择时同样走默认）。
5. `ending`：视频播完显示结局卡（标题、路径摘要、重玩按钮、回到第一个选择）。
6. 切换节点时：销毁旧 video，构建新 video；预加载下一节点（`preload="auto"`），切镜不黑屏超过 150ms。

## 4. 交互细节

- 选项按钮：键盘 `1` / `2` 可选，鼠标/触屏可点；选中后 120ms 反馈再切镜。
- 倒计时：环形进度条 + 剩余秒数；最后 1 秒脉冲。
- 道具栏：右上角 HUD；`grant_items` 入包，`required_items` 不满足时选项置灰并显示「缺少：xxx」。第一章暂无道具，但要能跑通。
- 状态机：`loading → playing → choosing → transitioning → ended`，非法跳转忽略并打日志。
- 调试面板（`~` 键）：跳到任意节点、显示当前节点/已选路径/计时。
- 自动记录路径（node_id 列表），结局页展示。

## 5. 视觉

- 16:9 画幅居中，超出留黑；桌面 ≤1280px 宽，移动端竖屏 letterbox。
- 暗色影院风：近黑底 `#0b0d10`、暖白字幕、选中色偏青绿（呼应走廊应急灯）。
- 字幕：`PingFang SC / Noto Sans SC`，描边 + 半透明底，不遮挡人物面部。
- 禁止花哨转场；切镜用 80–150ms 淡入。

## 6. 验收清单

- [ ] `python3 -m http.server 8000` 后 `/player/` 可打开，控制台无报错。
- [ ] s01 播放至 6.0s 自动进入 s02；s02 结束后进入 s03。
- [ ] s03 在 4.0s 弹选项；4s 不选 → 自动 `opt_listen`（s05）；选「开门」→ s04。
- [ ] s04/s05 均能汇入 s06；s06→s07→s08→s09→s10 连续。
- [ ] s10 选「交录音」→ s11；超时/选「删录音」→ s12。
- [ ] 两个结局卡可重玩，重玩从 s01 开始且状态清零。
- [ ] 视频缺失时显示首帧占位且流程可走通。
- [ ] 手机尺寸（390×844）可点选项，字幕不溢出。

## 7. 交付物

```
player/index.html
player/player.css
player/player.js
player/README.md   # 启动方式、键位、已知问题
```

## 8. 禁止

- 不改 `story/`、`scripts/`、`schema/`、`state/`。
- 不引入第三方库、不做构建步骤、不联网。
- 不吞错误：视频 404 要在界面上提示，而不是静默黑屏。
