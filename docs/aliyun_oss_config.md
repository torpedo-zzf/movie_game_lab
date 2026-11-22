# 阿里云 OSS 配置（给 MiniMax H3 提供公网图片 URL）

> 密钥文件：`.env.local`（项目根，chmod 600，gitignore）。
> **不要把 AccessKey Secret 贴到聊天里**；用本地交互命令录入。

## 1. 前置

- 一个 OSS Bucket（建议**私有**，用签名 URL 给 MiniMax，不必开公共读）；
- Bucket 的 Endpoint，如 `oss-cn-hangzhou.aliyuncs.com`；
- 一个 RAM 子账号的 AccessKey，权限只需该 Bucket 的：
  - `oss:PutObject`
  - `oss:GetObject`
  - `oss:ListObjects`（check 可选）
- 不需要 CORS；MiniMax 是服务端拉取。

## 2. 配置

```bash
# 逐项录入；Secret 不回显，文件自动 600
python3 scripts/oss_config.py set

# 查看（key 打码）
python3 scripts/oss_config.py show

# 验证认证与 Bucket 可用（HEAD，不写文件）
python3 scripts/oss_config.py check
```

`.env.local` 会增加：

```dotenv
OSS_ACCESS_KEY_ID=...
OSS_ACCESS_KEY_SECRET=...
OSS_BUCKET=your-bucket
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_PUBLIC_BASE_URL=
```

## 3. 上传并拿签名 URL

```bash
python3 scripts/oss_upload.py assets/frames/chapter_01/ch01_s01_voiceover_first.png --check
```

输出：

```json
{
  "key": "movie_game_lab/frames/ch01_s01_voiceover_first.png",
  "url": "https://<bucket>.<endpoint>/movie_game_lab/frames/...png",
  "presigned_url": "https://...?OSSAccessKeyId=...&Expires=...&Signature=...",
  "expires_in": 604800,
  "check_http": 200
}
```

- `presigned_url` 默认 **7 天**有效，可直接填进 MiniMax `/v2/video_generation` 的 `image_url`；
- 桶保持私有也能访问；
- `--ttl 86400` 可改 1 天；`--prefix` 改对象前缀；`--name` 改文件名；
- `--check` 会对签名 URL 做 HEAD，确认公网可读。

## 4. 安全

- `.env.local` 已 gitignore + 600；
- 建议用 RAM 子账号、只授权单 Bucket，不要用主账号 AccessKey；
- 签名 URL 谁拿到谁能读，TTL 尽量短；给 MiniMax 前先生成，生成后不需要长期公开；
- 如泄露 AccessKey，在阿里云控制台禁用并轮换。

## 5. 和 MiniMax 的衔接

1. `oss_upload.py` 上传 s01 首/末帧，拿到两个 `presigned_url`；
2. 调 `POST /v2/video_generation`：
   ```json
   {
     "model": "MiniMax-H3",
     "content": [
       {"type": "text", "text": "..."},
       {"type": "image_url", "image_url": {"url": "<首帧签名URL>"}, "role": "first_frame"},
       {"type": "image_url", "image_url": {"url": "<末帧签名URL>"}, "role": "last_frame"}
     ],
     "resolution": "480p",
     "duration": 7,
     "ratio": "adaptive",
     "fast_mode": false
   }
   ```
3. `GET /v2/query/video_generation/{task_id}` 轮询，成功后下载 `content.url` 到 `assets/videos/`。

**提交前仍受成本确认闸门约束**：480p/768P/1080p 为 4–30 整数秒，2K 最长 15 秒；>15 秒总价翻倍；基础费+素材费+输出费；Context IR 与再生成单独计费。
