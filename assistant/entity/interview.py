from sqlalchemy import Column, Integer, String, DateTime, Enum, Text, func
from sqlalchemy.orm import relationship
from assistant.config.database import Base
from assistant.enums import (
    SessionType, SessionStatus, Recommendation,
    ReminderStatus, SendMethod, ReportStatus
)

    
class InterviewSession(Base):
    """面试会话表"""
    __tablename__ = "interview_session"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="面试会话ID")
    candidate_name = Column(String(20), nullable=False, comment="面试人姓名")
    recruiter_id = Column(Integer, nullable=False, comment="招聘官ID")
    resume_id = Column(Integer, nullable=True, comment="简历ID")
    session_type = Column(Enum(SessionType), nullable=False, default=SessionType.ONLINE, comment="面试类型")
    status = Column(Enum(SessionStatus), nullable=False, default=SessionStatus.SCHEDULED, comment="面试状态")
    scheduled_start_at = Column(DateTime, comment="面试预定开始时间")
    scheduled_end_at = Column(DateTime, comment="面试预定结束时间")
    started_at = Column(DateTime, comment="实际开始时间")
    ended_at = Column(DateTime, comment="实际结束时间")
    notes = Column(Text, comment="备注")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="会话创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="会话更新时间")
    
    # 逻辑关联关系
    # 与User的关系（多对一，作为候选人）
    # 与User的关系（多对一，作为招聘官）
    # 与Resume的关系（多对一）
    # 与InterviewSessionQuestion的关系（一对多）
    # 与InterviewSessionStandard的关系（一对多）
    # 与InterviewEvaluation的关系（一对多）
    # 与InterviewReport的关系（一对多）
    # 与InterviewReminder的关系（一对多）
    # 与InterviewAudioTranscript的关系（一对多）


class InterviewSessionQuestion(Base):
    """面试会话问题表"""
    __tablename__ = "interview_session_question"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="ID")
    session_id = Column(Integer, nullable=False, comment="面试会话ID")
    question_id = Column(Integer, nullable=False, comment="题目ID")
    sort = Column(Integer, nullable=False, default=0, comment="题目顺序")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    
    # 逻辑关联关系
    # 与InterviewSession的关系（多对一）
    # 与InterviewQuestion的关系（多对一）


class InterviewSessionStandard(Base):
    """面试会话评估标准表"""
    __tablename__ = "interview_session_standard"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="ID")
    session_id = Column(Integer, nullable=False, comment="面试会话ID")
    standard_id = Column(Integer, nullable=False, comment="评估标准ID")
    score = Column(Integer, comment="分数")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    
    # 逻辑关联关系
    # 与InterviewSession的关系（多对一）
    # 与EvaluationStandard的关系（多对一）


class InterviewEvaluation(Base):
    """面试评估表"""
    __tablename__ = "interview_evaluation"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="面试评估ID")
    session_id = Column(Integer, nullable=False, comment="面试会话ID")
    evaluator_id = Column(Integer, nullable=False, comment="评估人ID")
    overall_score = Column(String(20), comment="总体评分")
    recommendation = Column(Enum(Recommendation), comment="推荐意见")
    comments = Column(Text, comment="评估文本")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 逻辑关联关系
    # 与InterviewSession的关系（多对一）
    # 与User的关系（多对一，作为评估人）


class InterviewReport(Base):
    """面试报告表"""
    __tablename__ = "interview_report"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="面试报告ID")
    session_id = Column(Integer, nullable=False, comment="面试会话ID")
    report_content = Column(Text, comment="报告内容")
    generated_at = Column(DateTime, comment="生成时间")
    status = Column(Enum(ReportStatus), nullable=False, default=ReportStatus.DRAFT, comment="状态")
    
    # 逻辑关联关系
    # 与InterviewSession的关系（多对一）


class InterviewReminder(Base):
    """面试提醒表"""
    __tablename__ = "interview_reminder"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="面试提醒ID")
    session_id = Column(Integer, nullable=False, comment="面试会话ID")
    user_id = Column(Integer, nullable=False, comment="用户ID")
    reminder_time = Column(DateTime, nullable=False, comment="提醒时间")
    message = Column(Text, comment="提醒内容")
    status = Column(Enum(ReminderStatus), nullable=False, default=ReminderStatus.PENDING, comment="状态")
    send_method = Column(Enum(SendMethod), nullable=False, default=SendMethod.SYSTEM, comment="发送方式")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 逻辑关联关系
    # 与InterviewSession的关系（多对一）
    # 与User的关系（多对一）
