from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
from assistant.enums import SessionType, Recommendation, ReportStatus, SendMethod



class InterviewSessionCreate(BaseModel):
    """面试会话创建模型"""
    candidate_name: str
    recruiter_id: int
    resume_id: int
    session_type: SessionType
    scheduled_start_at: str
    scheduled_end_at: str
    notes: Optional[str] = None
    
    @field_validator('scheduled_start_at', 'scheduled_end_at')
    @classmethod
    def validate_datetime_format(cls, v):
        """验证日期时间格式：YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS"""
        try:
            # 尝试解析不包含秒的格式
            datetime.strptime(v, '%Y-%m-%d %H:%M')
        except ValueError:
            try:
                # 尝试解析包含秒的格式
                datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                raise ValueError('日期时间格式必须为：YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS')
        return v


class InterviewSessionUpdate(BaseModel):
    """面试会话更新模型"""
    candidate_name: Optional[str] = None
    recruiter_id: Optional[int] = None
    resume_id: Optional[int] = None
    session_type: Optional[SessionType] = None
    status: Optional[str] = None
    scheduled_start_at: Optional[str] = None
    scheduled_end_at: Optional[str] = None
    started_at: Optional[str] = None 
    ended_at: Optional[str] = None
    notes: Optional[str] = None
    
    @field_validator('scheduled_start_at', 'scheduled_end_at', 'started_at', 'ended_at')
    @classmethod
    def validate_datetime_format(cls, v):
        """验证日期时间格式：YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS"""
        if v is None:
            return v
        try:
            # 尝试解析不包含秒的格式
            datetime.strptime(v, '%Y-%m-%d %H:%M')
        except ValueError:
            try:
                # 尝试解析包含秒的格式
                datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                raise ValueError('日期时间格式必须为：YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS')
        return v


class InterviewSessionQuestionCreate(BaseModel):
    """面试会话问题创建模型"""
    session_id: int
    question_id: int
    sort: int


class InterviewSessionStandardCreate(BaseModel):
    """面试会话评估标准创建模型"""
    session_id: int
    standard_id: int
    score: int


class InterviewEvaluationCreate(BaseModel):
    """面试评估创建模型"""
    session_id: int
    evaluator_id: int
    overall_score: str
    recommendation: Recommendation
    comments: str = None


class InterviewEvaluationUpdate(BaseModel):
    """面试评估更新模型"""
    evaluator_id: int = None
    overall_score: str = None
    recommendation: Recommendation = None
    comments: str = None


class InterviewReportCreate(BaseModel):
    """面试报告创建模型"""
    session_id: int
    report_content: str
    status: ReportStatus = ReportStatus.DRAFT


class InterviewReportUpdate(BaseModel):
    """面试报告更新模型"""
    report_content: str = None
    status: ReportStatus = None


class InterviewReminderCreate(BaseModel):
    """面试提醒创建模型"""
    session_id: int
    user_id: int
    reminder_time: datetime
    message: str
    send_method: SendMethod


class InterviewReminderUpdate(BaseModel):
    """面试提醒更新模型"""
    user_id: int = None
    reminder_time: datetime = None
    message: str = None
    status: str = None
    send_method: SendMethod = None
