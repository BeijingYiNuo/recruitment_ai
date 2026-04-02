from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from assistant.api import api_router

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

# 根路径
@app.get("/")
def read_root():
    return {"message": "Recruitment Service API"}

# 健康检查
@app.get("/health")
def health_check():
    return {"status": "healthy"}
