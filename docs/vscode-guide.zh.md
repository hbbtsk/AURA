# VSCode 中启动 AURA 服务指南

本指南介绍如何在 VSCode 中启动和调试 AURA 服务。

---

## 方法一：VSCode 终端直接运行（推荐）

### 步骤 1：打开 VSCode 终端

- 快捷键：`` Ctrl+` ``
- 或菜单栏：查看 → 终端

### 步骤 2：切换到项目目录

```bash
cd c:\AURA
```

### 步骤 3：启动服务

**方式 A — Python 模块模式（推荐）**
```bash
python -m app.main
```

**方式 B — 直接运行 main.py**
```bash
python app/main.py
```

**方式 C — 直接使用 Uvicorn**
```bash
python -c "import uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=8000)"
```

---

## 验证服务是否启动成功

### 查看终端输出

启动成功后，你应该看到类似输出：

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

### 测试健康检查端点

在新终端标签页中执行：

```bash
curl http://localhost:8000/health
```

预期返回：
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

## 快速测试命令

### 模式 A — TAVO 兼容模式

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Tavo-Debug: true" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "你好！"}]
  }'
```

### 模式 B — 世界平台模式

```bash
# 加载 RWBY 卡带，与魏丝对话
curl -X POST http://localhost:8000/v1/world/completions \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好，魏丝。",
    "cartridge": "rwby_beacon",
    "model": "deepseek-v4-flash"
  }'
```

### 查看可用卡带

```bash
curl http://localhost:8000/v1/models
```

---

## 常见问题解决

### 1. `python` 命令找不到

```bash
py -m app.main
# 或
python3 -m app.main
```

### 2. 端口 8000 被占用

修改 `app/main.py` 中的端口：
```python
uvicorn.run("app.main:app", host="0.0.0.0", port=8001)
```

### 3. 缺少依赖包

```bash
pip install -r requirements.txt
```

### 4. FAISS 导入错误

```bash
pip install faiss-cpu
```

### 5. LLM 后端未配置

创建或编辑 `.env` 文件：
```bash
DEEPSEEK_API_KEY=sk-your-key
KIMI_API_KEY=sk-your-key
```

---

## 日志文件

| 日志 | 路径 | 说明 |
|-----|------|------|
| 应用日志 | `logs/aura.log` | 完整应用日志，自动轮转（5MB × 3 个备份） |
| 重启日志 | `logs/aura_restart.log` | 服务重启事件 |

实时查看日志：
```bash
type logs\aura.log
```

---

## 停止服务

在终端中按 `Ctrl+C` 即可优雅停止。

如果无响应，强制终止：
```bash
taskkill /F /IM python.exe
```

---

## 最佳实践

1. **保持终端开启**：服务运行期间保持 VSCode 终端标签页打开
2. **使用多个终端**：一个运行服务，一个测试 API
3. **观察日志**：实时观察终端输出，及时发现和处理问题
4. **启用调试模式**：在 `.env` 中设置 `debug_mode=true` 获取详细日志
5. **测试双模式**：同时验证 `/v1/chat/completions`（模式 A）和 `/v1/world/completions`（模式 B）
