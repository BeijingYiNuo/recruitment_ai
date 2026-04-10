from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UserDocumentVO(BaseModel):
    """用户文档值对象"""
    id: int
    user_id: int
    knowledge_id: int
    file_id: int
    knowledge_name: str
    doc_name: str
    doc_type: str
    description: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True  # 支持从 SQLAlchemy 模型转换
