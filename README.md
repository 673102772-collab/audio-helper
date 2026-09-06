# 语音约碰面地点

本地全栈项目：按住录音，识别两人地点并推荐中间附近的碰面场所。

当前进度：项目骨架。后端仅提供 `GET /health`，前端为基础页面，录音与其他业务接口尚未实现。

## 环境

- Python 3.11
- Node.js 22.12 及以上的 22.x
- 后端 `http://localhost:8003`
- 前端 `http://localhost:5175`

## 配置

复制 `backend/.env.example` 为 `backend/.env`。骨架阶段密钥可留空，健康检查不依赖外部服务。

## 启动后端

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8003
```

## 启动前端

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 <http://localhost:5175>。

## 验证健康检查

- 接口：<http://localhost:8003/health>
- 文档：<http://localhost:8003/docs>

预期：HTTP 200，JSON 含 `request_id` 与 `data.status` 为 `"ok"`。

## 测试说明

自动化测试与真实供应商联调尚未纳入本轮。Mock 通过不能证明真实 ASR、DeepSeek、高德、TTS 已跑通。
