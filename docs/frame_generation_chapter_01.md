# 第一章 24 张首尾帧生产报告

> 日期：2026-11-22
> 范围：`story/03_storyboards/chapter_01.json` 的 12 节点 × 2 帧 = 24 张，854×480；已回填 `first_frame_path` / `last_frame_path`。
> 费用：**$0**（本机 ComfyUI Qwen Image 2.1 / MPS，无云端 / 无 H3）。

## 1. 结果

| 项目 | 结果 |
|---|---|
| 帧数 | **24 / 24**，`state/frame_generation.json` 全部 `status=ok` |
| 交付尺寸 | 854×480（母版：ref 帧 864×480；t2i 帧 1024×576） |
| 生成模式 | **20 帧角色参考模式** + **4 帧无人物 t2i**（s06 last / s07 last / s08 first / s12 last） |
| 参考图 | 沈砚旧 16:9 锚点、周启明 shuohao 锚点顶部 16:9 裁切、苏敏局部锚点 |
| 鱼眼 | s02 / s09 四帧加 `8mm fisheye, circular barrel distortion` |
| 校验 | `validate_graph.py --strict` exit 0；24 条路径存在、唯一、854×480 |
| 联系表 | `assets/frames/chapter_01/contact_sheet.png` |

## 2. 管线

- 角色帧（ref）：`TextEncodeQwenImage21`（`qwen3vl_8b`）挂 16:9 参考图，`resolution=640` → 864×480，`KSampler.latent_image=['pos',2]`（64 通道），**16 steps / cfg 2.5 / euler-simple / shift 3.1**。
- 无人物帧（t2i）：`TextEncodeQwenImage21` + `EmptyLatentImage 1024×576`，**30 steps / cfg 1.0**。
- 参考图上传走 ComfyUI `/upload/image`；输出下载后 sips 缩到 854×480。
- 每节点 seed = `20261122 + 节点序号×10 + frame(0/1)`；`--force` 重跑会先把旧图归档到 `_wip/`。
- 脚本：`scripts/gen_frames.py`；单帧 110–140 秒，24 帧约 45 分钟。

## 3. Prompt 规则

- 每帧 = 章节 `first_frame_prompt` / `last_frame_prompt` + 自动角色块 + 固定电影后缀。
- 角色块后追加左右映射：沈砚疤在画面右、白漆点在画面右；周启明痣在画面右、虎口疤在画面左、腰间钥匙；苏敏右眼泪痣/右食指咬痕/三珠手链。
- s02 / s09 追加鱼眼句；s04 last 单独 override 成「地毯边 + 一截手指，不出现完整女性」。
- 负面词固定：多余手指、手部畸形、文字、水印、logo、过饱和、塑料皮肤、双人重复、服装不一致、现代电子设备乱入、多余肢体。

## 4. 抽检与重拍

- 首轮 s01 first 出现「疤镜像到画面左、脸偏年轻、漆点大面积溅点」，已改规则重出。
- s02 first 首轮是普通走廊、非鱼眼，已加鱼眼句重出。
- s04 last 首轮泄出苏敏全脸与三人合影，已 override 成地毯手指特写重拍（第 2 版通过）。
- 其余 21 帧首轮通过。

## 5. 已知弱点（供用户抽检）

1. **s08 first**：主消息「704 好像出事，已经报警」渲染正确，但聊天界面其他小字是乱码；正式版建议后期叠字或换成无字底板。
2. **s11 first / last**：警灯、担架、周启明被按墙的叙事能读出来，但构图偏暗、警察数量/动作不够明确；s11 last 的猫眼贴纸是一枚大白圆点，形状偏大。
3. **s05 first / last**：手机录音界面不一定有可读 UI；若需要「录音中」状态，建议后期叠 UI。
4. **s12 first**：沈砚坐地、手机照亮下颌，氛围对；但脸与锚点略有差异。
5. 所有帧的脸部一致性别按角色逐帧拼看；目前沈砚/周启明主镜可认，远景与鱼眼帧略弱。

## 6. 回填与校验

- `chapter_01.json` 每个节点 `video.first_frame_path` / `last_frame_path` 已写为：
  `assets/frames/chapter_01/<node_id>_first.png` / `_last.png`
- 回填前后语义对比一致（只新增两字段 + 逗号），`validate_graph.py --strict` 通过。
- 24 条路径全部存在、唯一、854×480；无缺帧、无重复。

## 7. 下一步

- 用户抽检 24 帧；不合格的按单帧 `--only <node> --frames first|last --force` 重拍，不整批重跑。
- 24 帧验收后，执行已批准的 T-014a：H3 1 条 7s / 480p 付费校准；全量 12 条需重新出成本预估单并确认。
