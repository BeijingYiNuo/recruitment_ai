from pydantic import BaseModel
from datetime import datetime
from assistant.enums import QuestionType


class InterviewQuestionResponse(BaseModel):
    """面试问题响应模型"""
    id: int
    question_text: str
    question_type: QuestionType
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EvaluationStandardResponse(BaseModel):
    """评估标准响应模型"""
    id: int
    name: str
    description: str = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InterviewAudioTranscriptResponse(BaseModel):
    """面试音频转写响应模型"""
    id: int
    session_id: int
    content: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
