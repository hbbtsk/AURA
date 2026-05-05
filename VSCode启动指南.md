# VSCode中启动AURA服务指南

## 方法一：使用VSCode终端直接运行（推荐）

### 步骤1：打开VSCode终端
- 使用快捷键 `` Ctrl+` `` 打开终端
- 或者点击菜单栏：查看 → 终端

### 步骤2：确保在正确的目录
在终端中执行：
```bash
cd c:\AURA
```

### 步骤3：启动服务
有三种等效的命令方式：

#### 方式A：使用Python模块模式（推荐）
```bash
python -m app.main
```

#### 方式B：直接运行main.py
```bash
python app/main.py
```

#### 方式C：使用模块导入模式
```bash
python -c "from app.main import app; import uvicorn; uvicorn.run(app, host='0.0.0.0', port=8000)"
```

## 方法二：使用启动脚本

### 使用bat脚本（最简单）
在VSCode终端中执行：
```bash
# 使用全局Python环境启动脚本
.\start_aura.bat

# 或者使用简化版本
.\start_aura_simple.bat

# 或者使用专门的全局环境脚本
.\start_aura_global.bat
```

## 验证服务是否启动成功

### 查看终端输出
成功启动后，你应该看到类似这样的输出：
```
AURA简化版本初始化完成
   服务模式: 直接转发 (无数据库)
   调试模式: 启用
   激活的LLM后端: ['deepseek']
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### 测试健康检查端点
在新的终端标签页中执行：
```bash
curl http://localhost:8000/health
```

应该返回：
```json
{"status":"healthy","service":"AURA","version":"0.2.0","mode":"interception","debug":true}
```

## 常见问题解决

### 1. Python命令找不到
如果提示 `python` 命令找不到，尝试：
```bash
py -m app.main
# 或者
python3 -m app.main
```

### 2. 端口被占用
如果提示端口8000被占用，可以修改端口：
```bash
# 修改app/main.py中的端口配置
# 或者在启动命令中指定端口
python -m app.main --port 8001
```

### 3. 依赖包问题
如果提示缺少依赖，重新安装：
```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

## 查看日志输出

### 实时日志
服务启动后，所有日志都会实时显示在VSCode终端中，包括：
- 服务启动信息
- 请求处理详情
- 调试信息
- 错误日志

### 文件日志
详细日志还会保存到文件中：
```bash
# 查看日志文件列表
dir tavo_requests_*.log

# 实时查看最新日志
type tavo_requests_*.log
```

## 停止服务

在VSCode终端中按 `Ctrl+C` 即可优雅地停止服务。

如果服务无响应，可以强制终止：
```bash
taskkill /F /IM python.exe
```

## 最佳实践

1. **保持终端开启**：服务运行期间保持VSCode终端标签页开启
2. **使用多个终端**：可以开启多个终端标签页，一个运行服务，一个测试API
3. **监控日志**：实时观察终端输出，及时发现和处理问题
4. **调试模式**：确保在 [`app/config.py`](app/config.py) 中 `debug_mode=True` 以获得详细日志

## 快速测试命令

```bash
# 启动服务
python -m app.main

# 测试健康检查
curl http://localhost:8000/health

# 测试API端点（带调试信息）
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Tavo-Debug: true" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"你好！"}]}'
```

现在你可以在VSCode中轻松启动和调试AURA服务了！