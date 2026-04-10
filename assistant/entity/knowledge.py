from sqlalchemy import Column, BigInteger, String, Text, ForeignKey, DateTime, JSON, Boolean, Enum
from sqlalchemy.sql import func
from assistant.config.database import Base
import enum


class KnowledgeRole(enum.Enum):
    ENTERPRISE = "ENTERPRISE"
    PROFESSIONAL = "PROFESSIONAL"
    USER = "USER"


class ChunkingStrategy(enum.Enum):
    CUSTOM_BALANCE = "custom_balance"
    CUSTOM = "custom"


class UserKnowledge(Base):
    """用户知识库模型"""
    __tablename__ = "user_knowledge"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    name = Column(String(128), nullable=False, unique=True, comment="知识库名称")
    description = Column(Text, nullable=False, comment="知识库描述信息")
    user_id = Column(BigInteger, nullable=False, comment="所属用户ID")
    role = Column(Enum(KnowledgeRole, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=KnowledgeRole.USER, comment="知识库角色（企业知识库、专业领域知识库、用户知识库）")
    project = Column(String(64), nullable=False, default="default", comment="所属项目")
    version = Column(BigInteger, nullable=False, default=2, comment="版本（2:标准版、4:旗舰版）")
    chunking_strategy = Column(Enum(ChunkingStrategy, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=ChunkingStrategy.CUSTOM_BALANCE, comment="切片策略")
    chunking_identifier = Column(JSON, nullable=True, comment="切片标识符列表")
    chunk_length = Column(BigInteger, nullable=False, default=500, comment="切片长度")
    merge_small_chunks = Column(Boolean, nullable=False, default=True, comment="是否合并小切片")
    enabled = Column(Boolean, nullable=False, default=False, comment="是否开启文档AI摘要功能")
    created_at = Column(DateTime, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, comment="更新时间")
    
class UserDocument(Base):
    """用户知识库文档模型"""
    __tablename__ = "user_document"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    user_id = Column(BigInteger, nullable=False, comment="所属用户ID")
    knowledge_id = Column(BigInteger, nullable=False, comment="所属知识库ID")
    file_id = Column(BigInteger, nullable=False, comment="文件id")
    knowledge_name = Column(String(256), nullable=False, comment="所属知识库名称")
    doc_name = Column(String(256), nullable=False, comment="文档名称")
    doc_type = Column(String(256), nullable=False, comment="文档类型")
    description = Column(Text, nullable=False, comment="文档描述")
    created_at = Column(DateTime, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, comment="更新时间")