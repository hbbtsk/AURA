# VSCode Quick Start Guide

This guide covers how to start and debug the AURA service inside VSCode.

---

## Method 1: VSCode Terminal (Recommended)

### Step 1: Open the Terminal

- Shortcut: `` Ctrl+` ``
- Or: View → Terminal

### Step 2: Navigate to the Project Directory

```bash
cd c:\AURA
```

### Step 3: Start the Service

**Option A — Python module mode (recommended)**
```bash
python -m app.main
```

**Option B — Run main.py directly**
```bash
python app/main.py
```

**Option C — Uvicorn directly**
```bash
python -c "import uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=8000)"
```

---

## Verify the Service Is Running

### Check Terminal Output

On successful startup you should see:

```
AURA 初始化完成
服务模式: LangGraph 状态机 + 3层记忆 + 意图感知 (v0.9.0)
调试模式: 启用
激活的LLM后端: ['deepseek', 'kimi']
[AURA→记忆] MemoryManager 就绪 | FAISS 记忆数: 0
[AURA→卡带] 可用卡带: ['rwby_beacon']
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Test the Health Endpoint

In a new terminal tab:

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "AURA",
  "version": "0.9.0",
  "mode": "dual",
  "world_loaded": false,
  "available_cartridges": ["rwby_beacon"]
}
```

---

## Quick Test Commands

### Mode A — TAVO Compatible

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Tavo-Debug: true" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Mode B — World Platform

```bash
# Load the RWBY cartridge and talk to Weiss
curl -X POST http://localhost:8000/v1/world/completions \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好，魏丝。",
    "cartridge": "rwby_beacon",
    "model": "deepseek-v4-flash"
  }'
```

### List Available Cartridges

```bash
curl http://localhost:8000/v1/models
```

---

## Troubleshooting

### 1. `python` Command Not Found

```bash
py -m app.main
# or
python3 -m app.main
```

### 2. Port 8000 Already in Use

Change the port in `app/main.py`:
```python
uvicorn.run("app.main:app", host="0.0.0.0", port=8001)
```

### 3. Missing Dependencies

```bash
pip install -r requirements.txt
```

### 4. FAISS Import Error

```bash
pip install faiss-cpu
```

### 5. LLM Backend Not Configured

Create or edit `.env`:
```bash
DEEPSEEK_API_KEY=sk-your-key
KIMI_API_KEY=sk-your-key
```

---

## Log Files

| Log | Path | Description |
|-----|------|-------------|
| Application log | `logs/aura.log` | Full application logs with rotation (5MB × 3 backups) |
| Restart log | `logs/aura_restart.log` | Service restart events |

View logs in real time:
```bash
type logs\aura.log
```

---

## Stopping the Service

Press `Ctrl+C` in the terminal for graceful shutdown.

Force kill if unresponsive:
```bash
taskkill /F /IM python.exe
```

---

## Best Practices

1. **Keep the terminal open** while the service is running
2. **Use multiple terminal tabs**: one for the service, one for testing APIs
3. **Watch the logs**: real-time terminal output shows request flow and errors
4. **Enable debug mode**: set `debug_mode=true` in `.env` for verbose logging
5. **Test both modes**: verify `/v1/chat/completions` (Mode A) and `/v1/world/completions` (Mode B)
