from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from assistant.api import api_router
from assistant.streaming.router import router as stream_router
from assistant.streaming.session import StreamManager
from assistant.config.database import engine
from sqlalchemy import text
import asyncio
import logging

logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(title="Recruitment Service")

# 配置CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 配置限流中间件
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 包含API路由
app.include_router(api_router)
app.include_router(stream_router)


@app.on_event("startup")
async def startup_cleanup():
    """启动时迁移数据库并定期清理超时流式会话。"""
    # 自动迁移：为 resume 表添加 original_file_name 列（如已存在则跳过）
    try:
        with engine.connect() as conn:
            conn.execute(
                text("ALTER TABLE resume ADD COLUMN original_file_name VARCHAR(256) NULL COMMENT '原始文件名'")
            )
            conn.commit()
            logger.info("数据库迁移完成：resume.original_file_name 列已添加")
    except Exception as e:
        # 列已存在或其他错误，忽略
        logger.info(f"数据库迁移检查（可忽略）: {e}")

    async def _cleanup():
        while True:
            await asyncio.sleep(120)
            StreamManager.get_instance().cleanup_stale(300)

    asyncio.create_task(_cleanup())

    # 备注：SSE 逐条推送功能已移除，改为前端轮询

