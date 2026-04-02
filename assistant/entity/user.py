from sqlalchemy import Column, Integer, String, DateTime, Enum, func
from sqlalchemy.orm import relationship
from assistant.config.database import Base
from assistant.enums import UserRole, UserStatus


class User(Base):
    """用户表"""
    __tablename__ = "user"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="用户ID")
    username = Column(String(50), nullable=False, comment="用户名")
    email = Column(String(100), unique=True, nullable=False, comment="邮箱")
    phone = Column(String(20), comment="手机号")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    role = Column(Enum(UserRole), nullable=False, default=UserRole.CANDIDATE, comment="角色")
    status = Column(Enum(UserStatus), nullable=False, default=UserStatus.ACTIVATE, comment="状态")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    last_login_at = Column(DateTime, comment="最后登录时间")
    
    # 逻辑关联关系
    # 与Resume的关系（一对多）
    # 与InterviewSession的关系（作为候选人或招聘官）
    # 与InterviewEvaluation的关系（作为评估人）
    # 与InterviewReminder的关系（作为被提醒人）
