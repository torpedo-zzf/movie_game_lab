# 第一章《猫眼之后》资产生产计划（T-013a 预检）

> 状态：**只读预检**。本任务未生成任何图片/视频，未调用 ComfyUI `/prompt`，未修改 `story/`、`scripts/`、`schema/`、`state/task_board.json`。
>
> 输入：`story/03_storyboards/chapter_01.json`；严格校验通过：**12 节点 / 2 选择 / 2 结局 / 91.0 秒**。
>
> 目标：27 张 480p / 16:9 帧（3 张角色锚定 + 24 张首尾帧）+ 12 条 480p / 16:9 MiniMax H3 视频。
>
> 结构化预估：`state/cost_estimate_chapter_01.json`（`images` / `videos` / `unknowns` / `requires_user_approval`）。

## 0. 结论摘要

| 项目 | 预检结论 |
|---|---|
| 本地图像模型 | **有**：Qwen-Image 2.1（int8）+ Qwen3.5 9B t2i/i2i 文本编码器 + Qwen VAE；M5 Pro / 48GB / MPS 可承载 |
| 27 张能否本地生成 | **有条件可行**：模型与节点齐全，但项目内没有 Qwen API 工作流、没有图片批处理脚本；需先试产 1 张锚定验证工作流 |
| 本地图像缺口 | 无 SDXL/Flux 本地 checkpoint；IPAdapter/ControlNet/InstantID/PuLID 权重为空；无 `imagegen` CLI；无 2512 模型/Lightning LoRA |
| 视频节点 | `ComfyCloudMiniMaxH3FirstLastFrameToVideoNode` 已注册；480p / 16:9 / 7–8s 输入合法 |
| 视频计费 | `object_info` 有可读元数据：**USD 0.001295 / GPU-second（约 0.27 credits / GPU-second）**；按 GPU 秒计费，不按输出秒 |
| 视频总成本 | **GPU 秒/条待实测**，不能直接用 91 秒换算；规划区间见第 5 节，必须用户确认后才能 `/prompt` |
| 需要用户确认 | **是**：本地 27 张排期、云端图像替代（如需要）、1 条 H3 校准、12 条正式批量、任何 720p/重跑 |

## 1. 定稿基线

严格校验命令与结果：

```text
python3 scripts/validate_graph.py story/03_storyboards/chapter_01.json --strict
节点数: 12 | 结局数: 2 | 可达节点: 12
[OK] 校验通过：12 个节点，2 个结局。
exit=0
```

| # | node_id | 类型 | 时长 | 主要画面 | 帧 |
|---|---|---|---:|---|---:|
| 1 | `ch01_s01_voiceover` | video_play | 7s | 沈砚玄关，夜班配音结束 | 2 |
| 2 | `ch01_s02_peephole` | video_play | 8s | 猫眼鱼眼，周启明拖地毯 | 2 |
| 3 | `ch01_s03_knock` | choice_branch | 8s | 周启明敲门借电话 | 2 |
| 4 | `ch01_s04_open` | video_play | 8s | 开门，地毯下手指 | 2 |
| 5 | `ch01_s05_listen` | video_play | 8s | 门内贴门录音，苏敏气音 | 2 |
| 6 | `ch01_s06_lock` | video_play | 7s | 反锁、门链、走廊空镜 | 2 |
| 7 | `ch01_s07_elevator` | video_play | 7s | 周启明挂“维修中”牌 | 2 |
| 8 | `ch01_s08_groupchat` | video_play | 7s | 业主群手机屏 + 沈砚抬头 | 2 |
| 9 | `ch01_s09_second_knock` | video_play | 8s | 周启明二次敲门，钥匙串 | 2 |
| 10 | `ch01_s10_choice` | choice_branch | 8s | 警灯扫过猫眼，最终抉择 | 2 |
| 11 | `ch01_s11_end_testify` | ending | 7s | 开门作证，担架与猫眼贴纸 | 2 |
| 12 | `ch01_s12_end_silence` | ending | 8s | 删录音，次日警戒线 | 2 |
| | **合计** | **2 选择 / 2 结局** | **91.0s** | **12 节点 × 2 帧 = 24 帧** | **24** |

加 3 张角色锚定：`shen_yan`、`zhou_qiming`、`su_min_partial`，合计 **27 张**。陈警官只闻其声，不生成形象。

尺寸口径：

- 交付/H3 输入：**854×480**（标准 480p 16:9，PNG）。
- 本地生成：**1024×576**（16:9，长宽均为 32 的倍数，适配 Qwen 的 32 对齐要求），再以 lanczos 缩到 854×480。
- 锚定图保留 1024×576 母版用于参考，另导出 854×480 计入 27 张交付；母版放 `_master/`，不额外计数。
- 视频输出像素以 Comfy Cloud 返回为准；历史本地 H3 768P 输出为 1344×768，480p 16:9 需首条实测确认。

## 2. 本地图像生成能力

### 2.1 硬件与模型（只读探测）

- 机器：**Apple M5 Pro / 48GB 统一内存 / macOS 27.0.1**。
- ComfyUI：`http://127.0.0.1:8188`，版本 **0.46.1**，设备 `mps`，`vram_total` 48GB，预检时空闲约 24GB。
- 共享模型目录：`/Users/yul/ComfyUI-Shared/models/`（ComfyUI 通过共享路径加载）。

| 文件 | 体积 | 用途 | 状态 |
|---|---:|---|---|
| `diffusion_models/qwen_image_2.1_int8_convrot.safetensors` | 6.8G | Qwen-Image 2.1 扩散模型 | 已有 |
| `text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors` | 8.8G | 2.1 文生图文本/视觉编码器 | 已有 |
| `text_encoders/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` | 8.8G | 2.1 图生图/参考编辑编码器 | 已有 |
| `vae/qwen_image_2.1_vae_bf16.safetensors` | 644M | Qwen-Image 2.1 VAE | 已有 |
| `checkpoints/stable-audio-open-1.0.safetensors` | 4.5G | 音频模型 | 已有，但**不是图像 checkpoint** |

关键结论：

- `CheckpointLoaderSimple` 的 `ckpt_name` 只有 `stable-audio-open-1.0.safetensors`；**没有 SDXL / SD1.5 / Flux 本地 checkpoint**。
- `UNETLoader` 的 `unet_name` 有 `qwen_image_2.1_int8_convrot.safetensors` 等；`VAELoader` 有 `qwen_image_2.1_vae_bf16.safetensors`。
- 本地图像主路径是 **Qwen-Image 2.1**，不是 Flux；`Flux2/Flux3` 相关节点多为 Comfy Cloud / API 节点，本地无对应权重。
- IPAdapter / ControlNet / InstantID / PuLID 模型目录为空；`clip_vision` 只有 `dino_v3_L_naf_fp32.safetensors`，但没有可用的 IPAdapter 权重，不能按“已有 IPAdapter”估算。
- `loras` 只有 `YFG-Daak-v1e16.safetensors`、`lora.safetensors`，未确认与 Qwen-Image 2.1 兼容；**不要假设有 4-step Lightning 加速**。

### 2.2 已注册的本地生图节点

`/object_info` 共 1701 个节点类；与本计划相关的均已注册：

- 加载：`UNETLoader`、`CLIPLoader`、`VAELoader`。
- 编码：`CLIPTextEncode`、`TextEncodeQwenImage21`、`TextEncodeQwenImageEditPlus`、`QwenImage21Cache`。
- 采样/解码：`KSampler`、`ModelSamplingAuraFlow`、`VAEDecode`、`EmptySD3LatentImage`。
- 图像：`LoadImage`、`ImageScale`、`SaveImage`。
- 参考图：`TextEncodeQwenImage21` 的 `images` 输入支持参考图，并由 VAE 编码为 reference latents；`TextEncodeQwenImageEditPlus` 支持 image1/2/3。

`QwenImageTextToImageApi`、`Flux2ImageNode` 等是云端 API 节点，**不是本地模型**。

### 2.3 本地可行性判断

**有条件可行**，但不是“打开就能批”：

1. Qwen-Image 2.1 模型、t2i/i2i 编码器、VAE、采样与保存节点齐全；模型加载约 6.9GB + 8.9GB + 0.64GB ≈ 16.5GB，48GB 内存可承载。
2. 项目内**没有** Qwen-Image 2.1 的 API 格式工作流 JSON；需要先在 ComfyUI UI 搭通并导出（建议 `comfyui/qwen_image_2_1_api.json`，目录尚未创建）。
3. **没有图片批处理脚本**；`scripts/batch_minimax_h3.py` 只覆盖视频。27 张需要 UI 逐张或后续新增图片批处理（不在本次任务范围）。
4. 没有 `imagegen` CLI；本地 ComfyUI 是替代路径，但不提供一键参数模板。
5. 没有 IPAdapter/ControlNet/InstantID 权重；角色一致性主要依赖 Qwen 参考图 + 锚定图 + 固定角色块/prompt，需试产验证。
6. 没有 Qwen-Image 2.1 Lightning LoRA；不能按 4 步出图估算时间。蓝图里的 2512 模型、qwen2.5-vl-7b 编码器、2512 Lightning LoRA 本机都没有，**不要直接套用 2512 蓝图**。

建议先做 **1 张沈砚锚定试产**，验证模型加载、16:9 构图、脸部/疤/耳机/白漆点、参考图链路；通过后再生成 27 张。试产也应在成本闸门内（本地无现金费用，但需确认排期与验收标准）。

**若换机/重装，安装项如下：**

1. 将 `qwen_image_2.1_int8_convrot.safetensors` 放入 `models/diffusion_models/`。
2. 将 `qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors` 与 `..._pe_i2i...` 放入 `models/text_encoders/`。
3. 将 `qwen_image_2.1_vae_bf16.safetensors` 放入 `models/vae/`。
4. 重启 ComfyUI，确认 `/models/diffusion_models`、`/models/text_encoders`、`/models/vae` 能看到文件，且 `/object_info` 中 `UNETLoader`/`CLIPLoader`/`VAELoader` 可选到它们。
5. 无需额外安装自定义节点；本机 ComfyUI 0.46.1 已注册 `TextEncodeQwenImage21`、`EmptySD3LatentImage`、`KSampler` 等。
6. 工作流本身不是下载项：在 UI 搭通后 **Export (API)**，建议存 `comfyui/qwen_image_2_1_api.json`（目录尚未创建）。
7. IPAdapter/ControlNet/InstantID/PuLID 权重不是基线必需；本机对应目录为空，且与 Qwen 2.1 的兼容性未验证，不建议盲装。加速 LoRA 同理。
8. `imagegen` CLI 不是本地 ComfyUI 路径的必需项；图片批处理脚本仍需后续任务单，不在本次交付范围。

### 2.4 推荐工作流

**A. 角色锚定（纯文生图）**

```text
UNETLoader(qwen_image_2.1_int8_convrot, default)
CLIPLoader(qwen3vl_8b_int8_convrot, type=qwen_image)   # 主图像文本编码器
VAELoader(qwen_image_2.1_vae_bf16)
TextEncodeQwenImage21(clip, 正向：角色描述块 + 中性灰背景 + 正面半身, 负向：固定负面词, resolution=1024, vae)
EmptyLatentImage(1024, 576, 1)
# 可选：ModelSamplingAuraFlow(3.1)；2.1 自带 shift=0.69，先不带 patch 试产对比
KSampler(seed=锚定 seed, steps=36, cfg=1.0, sampler=euler, scheduler=simple, denoise=1.0)
VAEDecode -> ImageScale(854x480, lanczos) -> SaveImage
```

> 2026-11-21 实测更正：`qwen3.5_9b_qwen_image_2.1_pe_t2i` 是提示词增强器（TextGenerate）的编码器，
> 不是图像条件编码器；误用会输出纯噪声。官方 t2i 主编码器是 `qwen3vl_8b`，`cfg=1.0`；
> 本机 36 steps / 130–135 秒一张已验证。详见 `docs/anchor_generation_chapter_01.md`。

**B. 分镜帧（锚定图参考 + 文本）**

```text
TextEncodeQwenImage21(
  clip=qwen3vl_8b_int8_convrot,
  vae=qwen_image_2.1_vae_bf16,
  prompt=角色描述块 + 本镜场景/景别/光位 + 首帧或末帧状态,
  negative_prompt=固定负面词,
  resolution=768,          # 16:9 参考图 -> 约 1024x576 的 latent
  images=[角色锚定图]      # 可选再加同场景上一帧
)
-> positive / negative / latent
-> KSampler(seed=锚定 seed 或固定偏移, steps=36, cfg=1.0, euler, simple)
-> VAEDecode -> ImageScale(854x480) -> SaveImage
```

说明：

- `resolution=768` 是按“面积 768²、保持参考图 16:9、对齐 32 像素”推算的约 1024×576；以实际节点输出为准。
- Qwen-Image 2.1 官方 t2i 模板使用 `EmptyLatentImage`（16 通道）配 `KSampler`；本机 1024×576 实测可用。若参考图链路报 shape 错误，改用 `TextEncodeQwenImage21` 输出的 latent。
- Qwen 2.1 自带 `sampling_settings.shift=0.69`；`ModelSamplingAuraFlow(3.1)` 来自 2512 蓝图，**不是 2.1 的已确认配置**，只作为 A/B 试产项。
- 末帧应优先以本镜首帧为参考，再描述末态；这样比“只换文字”更容易保持机位与光位。
- 角色一致性优先靠**参考图 + 角色块逐字复用 + 固定 seed**；一次只改一个变量（seed / 参考强度 / prompt）。没有 IPAdapter 权重，不要假装有。
- `s08_groupchat` 的屏幕文字是高风险项：建议生成“无文字手机界面底板”，文字用后期/播放器叠字；否则固定负面词里的“文字”会和剧情需求冲突。

### 2.5 27 张本地耗时估算

同一台 M5 Pro 的 ComfyUI 日志中，Qwen-Image 2.1 的单次 `Prompt executed` 记录为：

| 依据 | 单张耗时 | 27 张线性外推 | +20% 重试 |
|---|---:|---:|---:|
| **本机实测（1024×576 / 36 steps / cfg 1.0）** | **130–135s** | **58.5–60.8 分钟** | **70.2–72.9 分钟** |
| 近期单次日志 | 102.53s | 46.1 分钟 | 55.4 分钟 |
| 历史中负载 | 248.06–254.76s | 111.6–114.6 分钟 | 134.0–137.6 分钟 |
| 历史高负载 | 431.66–454s | 194.3–204.3 分钟 | 233.1–245.2 分钟 |

口径与限制：

- 以上是 **MPS 执行墙钟时间**，不是云端 GPU 秒；不含人工抽检、修图、重绘迭代。
- 日志未记录当时的分辨率/步数；单次执行还包含模型加载。同进程连续生成时后续可能更快；本机锚定实测 3 张稳定在 130–135 秒/张。
- 本地现金成本：**0 USD**；电费、机器折旧、人工时间未计入。
- 规划时建议按 **1.5–4 小时**留出 27 张 + 抽检 + 2 轮局部重跑的窗口；实测锚定后可按 70–90 分钟（含重试）估计纯生成。

### 2.6 云端图像替代（仅作对比，未使用）

`/object_info` 的 `price_badge` 可读，但均为近似价，且未验证 480p/16:9 与账户额度：

| 云端选项 | 单价（object_info） | 27 张 | +20% 重试（33 张） | 备注 |
|---|---:|---:|---:|---|
| Qwen-Image 3.0 API（`QwenImageTextToImageApi`，非 pro） | $0.0429/张 | $1.1583 | $1.4157 | 需确认 model/size 支持 16:9；鉴权/额度未验证 |
| Flux.2 API（`Flux2ImageNode`，≤1MP，无参考图） | $0.03/张起 | $0.81 | $0.99 | 参考图/超过 1MP 另计，角色参考可能到 $0.045–$0.15/张 |
| Comfy Cloud Flux2（`ComfyCloudFlux2TextToImageNode`） | $0.001295/GPU-second | 待核实 | 待核实 | 与 H3 同样按 GPU 秒，需实测 |

## 3. 资产命名与批次顺序

### 3.1 命名

| 资产 | 路径 |
|---|---|
| 角色锚定 | `assets/frames/anchors/shen_yan_anchor.png`、`zhou_qiming_anchor.png`、`su_min_partial_anchor.png` |
| 节点首帧 | `assets/frames/chapter_01/<node_id>_first.png` |
| 节点末帧 | `assets/frames/chapter_01/<node_id>_last.png` |
| 视频 | `assets/videos/<node_id>.mp4` |
| 母版/弃稿 | `assets/frames/chapter_01/_master/`、`_wip/` |

规则：PNG；`node_id` 与 JSON 逐字一致；不覆盖已验收帧；回填路径前确认文件真实可读。

### 3.2 批次顺序（硬顺序）

1. **3 张锚定**：沈砚 → 周启明 → 苏敏局部。
2. **锚定抽检**：脸型/疤/痣/发型/服装/标志物；苏敏只看右手+右眼局部，不生成全脸。通过后才进入下一步。
3. **24 张首尾帧**：按“角色/场景分组”跑，减少模型重复加载与 prompt 切换；建议顺序：
   - 沈砚玄关组：`s01`、`s05`、`s06`、`s10`、`s12`；
   - 猫眼/门外组：`s02`、`s03`、`s04`、`s09`、`s11`；
   - 走廊/电梯/手机组：`s07`、`s08`。
   - 每组内先首帧后末帧；末帧参考本镜首帧。
4. **24 帧抽检**：逐节点 16:9、构图安全区、无文字/水印、手部/鱼眼、角色一致性；再按分支路径检查“上一镜末帧 → 下一镜首帧”的机位/光位衔接。
5. **12 条视频**：只在 27 张全部验收后开始；每条用 `first_frame` + `last_frame` + `video_prompt` + `seed` + 480p/16:9 + 对应整数时长。

任一步抽检不通过：只重跑该帧/该条，不上移；不合格资产放 `_wip/`，不覆盖已验收文件。

## 4. 12 条视频：输入与用量口径

节点：`ComfyCloudMiniMaxH3FirstLastFrameToVideoNode`（`api_node=true`，Comfy Cloud GPU）。

| 输入 | 类型/取值 | 本片用法 |
|---|---|---|
| `first_frame` | IMAGE（必填） | 854×480 首帧 |
| `last_frame` | IMAGE（可选） | 854×480 末帧；12 条均提供 |
| `prompt` | STRING | 章节 `video.video_prompt`，不改写 |
| `seed` | INT | 每节点固定；重跑换 seed 属新成本 |
| `aspect_ratio` | COMBO | `16:9` |
| `resolution` | COMBO | `480p` |
| `duration_seconds` | INT 5–15 | 章节 7/8 秒取整；H3 会量化到 17 帧@24fps，实际时长可能小幅浮动 |
| 输出 | VIDEO | 含匹配音轨；具体像素以云端返回为准 |

用量口径：

- **12 条**；请求总时长 **91.0 秒**（7+8×…，见第 1 节表）。
- 计费单位是 **GPU-second**，不是输出视频秒。不要用 91 秒 × 单价直接报总价。
- 可读计费元数据（`GET /object_info/ComfyCloudMiniMaxH3FirstLastFrameToVideoNode`）：
  - `price_badge.expr`：`{"type":"usd","usd":0.001295,"format":{"suffix":"/GPU-second","approximate":true}}`
  - 节点描述：`$0.001295/GPU-second (0.27 credits)`，约 **0.273 credits / GPU-second**。
  - 源码注释给出 **211 credits/USD**；object_info 只给 USD/GPU-second 与“0.27 credits”描述。
- 需要有效 Comfy Cloud 账户/额度/鉴权；本次没有调用 `/prompt`，鉴权与额度**未验证**。
- 失败重试预算：按 20% 条数预留（12 × 20% → 3 条）；任何重跑/补片/换分辨率都重新确认。

### 4.1 成本敏感性（不是报价）

| 假设 GPU 秒/条 | 12 条总 GPU 秒 | 基础 USD | 基础 credits | +20% 重试 USD | +20% 重试 credits |
|---:|---:|---:|---:|---:|---:|
| 20s | 240 | $0.3108 | 65.52 | $0.3730 | 78.62 |
| 30s | 360 | $0.4662 | 98.28 | $0.5594 | 117.94 |
| 40s | 480 | $0.6216 | 131.04 | $0.7459 | 157.25 |
| 60s | 720 | $0.9324 | 196.56 | $1.1189 | 235.87 |

历史参考（**不是 Comfy Cloud GPU 秒**）：

- 本机 `MiniMaxH3FirstLastFrameNode` 768P：
  - 4.458s 成片，端到端约 34.76s；
  - 5.167s 成片，端到端约 36.86s。
- 端到端约为输出时长的 **7.1–7.8 倍**；480p 理论上低于 768P，但未实测。
- 若按输出秒的 7–8 倍做规划：12 条约 637–728 GPU-s → 基础 **$0.82–$0.94 / 174–199 credits**；加 20% 重试约 **$0.99–$1.13 / 209–239 credits**。
- 该区间只用于预算沟通；**首条 480p 校准后以实际账单/日志回填**。

## 5. 成本汇总

| 项目 | 数量/口径 | 本地现金 | 云端参考 | 状态 |
|---|---|---:|---:|---|
| 角色锚定 | 3 张 | $0 + 时间 | $0.13（Qwen API） | 先试产 1 张 |
| 首尾帧 | 24 张 | $0 + 时间 | $1.03（Qwen API） | 锚定通过后 |
| 图片合计 | 27 张 | **$0 + 55–245 分钟**（含 20% 重试，历史外推） | **$1.16（无重试）/ $1.42（含重试）** | 本地优先；工作流待验证 |
| 视频校准 | 1 条（建议 7s） | — | 实际 GPU 秒 × $0.001295 | **需单独确认** |
| 视频正式 | 12 条 / 91s / 480p | — | **规划 $0.99–$1.13 / 209–239 credits**（7–8× 代理 + 20% 重试） | 校准后回填；非报价 |
| 720p/重跑 | 任意 | — | 重新出单 | 需重新确认 |

若本地图片链路失败，改用云端图片时，图片成本按上表另加；不要把云端图片价格隐式计入“视频预算”。

## 6. 风险与回滚

| 风险 | 触发 | 预防/处理 | 回滚 |
|---|---|---|---|
| 角色漂移 | 脸型、左眉尾疤、左眼下痣、耳机、白漆点、钥匙串不一致 | 锚定图 + 角色块逐字复用 + 固定 seed；按角色分组抽检；一次只改一个变量 | 单帧重跑；旧帧保留 `_wip/`；不覆盖已验收 |
| 首尾帧不衔接 | 末帧机位/光位与下一镜首帧跳变 | 末帧以首帧为参考；先检查“末帧→下一首帧”再出视频 | 只重跑末帧或下一首帧；必要时换构图，不硬剪 |
| 手部/鱼眼/手机 UI 崩坏 | s04 手指、s09 钥匙、s02/s03/s09 鱼眼、s08 屏幕文字 | 手部特写单独抽检；鱼眼强化提示词；屏幕文字后期叠字 | 单帧重跑；屏幕改为无字底板 |
| H3 失败/超时/400 | 上传失败、鉴权/额度、首尾帧不匹配、时长越界 | 先校准 1 条；检查帧可读、7/8s 在 5–15 内；记录 prompt_id/seed | 不无限重试；同节点最多 2 次；重跑前重新确认成本 |
| 预算超 10% | 实际 GPU 秒/重试超预估 | 每批记录用量；超 10% 停止 | 重新出单，未确认不继续 |
| 本地 OOM/模型不兼容 | Qwen 2.1 工作流报错、加载失败 | 先 1 张试产；使用 Qwen21Cache/低显存设置；不混用 2512 模型 | 回退到云端图片（需新确认） |
| 误覆盖资产 | 重跑写同名文件 | 先写 `_wip/`，验收后替换；保留母版 | 从 `_wip/`/母版恢复；不要删已验收帧 |
| 云端价格变动 | price_badge 为 approximate | 以 Comfy Cloud 控制台账单为准；出单时注明时间 | 重新核算；不沿用旧报价 |

## 7. 需要用户确认的事项

在以下各项获得**明确肯定答复**前，不调用 ComfyUI `/prompt`，也不“先跑一条试试”：

1. **本地 27 张排期**：接受 55–245 分钟（含 20% 重试，历史外推；本地现金 0），并接受先试产 1 张锚定。
2. **本地工作流验收标准**：3 张锚定通过后，才生成 24 张；`s08` 屏幕文字改为后期叠字/无字底板。
3. **云端图片替代（仅当本地失败时）**：选择 Qwen-Image 3.0 API（约 $1.16/27 张，重试约 $1.42）或 Flux.2（约 $0.81 起，参考图另计），确认预算与 16:9 参数。
4. **H3 1 条校准**：建议用最短 7s 镜头、480p/16:9，实际 GPU 秒与费用按云端账单；这是付费提交，需单独确认。
5. **H3 正式 12 条 + 20% 重试**：校准后回填实际单价/GPU 秒；按当前代理区间约 $0.99–$1.13 / 209–239 credits（含重试），最终以校准单为准。
6. **任何 720p、补片、换分辨率、超出 10% 的重跑**：重新出《视频成本预估单》并重新确认。

确认记录应写入 `state/task_board.json` 的 `approvals`，包含时间、用户回复摘要、预估量、实际提交量；本任务不修改看板。

## 8. 本次只读证据

- `GET /system_stats`：ComfyUI 0.46.1，`mps`，48GB，空闲约 24GB。
- `GET /object_info`：1701 个节点类；`UNETLoader`/`CLIPLoader`/`VAELoader`/`KSampler`/`TextEncodeQwenImage21` 等已注册。
- `GET /models/*`：Qwen-Image 2.1 系列文件存在；`checkpoints` 仅音频模型；`ipadapter`/`controlnet`/`instantid`/`pulid` 为空。
- `GET /history?max_items=20`：4 条 H3 记录，2 条成功、2 条鉴权失败；成功记录为 768P，输出 4.458s/5.167s。
- `python3 scripts/validate_graph.py ... --strict`：12 节点 / 2 结局 / 91.0s，退出 0。
- 本任务执行期间：`/prompt` 调用 0 次；生成图片 0 张；生成视频 0 条；未修改 `story/`、`scripts/`、`schema/`、`state/task_board.json`。
