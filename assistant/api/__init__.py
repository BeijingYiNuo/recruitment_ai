from fastapi import APIRouter
from assistant.api.user import router as user_router
from assistant.api.resume import router as resume_router
from assistant.api.interview import router as interview_router
from assistant.api.interview_helper import router as interview_helper_router
from assistant.api.interview_reserve import router as interview_reserve_router

# 创建主路由器
api_router = APIRouter()

# 包含所有子路由器
api_router.include_router(user_router)
api_router.include_router(resume_router)
api_router.include_router(interview_reserve_router)
api_router.include_router(interview_router)
api_router.include_router(interview_helper_router)

