# 配音 / 音效 / BGM 交付报告（T-017）

> 日期：2026-11-23
> 设计：Agy `story/04_audio/audio_design_chapter_01.json`
> 实现：Codex `scripts/build_audio_chapter_01.py`（纯 stdlib + macOS `say` + ffmpeg）
> 结果：**12/12 条成片带完整音轨**，整片 -16 LUFS，视频流零重编码。

## 1. 方案

| 层 | 实现 |
|---|---|
| TTS | macOS `say` 5 个 zh_CN 音色：Eddy（旁白/沈砚旁白）、Grandpa（周启明）、Flo（苏敏）、Reed（沈砚）、Rocko（陈警官）；48k 单声道，`highpass=70` + 压缩/限幅，峰值归一 -3 dBFS |
| SFX | 21 个纯 stdlib 合成音效（brown/white noise + biquad + 包络 + 延迟混响），设计实际引用 19 类、预留 2 类 |
| BGM | 3 段低频 drone：`tension` 32s（s01–s10）、`ending_a` 36s（s11）、`ending_b` 36s（s12），首尾交叉淡化可循环 |
| 混音 | 原声 -20dB + TTS + SFX + BGM；TTS 侧链闪避 BGM（约 12dB）；`loudnorm I=-16 TP=-1.5` 两遍；回填 `-c:v copy -c:a aac 192k` |
| 回填 | `assets/videos/<node>.mp4`；原始视频备份 `assets/videos/raw/<node>.mp4` |

## 2. 12 条实测

| 节点 | 台词 | 音色 | TTS | SFX | LUFS | True Peak | 视频流 |
|---|---|---|---|---|---|---|---|
| `ch01_s01_voiceover` | 凌晨两点，最后一条配音过了。 | Eddy | 3.29s | 3 | -16.0 | -4.2 | MD5 一致 |
| `ch01_s02_peephole` | 猫眼里，对门的老周正拖着一卷地毯。 | Eddy | 3.77s | 3 | -16.0 | -3.5 | MD5 一致 |
| `ch01_s03_knock` | 小沈，我家跳闸了，借个电话。 | Grandpa | 3.73s | 3 | -16.0 | -2.8 | MD5 一致 |
| `ch01_s04_open` | 地毯？旧东西，明天就扔。 | Grandpa | 3.55s | 4 | -16.0 | -1.9 | MD5 一致 |
| `ch01_s05_listen` | 别信他。 | Flo | 1.15s | 3 | -16.0 | -2.2 | MD5 一致 |
| `ch01_s06_lock` | 门锁扣上的声音，比想象中响。 | Eddy | 3.29s | 4 | -16.0 | -4.8 | MD5 一致 |
| `ch01_s07_elevator` | 电梯停在七楼，很久没有动。 | Eddy | 3.13s | 4 | -16.3 | -2.5 | MD5 一致 |
| `ch01_s08_groupchat` | 业主群里有人说：704 好像出事，已经报警。 | Eddy | 5.12s | 4 | -15.9 | -4.4 | MD5 一致 |
| `ch01_s09_second_knock` | 警察来了，你打算怎么说？ | Grandpa | 3.00s | 4 | -16.0 | -3.0 | MD5 一致 |
| `ch01_s10_choice` | 门外的警灯，一下一下扫过猫眼。 | Reed | 3.25s | 4 | -16.0 | -3.8 | MD5 一致 |
| `ch01_s11_end_testify` | 沈先生，把录音给我。 | Rocko | 2.58s | 4 | -15.9 | -1.9 | MD5 一致 |
| `ch01_s12_end_silence` | 天亮之前，他删掉了那段录音。 | Eddy | 3.27s | 5 | -16.0 | -3.0 | MD5 一致 |

- 音频流：全部 AAC 48000Hz 2ch；`astats` RMS -19.6 ~ -22.8 dBFS，非静音。
- 时长：7s 档 7.29s、8s 档 8.00s（AAC 取整差 0.01s，视频帧完整）。
- 波形证据：`assets/audio/qc/qc_waveforms_chapter_01.png`（9 条）、`state/audio_build_chapter_01.json`。

## 3. 关键动作音效对照

| 节点 | 关键音效 |
|---|---|
| s01 | 走廊拖行 + 金属轻响 + 玄关底噪 |
| s02 | 地毯拖行 + 贴猫眼金属声 |
| s03 | 三下敲门 + 钥匙串 |
| s04 | 开门吱呀 + 挡地毯 + 心跳 |
| s05 | 闷响 + 苏敏气音「别信他」 |
| s06 | 反锁 + 门链 + 脚步远去 |
| s07 | 电梯嗡鸣 + 层站提示 + 钥匙（无开门声） |
| s08 | 群消息提示 + 心跳 + 远处警笛 |
| s09 | 重敲门 + 对讲机 + 警笛 |
| s10 | 警笛 + 心跳 + 对讲机 |
| s11 | 开门 + 对讲机 + 多脚步 + 担架轮 |
| s12 | 心跳 + 删除确认 + 关灯 + 极轻警笛 |

## 4. 重建

```bash
# 全部重建（缓存命中时很快）
python3 scripts/build_audio_chapter_01.py

# 只做指定节点
python3 scripts/build_audio_chapter_01.py --only s03,s08 --force

# 只打印时间轴
python3 scripts/build_audio_chapter_01.py --dry-run

# 校验已有成片（不写文件）
python3 scripts/build_audio_chapter_01.py --verify-only
```

生成的 WAV/QC 图不入库（见 `.gitignore`），只保留本报告；脚本可确定性重建。

## 5. 已知限制

- TTS 为 macOS `say`，情感与口型不可控；要更专业的配音需换 Fish Audio / Breeze TTS / 真人录音，再复用同一混音脚本。
- SFX/BGM 为算法合成，可信但不采样级拟真；需要可微调 `story/04_audio/audio_design_chapter_01.json` 的 `gain_db`。
- 字幕与语音由播放器分别显示/播放，未做逐字时间轴；台词较长时以 TTS 自然时长为准。
- 未做旁白/对白音量用户可调（播放器未加音量控件）。
