from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from assistant.enums import UserRole, UserStatus


class UserResponse(BaseModel):
    """用户响应模型"""
    id: int
    username: str
    email: str
    phone: Optional[str] = None
    role: UserRole
    status: UserStatus
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True
