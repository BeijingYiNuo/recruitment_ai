from pydantic import BaseModel, EmailStr, Field, validator
from assistant.enums import UserRole
import re


class UserCreate(BaseModel):
    """用户创建模型"""
    username: str = Field(..., min_length=3, max_length=20, description="用户名，长度3-20位")
    email: EmailStr
    phone: str = None
    password: str = Field(..., min_length=8, description="密码，长度至少8位")
    role: UserRole = UserRole.CANDIDATE
    
    @validator('username')
    def validate_username(cls, v):
        """验证用户名，禁止特殊字符"""
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('用户名只能包含字母、数字和下划线')
        return v
    
    @validator('password')
    def validate_password(cls, v):
        """验证密码强度"""
        if len(v) > 72:
            raise ValueError('密码长度不能超过72个字符')
        if not re.search(r'[A-Z]', v):
            raise ValueError('密码必须包含至少一个大写字母')
        if not re.search(r'[a-z]', v):
            raise ValueError('密码必须包含至少一个小写字母')
        if not re.search(r'[0-9]', v):
            raise ValueError('密码必须包含至少一个数字')
        return v


class UserUpdate(BaseModel):
    """用户更新模型"""
    username: str = None
    email: EmailStr = None
    phone: str = None
    password_hash: str = None
    role: UserRole = None


class UserLogin(BaseModel):
    """用户登录模型"""
    username: str = None
    password: str = Field(..., min_length=8, description="密码，长度至少8位")

