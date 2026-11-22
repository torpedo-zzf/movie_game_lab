# MiniMax H3 API Key 配置

> 本地密钥文件：**`.env.local`**（项目根目录，已 `chmod 600`，已被 `.gitignore` 忽略，不会入库）。
> 当前状态：key 已配置，`credits/balance` 验证通过。

## 1. 在哪里改

```bash
# 查看当前配置（key 打码）
python3 scripts/minimax_config.py show

# 交互式改 key（输入不回显；文件权限自动 600）
python3 scripts/minimax_config.py set-key

# 验证 key + 查余额（只读，不生成视频、不扣费）
python3 scripts/minimax_config.py check
```

`.env.local` 内容只有两行：

```dotenv
MINIMAX_BASE_URL=https://metaso.cn/api/minimax
MINIMAX_API_KEY=你的_key
```

`.env.example` 是入库模板；不要把真实 key 写进它。

## 2. 已验证

`python3 scripts/minimax_config.py check`：

```text
GET https://metaso.cn/api/minimax/v2/credits/balance -> HTTP 200
{
  "balance": 11605.0,
  "lecture_balance": 6400.0,
  ...
}
```

查询时余额 **11605 credits**（以你账户实时为准）。

## 3. API 端点（来自你的接口文档）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/v2/video_generation` | 文生视频 / 首帧 / 首末帧 / 参考图·视频·音频 |
| GET | `/v2/query/video_generation/{task_id}` | 查询任务；成功时返回 `content.url` 与 `usage` |
| POST | `/v2/h3_context_ir` | Context IR 单独计费 |
| POST | `/v2/video_regeneration` | 视频再生成，独立接口/计费 |
| GET | `/v2/credits/balance` | 余额（只读） |

请求要点：

- `model`: `MiniMax-H3`
- `content`: 文本 + `image_url`（`role: first_frame` / `last_frame` / `reference_image`）+ `video_url` / `audio_url`
- `resolution`: `480p` / `768P` / `1080p` / `2K`（以接口实际接受为准）
- `duration`: 480p/768P/1080p **4–30 整数秒**；2K **最长 15 秒**
- `ratio`: `16:9` / `9:16` / `adaptive` 等
- `fast_mode`: 布尔

计费规则（你给的）：

- 总价 = **基础费 + 素材费 + 输出费**
- 输出 **>15 秒**时视频任务总价翻倍
- Context IR 按原价单独计费
- 视频再生成按独立接口限制与费用执行

## 4. 重要限制：图片要公网 URL

文档里的 `image_url.image_url.url` 是公网地址；本地 `assets/frames/...` 不能直接填进去。真正走直连 API 生成前，还需要二选一：

1. 把首/末帧上传到可公网访问的临时对象存储/CDN；
2. 或确认接口是否接受 `data:image/png;base64,...` 的 data URI（需实测）。

ComfyUI 的 `MiniMaxH3KeyNode` 节点会自己在内部上传图片，所以它不需要公网 URL；但它当前只开放 768P/2K。480p 直连 API 的本地图片上传方式待验证。

## 5. 安全

- 不要把 `.env.local` 提交、截图或贴到聊天里；
- 轮换 key 直接 `set-key`，旧 key 在平台侧作废；
- `show` 只显示 `mk-xxxx…xxxx`，不打印全量。
