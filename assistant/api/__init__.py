from fastapi import APIRouter, Depends
from assistant.api.user import router as user_router
from assistant.api.resume import router as resume_router
from assistant.api.interview import router as interview_router

from assistant.api.interview_reserve import router as interview_reserve_router
from assistant.user_management.auth_middleware import get_current_user_id

# 创建主路由器
api_router = APIRouter()

# 创建公开路由器（不需要认证）
public_router = APIRouter()

# 从用户路由器中提取注册和登录接口
for route in user_router.routes:
    if hasattr(route, 'path') and hasattr(route, 'methods'):
        # 注册接口：POST /api/users
        if route.path.endswith('') and 'POST' in route.methods:
            public_router.routes.append(route)
        # 登录接口：POST /api/users/login
        elif '/login' in route.path:
            public_router.routes.append(route)

# 包含所有子路由器
# 公开接口（注册和登录）不需要认证
api_router.include_router(public_router)

# 其他所有接口都需要认证
api_router.include_router(
    user_router,
    dependencies=[Depends(get_current_user_id)]
)
api_router.include_router(
    resume_router,
    dependencies=[Depends(get_current_user_id)]
)
api_router.include_router(
    interview_reserve_router,
    dependencies=[Depends(get_current_user_id)]
)
api_router.include_router(
    interview_router,
    dependencies=[Depends(get_current_user_id)]
)

