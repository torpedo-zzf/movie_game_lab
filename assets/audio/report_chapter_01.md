# 第一章音频混音报告（T-017）

> 生成时间：2026-11-23T00:50:30+08:00
> 设计：`story/04_audio/audio_design_chapter_01.json`；分镜：`story/03_storyboards/chapter_01.json`
> 目标响度：-16.0 LUFS（True Peak -1.5 dBTP）；成片 12 OK / 0 FAIL / 0 待重拍

## 1. 九条成片实测

| 节点 | 时长 | LUFS(ebur128) | 偏差 | 音轨 | 大小 | 视频流 | 状态 |
|---|---|---|---|---|---|---|---|
| `ch01_s01_voiceover` | — | — | — | — | 待重拍，未处理 |
| `ch01_s02_peephole` | 8.00s | -16.00 | +0.00 | 48000Hz/2ch aac | 1.50 MB | copy | OK |
| `ch01_s03_knock` | 8.00s | -16.00 | +0.00 | 48000Hz/2ch aac | 1.52 MB | copy | OK |
| `ch01_s04_open` | 8.00s | -16.00 | +0.00 | 48000Hz/2ch aac | 1.82 MB | copy | OK |
| `ch01_s05_listen` | 8.00s | -16.00 | +0.00 | 48000Hz/2ch aac | 1.39 MB | copy | OK |
| `ch01_s06_lock` | 7.29s | -16.00 | +0.00 | 48000Hz/2ch aac | 1.36 MB | copy | OK |
| `ch01_s07_elevator` | — | — | — | — | 待重拍，未处理 |
| `ch01_s08_groupchat` | — | — | — | — | 待重拍，未处理 |
| `ch01_s09_second_knock` | 8.00s | -16.00 | +0.00 | 48000Hz/2ch aac | 1.64 MB | copy | OK |
| `ch01_s10_choice` | 8.00s | -16.00 | +0.00 | 48000Hz/2ch aac | 1.77 MB | copy | OK |
| `ch01_s11_end_testify` | 7.29s | -15.90 | +0.10 | 48000Hz/2ch aac | 1.59 MB | copy | OK |
| `ch01_s12_end_silence` | 8.00s | -16.00 | +0.00 | 48000Hz/2ch aac | 1.50 MB | copy | OK |

## 2. TTS 时间轴

| 节点 | 音色 | 起点 | 时长 | 提速 | 状态 |
|---|---|---|---|---|---|
| `ch01_s01_voiceover` | narrator | 1.20s | 3.29s | 1.00x | built |
| `ch01_s07_elevator` | narrator | 1.40s | 3.13s | 1.00x | built |
| `ch01_s08_groupchat` | narrator | 1.40s | 5.12s | 1.00x | built |

## 3. 合成方案

### TTS
- `say -v "<voice>" -r <rate>` → AIFF → 48k 单声道 WAV；`highpass=70` + 压缩/限幅，峰值归一化到 -3 dBFS；
- 逐字使用分镜 `dialogue`，脚本启动时校验 design `line` 与 storyboard 完全一致；
- 缓存键：台词/音色/语速/源文件 mtime；`--force-tts` 强制重做。

### SFX（21 个调色板 id，纯 stdlib 合成）
- 噪声塑形（brown/white + RBJ biquad 低通/带通/峰值）、正弦/锯齿、指数包络、简易延迟混响；
- 每个 id 的基片时长 >= 设计中最长引用时长，混音时按 `dur_sec` 裁剪；
- 19 个设计 id：room_tone / corridor_drag / peephole_metal / carpet_drag / knock_three / keys_jingle /
  door_open_creak / heartbeat / door_lock_click / footsteps_hall / elevator_hum / elevator_ding /
  phone_notify / police_siren_far / knock_hard / radio_squelch / gurney_wheels / delete_confirm / light_switch；
- 2 个预留 id：door_close_soft / phone_vibrate。

### BGM（3 条，低频 drone 为主）
- `tension` 32s：D1/D2 + 小三级 + 五度，慢速 LFO 与 4.2s 次低频脉冲；
- `ending_a` 36s：A 小调 drone + 稀疏钟音，结尾叠入 C# 向大调靠拢；
- `ending_b` 36s：D + Ab 三全音 drone、空洞高频气声，无解决；
- 首尾 1.0–1.2s 交叉淡化实现无缝循环，边缘再 10ms 淡化防爆音。

### 混音链
- 原声 `-20 dB` 压低；TTS 单独声道并 `asplit` 出 sidechain key；
- `sidechaincompress`（threshold 0.04 / ratio 6 / attack 15ms / release 420ms）对 BGM 闪避；
- 4 路 `amix normalize=0` → 两遍 `loudnorm I=-16:TP=-1.5:LRA=11` → AAC 回填 → 成片 `ebur128` 闭环微调；
- 输出 48k 立体声 PCM24 母版，AAC 192k 回填；`-map 0:v -map 1:a -c:v copy -shortest`；

## 4. 校验

- 视频流：h264 / 832×480 / 帧数与视频流 MD5 与 `raw/` 完全一致；
- 音频流：aac / 48000 Hz / 2ch；成片时长与原始视频差 <= 0.06s；
- 响度：`ffmpeg -af ebur128=peak=true` 测量整片，并以成片 ebur128 闭环微调；`loudnorm` 交叉复核，偏差在 ±2 LU 内；
- 非静音：`astats` RMS/Peak 与 `qc/*_frame_wave.png` 抽帧+波形对照图；
- `node player/selftest.mjs` 见交付说明。

## 5. 待重拍节点

`ch01_s01_voiceover` / `ch01_s07_elevator` / `ch01_s08_groupchat` 本次按边界不处理。
重拍替换 `assets/videos/<node>.mp4` 后，用一条命令补跑：

```bash
python3 scripts/build_audio_chapter_01.py --only s01,s07,s08 --allow-pending
```

脚本会为这三条新建 `assets/videos/raw/<node>.mp4` 备份，再走同一套 TTS/混音/校验。

## 6. 已知问题 / 说明

- 设计文件实际引用 19 个唯一 SFX id（45 条引用），与任务描述里的「21 个调色板 id」差 2；
  脚本补齐 `door_close_soft`、`phone_vibrate` 两个预留 id，21 个全部落盘。
- BGM/SFX 为算法合成，听感以「可信、不抢台词」为目标，不是采样级拟真；建议真人试听后微调 `gain_db`。
- `s08` 警笛段额外 -2 dB 的规则已写入 `bgm` 增益计算，待该条重拍后生效。
- 混音不重编码视频流；播放器未做任何修改。
