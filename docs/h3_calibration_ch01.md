# H3 直连 480p 7s 校准报告（T-014a）

> 日期：2026-11-22
> 方式：**直连 MiniMax API** `POST /v2/video_generation`（metaso.cn 代理），首/末帧经阿里云 OSS 签名 URL 提供。
> 审批：`APR-20261122-VID-003`（用户回复「确认直连 480p 7s」）。
> 结果：**成功**，1 条，832×480 / 7.3s / h264 + aac。

## 1. 请求

| 项 | 值 |
|---|---|
| 节点 | `ch01_s01_voiceover` |
| 模型 | `MiniMax-H3` |
| 分辨率 | `480p`（接口返回记为 `480P`） |
| 时长 | 7 秒 |
| 比例 | `adaptive`（跟随首帧 16:9） |
| 首帧 | `movie_game_lab/frames/ch01_s01_voiceover_first.png`（OSS 签名 URL） |
| 末帧 | `movie_game_lab/frames/ch01_s01_voiceover_last.png`（OSS 签名 URL） |
| 输入图数量 | 2 |
| `fast_mode` | false |

`task_id`：`2124521845248765952`
`usage`：`total_seconds=7`、`output_seconds=7`、`input_image_count=2`

## 2. 成本

| 项 | 值 |
|---|---|
| 余额前 | 11605.00 credits |
| 余额后 | 11551.56 credits |
| **实际扣费** | **53.44 credits** |
| 审批上限 | 200 credits / $0.50 |
| 按上限费率折算 | 约 **$0.13**（非正式账单，仅作估算） |
| 重试 | 0 次 |

实际只用掉上限的约 27%，**未超 10% 阈值**，本单无需重新确认。

## 3. 成片

| 项 | 值 |
|---|---|
| 文件 | `assets/videos/calibration_ch01_s01.mp4` |
| 同源备份 | `assets/videos/calibration_ch01_s01_480p.mp4` |
| 画面 | h264，832×480，24fps，1.58 Mb/s |
| 音频 | aac，32kHz 立体声，128kb/s |
| 时长 | 7.30s |
| 大小 | 1.57 MB |
| 抽帧 | `assets/videos/calibration_ch01_s01_contact.png`（0.1s / 3.5s / 7.0s） |

## 4. 人眼验收

- 首帧：玄关暖黄灯 + 门缝冷绿光，沈砚深灰卫衣、耳机挂脖，身份与 s01 首帧一致；
- 中段：镜头切到背影沿走廊走，**不是分镜要求的「摘耳机、转头看门」**；
- 末帧：回到门边、手搭门把，但与 s01 末帧「侧身贴门、右手悬在门把上方」不完全一致；
- 无文字/水印；音频有环境声但偏轻（mean -39dB / max -20.7dB）。

结论：**管线、鉴权、计费、OSS 公网链路全部跑通**；动作与末帧贴合度不够，属于 prompt/首末帧引导问题，不代表管线失败。正式批量前应针对「摘耳机→转头→看门」写更明确的动作时序，并把末帧构图约束写进 prompt。

## 5. 全量 12 条的初步外推（未批准）

按本次 53.44 credits / 7s 粗算：

- 12 条 / 91s ≈ **695 credits**（约 $1.74 按上限费率）；
- 加 20% 重试预算 ≈ **835 credits**（约 $2.09）；
- 建议正式出单区间 **650–850 credits**，上限 **900 credits / $2.25**；
- 该数字只是线性外推，不同镜头时长/动作/重试会变；**全量提交前必须重新出《视频成本预估单》并获得用户明确确认**。

## 6. 复现

```bash
# 1) 首末帧已在 OSS：movie_game_lab/frames/<node>_first.png / _last.png
# 2) 需要新的审批 id 后，单条提交：
python3 scripts/minimax_h3_generate.py \
  --approval-id <APPROVAL_ID> \
  --node ch01_s01_voiceover \
  --resolution 480p --duration 7 \
  --confirm CONFIRM
```

脚本只做单条提交；不会自动批量、不会自动重试。记录写在 `state/h3_direct_calibration.json`。
