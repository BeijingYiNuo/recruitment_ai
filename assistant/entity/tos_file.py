from sqlalchemy import Column, BigInteger, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.sql import func
from assistant.config.database import Base


class TosFile(Base):
    """TOS 文件存储模型"""
    __tablename__ = "user_file"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键 ID")
    user_id = Column(BigInteger, nullable=False, comment="所属用户 ID")
    file_name = Column(String(256), nullable=False, comment="原始文件名")
    file_type = Column(String(64), nullable=False, comment="文件类型（resume/voice/dialogue）")
    file_size = Column(BigInteger, nullable=False, comment="文件大小（字节）")
    file_uri = Column(String(1024), nullable=False, unique=True, comment="文件访问 URI（用于 API 访问）")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")