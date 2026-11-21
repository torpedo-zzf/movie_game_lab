# 第一章角色锚定图生产报告（T-013 锚定阶段）

> 日期：2026-11-21
> 授权：`APR-20261121-IMG-001`（本地 27 张，先试产锚定并停下抽检）
> 范围：3 张锚定；24 张首尾帧**未开始**；H3 视频**未提交**。
> 现金成本：**0 USD**（全部本机 ComfyUI / MPS）。

## 1. 交付物

| 角色 | 交付图（854×480） | 母版（1024×576） | seed |
|---|---|---|---|
| 沈砚 | `assets/frames/anchors/shen_yan_anchor.png` | `assets/frames/anchors/_master/shen_yan_anchor_1024x576.png` | 20261121 |
| 周启明 | `assets/frames/anchors/zhou_qiming_anchor.png` | `assets/frames/anchors/_master/zhou_qiming_anchor_1024x576.png` | 20261124 |
| 苏敏（局部） | `assets/frames/anchors/su_min_partial_anchor.png` | `assets/frames/anchors/_master/su_min_partial_anchor_1024x576.png` | 20261123 |

生成记录（prompt / 参数 / prompt_id / 耗时 / 尺寸）：`state/anchor_generation.json`。
管线脚本：`scripts/gen_anchors.py`（仅标准库，可 `--dry-run`，支持四角色键）。

## 2. 实际工作流

```text
UNETLoader(qwen_image_2.1_int8_convrot.safetensors, default)
CLIPLoader(qwen3vl_8b_int8_convrot.safetensors, type=qwen_image)   # 主图像文本编码器
VAELoader(qwen_image_2.1_vae_bf16.safetensors)
TextEncodeQwenImage21(clip, prompt, negative_prompt, resolution=1024, vae)
EmptyLatentImage(1024, 576, 1)
KSampler(seed, steps=36, cfg=1.0, euler, simple, denoise=1.0)
VAEDecode -> SaveImage -> 下载 -> sips 缩到 854×480
```

关键纠正：`qwen3.5_9b_qwen_image_2.1_pe_t2i` 是**提示词增强器（TextGenerate）**用的编码器，
不是图像条件编码器。误用它做 CLIP 会输出纯噪声（已归档 `_wip/shen_yan_anchor_v1_noise_*`）。
Qwen-Image 2.1 官方 t2i 使用 `qwen3vl_8b`，`cfg=1.0`；本机 36 steps 已够用。

## 3. 提交与耗时

| 次 | 角色 | seed | 结果 | 耗时 | 说明 |
|---:|---|---:|---|---:|---|
| 1 | 沈砚 | 20261121 | 废弃 | 125.3s | CLIP 选错，纯噪声 |
| 2 | 沈砚 | 20261121 | 废弃 | 135.3s | 白漆点跑到人物右胸（画面左） |
| 3 | 沈砚 | 20261121 | **采用** | 130.4s | 加“画面左/右”锚点后修正 |
| 4 | 周启明 | 20261122 | 废弃 | 135.2s | 用户否决：年龄感偏老、体型偏瘦、气质偏温和 |
| 5 | 周启明 | 20261124 | **采用 v2** | 140.3s | 改为 42 岁/185cm/85kg 厚实体格、半身、压低声量 |
| 6 | 苏敏 | 20261123 | **采用** | 135.2s | — |

采用 3 张合计约 405.9 秒（6.8 分钟）；含三次废弃的总墙钟约 15 分钟。
与预检的 55–245 分钟区间相比，模型常驻后单张稳定在 130–140 秒（1024×576 / 36 steps）。

## 4. 自检结论（待用户抽检）

| 项 | 沈砚 | 周启明 | 苏敏（局部） |
|---|---|---|---|
| 脸型/年龄 | 窄长脸、单眼皮，33 岁感 | 方脸宽下颌、肩宽背厚，42–45 岁感 | 不露全脸 |
| 关键锚点 | 左眉尾疤（画面右）可见 | 左眼下痣（画面右）可见；右手虎口疤（画面左）**不够清晰** | 右眼泪痣可见；食指第二指节咬痕可见 |
| 发型 | 黑色三七分，分缝画面左，长刘海画面左 | 灰黑 6mm 寸头、发际线后移 | 黑长直，发尾深棕 |
| 服装/标志物 | 深灰卫衣 + 白 T；耳机挂脖；左胸白漆点（画面右） | 深蓝厚工装夹克 + 灰 polo；双袖口卷起露磨白衬里；腰间黄铜钥匙串 | 米色针织袖口；三珠细银手链；短甲无甲油 |
| 16:9 / 干净度 | 854×480，无文字水印 | 854×480，无文字水印 | 854×480，无文字水印 |
| 备注 | 通过 | v2 通过方向；虎口疤弱，必要时单帧补拍 | 咬痕需放大才明显；不露全脸 |

## 5. 未做与下一步

- 未生成 24 张首尾帧；未回填 `chapter_01.json` 的帧路径。
- 未调用 ComfyUI `/prompt` 的任何云端视频节点；未产生云端费用。
- 下一步（需用户 A2 抽检通过）：以 3 张锚定为参考图，扩展 `TextEncodeQwenImage21` 的 `images` 输入，按“角色/场景分组”生成 24 张首尾帧；末帧参考本镜首帧。

## 6. 工具链备注

- 本会话尝试派发 `codex exec` 时，Codex CLI 在本机沙箱内报
  `failed to initialize in-process app-server client: Operation not permitted`，无法启动；
  为不阻塞已批准的锚定生产，由总控直接落地最小管线并完成生成。
- 后续若恢复 Codex 通道，`scripts/gen_anchors.py` 可直接复用，不需要重写工作流。
