from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List
import re
from passlib.context import CryptContext
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from assistant.config.database import get_db
from assistant.entity import User, UserStatus
from assistant.entity.DTO import UserCreate, UserUpdate, UserLogin, TokenResponse
from assistant.entity.VO import UserResponse
from assistant.utils.logger import logger
from assistant.user_management.auth_utils import create_access_token
from assistant.user_management.auth_middleware import get_current_user_id

# 密码加密上下文
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# 限流配置
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/users", tags=["用户管理"])


@router.get("", response_model=List[UserResponse])
def get_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取用户列表"""
    users = db.query(User).filter(User.id == current_user_id).offset(skip).limit(limit).all()
    return users


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取单个用户"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    return user


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def create_user(
    user: UserCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """创建用户"""
    # 记录注册请求
    client_ip = get_remote_address(request)
    
    # 检查邮箱是否已存在
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        logger.warning(f"Registration attempt with existing email: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册"
        )
    
    # 检查用户名是否已存在
    existing_username = db.query(User).filter(User.username == user.username).first()
    if existing_username:
        logger.warning(f"Registration attempt with existing username: {user.username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已被使用"
        )
    
    # 密码加密（bcrypt限制密码长度为72字节）
    password_to_hash = user.password[:72]  # 截断密码到72字节
    hashed_password = pwd_context.hash(password_to_hash)
    
    # 创建新用户
    db_user = User(
        username=user.username,
        email=user.email,
        phone=user.phone,
        password_hash=hashed_password,
        role=user.role,
        status=UserStatus.ACTIVATE,
        last_login_at=None
    )
    
    try:
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        logger.info(f"User registered successfully: {user.email}")
    except IntegrityError:
        db.rollback()
        logger.error(f"Integrity error during registration: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="注册失败，请稍后重试"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error during registration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误"
        )
    
    return db_user
    
@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login_user(
    user: UserLogin,
    request: Request,
    db: Session = Depends(get_db)
):
    """用户登录"""
    # 记录登录请求
    # client_ip = get_remote_address(request)
    
    # 查找用户
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 检查用户状态
    if db_user.status != UserStatus.ACTIVATE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用"
        )
    
    # 验证密码
    if not pwd_context.verify(user.password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 更新最后登录时间
    from datetime import datetime
    db_user.last_login_at = datetime.now()
    
    try:
        db.commit()
        db.refresh(db_user)
        logger.info(f"User logged in successfully: {user.username}")
    except Exception as e:
        db.rollback()
        logger.error(f"Error during login: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误"
        )
    
    # 生成JWT Token
    access_token = create_access_token(
        data={"sub": str(db_user.id)}
    )
    
    # 返回Token响应
    return TokenResponse(
        access_token=access_token,
        token_type="Bearer",
        user_id=db_user.id,
        username=db_user.username,
        email=db_user.email
    )

@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """更新用户"""
    # 记录更新请求
    client_ip = get_remote_address(request)
    logger.info(f"User update attempt from IP: {client_ip}, user_id: {user_id}, current_user_id: {current_user_id}")
    
    # 查找用户
    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        logger.warning(f"Update attempt for non-existent user: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 检查邮箱是否已被其他用户使用
    if user.email and user.email != db_user.email:
        existing_email = db.query(User).filter(User.email == user.email).first()
        if existing_email:
            logger.warning(f"Update attempt with existing email: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被其他用户使用"
            )
    
    # 检查用户名是否已被其他用户使用
    if user.username and user.username != db_user.username:
        existing_username = db.query(User).filter(User.username == user.username).first()
        if existing_username:
            logger.warning(f"Update attempt with existing username: {user.username}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已被其他用户使用"
            )
    
    # 更新用户信息
    update_data = user.dict(exclude_unset=True)
    
    # 处理密码加密
    if "password_hash" in update_data:
        # 验证密码强度
        password = update_data["password_hash"]
        if len(password) > 72:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="密码长度不能超过72个字符"
            )
        if not re.search(r'[A-Z]', password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="密码必须包含至少一个大写字母"
            )
        if not re.search(r'[a-z]', password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="密码必须包含至少一个小写字母"
            )
        if not re.search(r'[0-9]', password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="密码必须包含至少一个数字"
            )
        # 加密密码
        password_to_hash = password[:72]
        update_data["password_hash"] = pwd_context.hash(password_to_hash)
    
    # 应用更新
    for key, value in update_data.items():
        setattr(db_user, key, value)
    
    try:
        db.commit()
        db.refresh(db_user)
        logger.info(f"User updated successfully: {user_id}")
    except IntegrityError:
        db.rollback()
        logger.error(f"Integrity error during user update: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="更新失败，请稍后重试"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error during user update: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误"
        )
    
    return db_user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """删除用户"""
    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    db.delete(db_user)
    db.commit()
    
    return None