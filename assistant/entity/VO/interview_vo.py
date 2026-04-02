from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from assistant.enums import SessionType, SessionStatus, Recommendation, ReminderStatus, SendMethod, ReportStatus


class InterviewSessionResponse(BaseModel):
    """面试会话响应模型"""
    id: int
    candidate_name: str
    recruiter_id: int
    resume_id: int
    session_type: SessionType
    status: SessionStatus
    scheduled_start_at: datetime
    scheduled_end_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    



    class Config:
        from_attributes = True


class InterviewSessionQuestionResponse(BaseModel):
    """面试会话问题响应模型"""
    id: int
    session_id: int
    question_id: int
    sort: int
    created_at: datetime

    class Config:
        from_attributes = True


class InterviewSessionStandardResponse(BaseModel):
    """面试会话评估标准响应模型"""
    id: int
    session_id: int
    standard_id: int
    score: int
    created_at: datetime

    class Config:
        from_attributes = True


class InterviewEvaluationResponse(BaseModel):
    """面试评估响应模型"""
    id: int
    session_id: int
    evaluator_id: int
    overall_score: str
    recommendation: Recommendation
    comments: str = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InterviewReportResponse(BaseModel):
    """面试报告响应模型"""
    id: int
    session_id: int
    report_content: str
    generated_at: datetime
    status: ReportStatus

    class Config:
        from_attributes = True


class InterviewReminderResponse(BaseModel):
    """面试提醒响应模型"""
    id: int
    session_id: int
    user_id: int
    reminder_time: datetime
    message: str
    status: ReminderStatus
    send_method: SendMethod
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
