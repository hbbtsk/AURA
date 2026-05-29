"""
AURA主应用 - Tavo→AURA→LLM桥梁模式
"""
import sys
import io

# 设置默认编码为UTF-8，解决Windows下的编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.api import initialize_aura
from app.core.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化（含 MemoryManager）
    await initialize_aura()
    # 初始化维测数据库
    from app.debug import init_db
    init_db()
    yield

# 创建FastAPI应用
app = FastAPI(
    title="AURA",
    description="Agentic Unified Roleplay Assistant - Tavo→AURA→LLM桥梁",
    version="1.0.0",
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-Tavo-Debug"],  # 允许Tavo调试头
)

# 禁用前端页面缓存（确保 index.html 更新后立即生效）
@app.middleware("http")
async def add_cache_control_header(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/dashboard") or request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# 注册路由
from app.api import router as aura_router
app.include_router(aura_router, prefix="/v1")

# 注册调试路由
from app.debug.routes import debug_router
app.include_router(debug_router, prefix="/debug")

# 注册 Dashboard API（前端观测台数据源）
from app.api import dashboard_router
app.include_router(dashboard_router, prefix="/api")

# 托管维测前端页面（仅 static/ 目录，避免暴露项目根目录的敏感文件）
import os
_static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
app.mount("/dashboard", StaticFiles(directory=_static_dir, html=True), name="dashboard")

# 健康检查端点
@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "AURA",
        "version": "1.0.0",
        "mode": "langgraph-state-machine",
        "debug": settings.debug_mode
    }

# 根路径
@app.get("/")
async def root():
    """根路径信息"""
    return {
        "message": "AURA - Tavo→AURA→LLM桥梁已启动",
        "description": "拦截和分析Tavo与LLM之间的数据传输",
        "endpoints": {
            "chat": "/v1/chat/completions",
            "health": "/health",
            "debug": "/debug/requests"
        },
        "debug_mode": settings.debug_mode
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,  # 禁用热重载，避免日志文件写入触发无限 reload
        log_level="info" if settings.debug_mode else "warning"
    )