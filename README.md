# 语音约碰面地点

按住录音，识别两人地点，推荐中间附近的碰面场所并播报。

当前进度：后端接口与前端联调代码已按约定落地。启动时清理过期临时文件尚未实现（读取时仍检查 24 小时有效期）。全量验收未完成。Mock 通过不能证明真实 ASR、DeepSeek、高德、TTS 已跑通。

## 环境

- Python 3.11（本机若已用 3.13 建好 `backend/.venv`，可继续用该环境）
- Node.js 22.12 及以上的 22.x
- ffmpeg（提供 `ffprobe`，用于校验真实容器、编码和时长，不转码）
- 后端 `http://localhost:8003`
- 前端 `http://localhost:5175`

安装 ffmpeg（macOS）：

```bash
brew install ffmpeg
ffprobe -version
```

## 配置

复制 `backend/.env.example` 为 `backend/.env`，填写：

| 变量 | 用途 |
|------|------|
| `BAILIAN_API_KEY` | 百炼 ASR / TTS |
| `DEEPSEEK_API_KEY` | 地址提取、推荐语 |
| `AMAP_API_KEY` | 高德 Web 服务 Key（地理编码、周边搜店） |

模型与完整 URL 已在 `.env.example` 中分开配置（北京地域百炼、DeepSeek Chat、高德 geo / around）。不要把真实密钥提交进 Git。已有 `.env` 时，即使执行 `cp .env.example .env`，`protect_env.sh` 也不会覆盖。

CORS 仅放行 `http://localhost:5175`。请用该地址打开前端，不要用 `http://127.0.0.1:5175`。

## 启动后端

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8003
```

健康检查：<http://localhost:8003/health>  
接口文档：<http://localhost:8003/docs>  
预期：HTTP 200，`data.status` 为 `"ok"`。密钥留空时健康检查仍应成功。

## 启动前端

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 <http://localhost:5175>。

## 模拟测试（Mock，不打真实供应商）

在 `backend` 目录、已激活虚拟环境时：

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/ -q
```

覆盖上传校验相关逻辑、ASR/提取/搜店/推荐语的 Mock 成功与部分失败分支。这些测试不调用百炼、DeepSeek、高德。Mock 通过不能替代真实接口联调，也不能证明前端全链路可用。

前端没有自动化测试，页面行为需人工验收。

## 真实接口与前端验收

`.env` 填好三个 Key 后，按下面顺序做。会消耗配额。不要用上传返回的 `aud_` 去请求 `GET /audio`；播报地址必须是 `POST /finalize` 返回的 `audio_url`（`tts_` 开头）。

超时预算（后端最坏路径 → 前端略长）：上传约 8s / 前端 12s；识别 30s+余量 / 40s；提取 15s / 22s；搜店双方定位 6+6s 加 2000/5000 米各 8s 共约 28s / 35s；推荐语 15s + TTS 20s + 下载 8s 共约 45s / 52s。

### 1. 正常录音到推荐与播放（真实服务）

1. 页顶显示后端服务正常。
2. 城市默认杭州，可改。
3. 按住说话，例如：「我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。」1—60 秒后松开。
4. 状态依次为：上传中、识别中、提取中、找店中、生成推荐中。
5. 页面出现识别文字、提取的两个地点和类型、最多 3 家店（店名、地址、距离中点多少米）、推荐语。
6. Network：`GET /health` → `POST /upload`（FormData 字段 `file`）→ `POST /asr` → `POST /extract` → `POST /search` → `POST /finalize` → `GET /audio/tts_...`。
7. 最后一项为音频二进制和正确 `Content-Type`，不是 JSON。自动播放被拦时点「点击播放」。

### 2. 麦克风拒绝、非法文件、重复点击

| 项 | 做法 | 预期 | 类型 |
|----|------|------|------|
| 拒绝麦克风 | 浏览器拒绝权限后按住 | 中文提示，Network 无 upload/asr 等业务请求 | 前端人工 |
| 录音过短 | 松开不足 1 秒 | 前端提示过短，不发业务请求 | 前端人工 |
| 非 WebM | `curl` 上传 jpg/mp3 到 `/upload` | 415 `UNSUPPORTED_MEDIA_TYPE` | 可用 curl 模拟 |
| 文件过大 | 上传超过 5MB | 413 `FILE_TOO_LARGE` | 可用 curl 模拟 |
| 重复提交 | 处理中再次按住并完成新录音 | 旧请求被取消或忽略，页面只保留新一轮 | 前端人工 |

### 3. 地址缺失、人数不符、跨城、定位不明确、无候选（真实提取/搜店）

在页面说对应内容，或在 `/docs` 对 `/extract`、`/search` 发 JSON：

| 场景 | 示例 | 预期 |
|------|------|------|
| 缺一方地址 | 「我在杭州东站，帮我找咖啡店」 | 422 `ADDRESS_MISSING`，不搜店 |
| 人数不符 | 「我们三个人，我在东站，朋友在龙翔桥，另一个在河坊街」 | 422 `PARTY_COUNT_INVALID` |
| 跨城 | 「我在杭州东站，朋友在上海人民广场」 | 422 `CROSS_CITY` |
| 含糊地址 | 「我在我家，朋友在公司」 | 422 `ADDRESS_MISSING` |
| 定位不明确 | 搜一个高德会返回多个不同坐标的地点 | 422 `GEOCODE_AMBIGUOUS` |
| 无候选 | 用极偏地点或不存在的类别搜店 | 422 `NO_POI_FOUND` |

页面应显示中文错误，停止后续请求，已完成的识别文字仍保留。

### 4. 外部服务异常、超时、文字降级

| 项 | 做法 | 预期 | 类型 |
|----|------|------|------|
| ASR/提取/搜店/推荐语失败 | 临时改错对应 URL 或清空该 Key 后重启后端 | 502 或 504，`error.stage` 对应阶段，后续停止 | 模拟故障；真实供应商故障需真实环境 |
| 请求超时 | 把供应商 URL 指到无法完成的地址 | 504 或前端「请求超时」 | 模拟故障 |
| 断网 | 关掉后端或断网后提交 | 前端网络失败提示 | 模拟故障 |
| TTS/下载降级 | 推荐语能成功时，把 `BAILIAN_TTS_URL` 改成不可达地址后重启，用未过期 `search_id` 再 finalize 或整链重录 | HTTP 200，`reply_text` 有内容，`audio_url` 为 `null`，显示 `warning` | 模拟故障；真实 TTS 成功需真实服务 |

测完恢复 `.env` 并重启后端。

### 5. 失败保留、重录清空、新旧不混用（前端人工）

1. 做到识别或找店成功后，人为让下一步失败：已完成区块仍在。
2. 再次按住录音：上一轮 `audio_id`、`search_id`、文字、店铺、推荐语和播报应被清空，旧音频停止。
3. 慢网或处理中开始新一轮：页面只展示新一轮结果，旧响应不得盖住新数据。

### 6. 编号有效期、临时数据、密钥与 Git

| 项 | 做法 | 预期 | 类型 |
|----|------|------|------|
| 过期 `audio_id` | Mock：`tests/test_asr.py` 中过期用例；真实：改 meta 的 `created_at` 为 25 小时前再 `POST /asr` | 404 `AUDIO_NOT_FOUND` | Mock 已有；真实可改文件模拟 |
| 过期 `search_id` | 改 `storage/search/*.json` 的 `created_at` 后 `POST /finalize` | 404 `SEARCH_NOT_FOUND` | 模拟 |
| 过期 `tts_` | 改 `storage/tts/*.meta.json` 后 `GET /audio/tts_...` | 404 JSON，`stage` 为 `audio_download` | 模拟 |
| 读取检查 | 不存在的 `aud_` / `srch_` / `tts_` | 404，不依赖启动清理 | 模拟 |
| 启动清理 | 约定启动时删除超过 24 小时的临时文件 | **尚未实现**；过期仍靠读取时检查 | — |
| 密钥 | `git check-ignore -v backend/.env` | 被忽略 | 本地检查 |
| 临时文件 | `git check-ignore -v backend/storage/audio/dummy` | `storage/*` 被忽略（`.gitkeep` 除外） | 本地检查 |
| 依赖目录 | `.venv/`、`node_modules/` | 被忽略 | 本地检查 |
| `.env.example` | 打开确认 Key 为空 | 可以入库 | 只读检查 |

## 说明

- 日志记录阶段和失败原因，不打印密钥或音频 Base64；请求耗时目前未写入日志。
- 中点只表示地理大致居中，页面距离文案为「距离中点」，不得理解成两人出行时间相同。
- 真实调用由你确认后执行。本 README 不把未跑过的项标为通过。
