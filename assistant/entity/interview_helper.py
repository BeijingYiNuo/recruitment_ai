from sqlalchemy import Column, Integer, String, DateTime, Enum, Text, func, BigInteger
from sqlalchemy.orm import relationship
from assistant.config.database import Base
from assistant.enums import QuestionType


class InterviewQuestion(Base):
    """面试定制问题表"""
    __tablename__ = "interview_question"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="面试定制问题ID")
    question_text = Column(Text, nullable=False, comment="问题内容")
    question_type = Column(Enum(QuestionType), nullable=False, default=QuestionType.TECHNICAL, comment="问题类型")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 逻辑关联关系
    # 与InterviewSessionQuestion的关系（一对多）


class EvaluationStandard(Base):
    """评估标准表"""
    __tablename__ = "evaluation_standard"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="标准ID")
    name = Column(String(100), nullable=False, comment="标准名称")
    description = Column(Text, comment="标准描述")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 逻辑关联关系
    # 与InterviewSessionStandard的关系（一对多）


class InterviewAudioTranscript(Base):
    """面试音频转写表"""
    __tablename__ = "interview_audio_transcript"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="ID")
    session_id = Column(BigInteger, nullable=False, comment="会话ID")
    content = Column(Text, comment="语音转文本内容")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 逻辑关联关系
    # 与InterviewSession的关系（多对一）
