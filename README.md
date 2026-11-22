# 互动影游项目脚手架 (DeepSeek Harness + Agy + Codex)

**在线试玩：<https://torpedo-zzf.github.io/movie_game_lab/>**（GitHub Pages，手机/桌面均可）

本仓库是互动影游（FMV）的最小工程脚手架：剧情图 → 结构/连通性/道具校验 → 首尾帧与 MiniMax H3 视频生产 → 播放器联调。工程脚本只依赖 Python 标准库，不需要 `pip install`。

## 目录说明

- `AGENTS.md`：三方（DeepSeek Harness / Agy / Codex）协作分工、流水线与成本确认硬规则。
- `.agents/skills/`：4 个项目专属 Skill（`harness-fmv-director`、`fmv-branch-schema`、`imagegen-character-anchor`、`comfyui-minimax-h3-pipeline`）。
- `schema/story_graph.schema.json`：剧情分支节点 JSON 规范（字段的唯一准绳）。
- `scripts/check_env.py`：环境自检；输出检查表并写入 `state/env_report.json`。
- `scripts/validate_graph.py`：剧情图结构、连通性、结局可达性与道具闭环校验。
- `scripts/test_validate_graph.py`：校验器单元测试（unittest + tempfile）。
- `scripts/batch_minimax_h3.py`：对接本地 ComfyUI API，批量调度 MiniMax H3；内置成本确认闸门。
- `state/task_board.json`：全局任务阶段进度、任务与 `approvals` 审批记录看板。
- `install_skills.sh`：尝试安装社区基础 Skill（可选，见“降级说明”）。
- `assets/frames/`、`assets/videos/`：首尾帧与视频产物目录（仅 `.gitkeep` 入库）。

## 当前可玩 Demo（第一章）

第一章《猫眼之后》12 个节点、2 个选择点、2 个结局已全部成片，含 TTS 配音、音效与 BGM。

```bash
# 仓库根目录
python3 -m http.server 8123
# 浏览器打开 http://127.0.0.1:8123/player/
```

- 播放器：`player/`（纯静态、零依赖），默认每条播完再切；`?advance=trigger` 按分镜时间切镜。
- 剧情图：`story/03_storyboards/chapter_01.json`；音频设计：`story/04_audio/audio_design_chapter_01.json`。
- 交付报告：`docs/video_batch_report_ch01.md`、`docs/audio_report_ch01.md`、`docs/player_report_ch01.md`。
- 重建音轨：`python3 scripts/build_audio_chapter_01.py`（原始视频在 `assets/videos/raw/`）。

## 快速开始

以下命令均在项目根目录执行（`/Users/yul/work/games/movie_game_lab`）。

### 1. 环境自检

```bash
python3 scripts/check_env.py
```

检查 Python（>=3.9）、ffmpeg/ffprobe、node/npm、ComfyUI 可达性、MiniMax H3 节点注册、`imagegen` CLI。

- 默认读取 `COMFYUI_URL`，未设置时用 `http://127.0.0.1:8188`；可这样覆盖：
  ```bash
  COMFYUI_URL=http://127.0.0.1:8188 python3 scripts/check_env.py
  ```
- 人类可读检查表之外，会写入机器可读的 `state/env_report.json`（含 `timestamp`、`checks`、`ok`、`summary`）。该文件已被 `.gitignore` 忽略。
- 退出码：Python / ffmpeg / ffprobe 等必需项失败返回 `1`；ComfyUI 不可达、H3 节点缺失、`imagegen` 缺失只记 `WARN`，不改变退出码。

### 2. 校验剧情图

```bash
python3 scripts/validate_graph.py story/03_storyboards/chapter_01.json
```

校验内容：

- 顶层 `chapter_id` / `title` / `start_node` / `nodes`，节点 `node_id` 唯一、`node_type` 合法；
- 非 `ending` 节点必须有 `interaction`；`ending` 节点不得配置后续；
- `default_next_node` 与所有 `options[].next_node` 必须存在；`option_id` 在同节点内唯一；
- `video.first_frame_prompt` 与 `video.video_prompt` 非空；
- 从 `start_node` 可达所有节点（不可达孤岛记 `WARN`）；
- 至少一个 `ending`，且每个可达节点都能到达某个结局（检测死胡同/无出口环）；
- 道具闭环：所有 `required_items` 必须被可达节点的 `grant_items` 覆盖；未被使用的道具记 `WARN`。

退出码：有 `ERROR` 返回 `1`；只有 `WARN` 默认返回 `0`。进入批量生产前建议使用 `--strict`，把孤岛/未使用道具也视为失败：

```bash
python3 scripts/validate_graph.py story/03_storyboards/chapter_01.json --strict
```

管线调用可加 `--json`，只输出结构化结果：

```bash
python3 scripts/validate_graph.py story/03_storyboards/chapter_01.json --json
```

### 3. 运行单元测试

```bash
python3 -m unittest scripts/test_validate_graph.py -v
```

覆盖合法图通过、指向不存在节点、缺道具、孤岛 WARN、无结局、死胡同环 6 类场景。

### 4. 导出 ComfyUI API 工作流

1. 在 `http://127.0.0.1:8188` 搭通 MiniMax H3 首尾帧工作流，并确认生成节点为 `ComfyCloudMiniMaxH3FirstLastFrameToVideoNode`。
2. 从菜单 **Workflow → Export (API)** 导出扁平 API JSON；旧版界面需先开启 Dev mode，再使用 **Save (API Format)**。
3. 不要把 UI 保存的 workflow 直接喂给脚本；脚本需要的是 `{"<node_id>": {"class_type": "...", "inputs": {...}}}` 结构。
4. 建议放在 `comfyui/minimax_h3_api.json`（本机路径，不入库亦可），并核对 `prompt`、`resolution`、`duration_seconds` 等输入键名。
5. `python3 scripts/check_env.py` 只做只读探测，不会排队生成。

### 5. 成本确认闸门与批量生视频

**每次提交（含重跑、补片、换分辨率）前，必须先出《视频成本预估单》并获得用户明确确认。** 脚本从机制上强制这一点：

```bash
# 只出预估单：扫描待生成节点，不提交、不写审批记录
python3 scripts/batch_minimax_h3.py \
  story/03_storyboards/chapter_01.json \
  comfyui/minimax_h3_api.json \
  --dry-run \
  --cost-per-sec 1.5 \
  --task-id T-014

# 交互确认：打印预估单后，必须输入 CONFIRM 才提交
python3 scripts/batch_minimax_h3.py \
  story/03_storyboards/chapter_01.json \
  comfyui/minimax_h3_api.json \
  --cost-per-sec 1.5 \
  --task-id T-014

# 总控已转述用户并拿到明确确认后，才可用 --yes 跳过交互
python3 scripts/batch_minimax_h3.py ... --yes --cost-per-sec 1.5
```

闸门行为：

- 预估单包含：节点清单、单条时长、分辨率分布、总条数、总时长、计费口径、基础预估、失败重试预算、预计总成本上限。
- `--cost-per-sec` 是每秒单价（默认单位“积分”）；**不知道单价时不要传**，预估单会写“待核实”，不会编造金额。
- `--retry-rate` 默认 `0.2`（20% 重试预算），只用于预估上限；任何重跑本身仍需重新确认。实际用量超过基础预估 10% 时也必须重新确认。
- 默认安全：非交互环境且没有 `--yes` 时，只打印预估单并拒绝提交（退出码 `2`）。
- 已有可读 `video_path` 的节点会自动跳过。重跑、补片或换分辨率前，先清理对应 `video_path` 或视频文件，让脚本重新识别为待生成；再次运行仍会重新出单并要求确认。
- 常用参数：`--resolution 480p|720p` 覆盖分辨率，`--default-duration <秒>` 兜底缺失时长，`--retry-rate <0-1>` 调整重试预算，`--task-id T-014` 关联看板任务，`--approval-id` 自定义审批号。
- 确认后先把审批记录写入 `state/task_board.json` 的 `approvals`，写入失败则拒绝提交；随后才逐条调用 `/prompt`。
- 脚本只回填 `assets/videos/<node_id>.mp4` 路径，**不下载/搬运视频**；请确认文件已归档，并用 `ffprobe` 验证可读。

`approvals` 记录约定（脚本按 `approval_id` 读-合并-原子替换，保留看板其他字段）：

```json
{
  "approval_id": "APR-20261121T223000+0800-a1b2c3",
  "task_id": "T-014",
  "stage": "批量生视频",
  "kind": "minimax_h3_video_batch",
  "status": "submitting | completed | partial | failed",
  "requested_at": "2026-11-21T22:30:00+08:00",
  "confirmed_at": "2026-11-21T22:31:00+08:00",
  "confirmed_by": "interactive:CONFIRM | cli:--yes",
  "user_reply": "确认生成（CONFIRM）",
  "chapter_file": "story/03_storyboards/chapter_01.json",
  "workflow_file": "comfyui/minimax_h3_api.json",
  "estimated": {
    "resolution": "480p",
    "resolutions": {"480p": 6},
    "nodes": 6,
    "node_ids": ["ch01_s01_open"],
    "total_duration_sec": 28.0,
    "unit_price": 1.5,
    "cost_unit": "积分",
    "estimated_cost": 42.0,
    "retry_budget": 2,
    "retry_budget_sec": 5.6,
    "retry_budget_cost": 8.4,
    "total_cost_cap": 50.4
  },
  "submitted": {"nodes": 0, "total_duration_sec": 0.0, "cost": 0.0},
  "actual": {"nodes": 0, "total_duration_sec": 0.0, "cost": 0.0},
  "failed_nodes": []
}
```

单价未知时，`unit_price` / `estimated_cost` / `retry_budget_cost` / `total_cost_cap` 写 `"待核实"`。`status` 在提交前为 `submitting`，结束后为 `completed` / `partial` / `failed`。看板本体由总控维护；脚本只在确认提交后追加/更新对应审批记录。重跑请让脚本自动生成新的 `approval_id`，不要复用旧审批号覆盖历史记录。

## 降级说明

### `install_skills.sh` 在受限 npm 沙箱下可能失败

脚本通过 `npx skills add ...` 拉取社区 Skill，需要 npm 注册表网络与可写缓存。受限沙箱可能出现 `EPERM` / 网络拒绝，这是环境限制，不是仓库损坏。

- 失败时不影响 `check_env.py`、`validate_graph.py`、单元测试与 ComfyUI 管线；项目所需的 4 个专属 Skill 已放在 `.agents/skills/`。
- 如需社区 Skill，可在有网络与写权限的终端重试，或按团队流程手动放置 Skill 目录。
- 不要为了安装 Skill 放宽高权限、修改系统 npm 配置；先与总控确认。

### `imagegen` 缺失时如何降级

`check_env.py` 找不到 `imagegen` 时只记 `WARN`，不影响剧本校验和视频阶段的技术联通。可选用以下路径：

1. **手动准备首尾帧**：按 `assets/frames/<chapter_id>/<node_id>_first.png`、`_last.png` 命名放入图片，并在章节 JSON 的 `video.first_frame_path` / `last_frame_path` 回填真实路径。
2. **用 ComfyUI 生首尾帧**：在 ComfyUI 中完成角色锚定与首尾帧工作流，导出图片后再进入 H3 首尾帧视频工作流；仍受“先校验、后成本确认”的约束。
3. **安装本地 CLI**：安装后重跑 `python3 scripts/check_env.py`，确认该项变为 `[通过]` 再纳入批量流程。

没有末帧时，不要把首帧复制成末帧硬凑（画面会接近静止）；应先补生末帧，或确认 H3 模板支持仅首帧模式后再用。

## 产物与忽略规则

- `assets/frames/`、`assets/videos/` 下除 `.gitkeep` 外的图片/视频不入库。
- `.gitignore` 已忽略 `__pycache__`、`.DS_Store`、`.venv`、`node_modules`、日志、临时文件与 `state/env_report.json`。
- 生成产物应归档到 `assets/`，章节 JSON 只保存相对路径；提交前用 `ffprobe` 验证文件真实可读。
- 不要 `git commit` 未确认的媒体产物；成本确认与用量记录以 `state/task_board.json` 的 `approvals` 为准。

## 发布到 GitHub Pages

站点只包含播放器、章节 JSON、12 条成片和 24 张首末帧（约 30MB），原始备份/音频工程不入库。

```bash
python3 scripts/build_pages.py          # 生成 dist/
# 首次：GitHub 仓库 Settings -> Pages -> Source: Deploy from a branch -> gh-pages / (root)
# 之后重新发布：把 dist/ 推到 gh-pages
rm -rf /tmp/pages-repo && cp -R dist /tmp/pages-repo
cd /tmp/pages-repo && git init -b gh-pages && git add -A \
  && git commit -m "site: update" \
  && git remote add origin https://github.com/torpedo-zzf/movie_game_lab.git \
  && git push -f origin gh-pages
```

线上地址：<https://torpedo-zzf.github.io/movie_game_lab/>（入口自动跳转 `/player/`）。
