from pydantic import BaseModel
from assistant.enums import QuestionType


class InterviewQuestionCreate(BaseModel):
    """面试问题创建模型"""
    question_text: str
    question_type: QuestionType


class InterviewQuestionUpdate(BaseModel):
    """面试问题更新模型"""
    question_text: str = None
    question_type: QuestionType = None


class EvaluationStandardCreate(BaseModel):
    """评估标准创建模型"""
    name: str
    description: str = None


class EvaluationStandardUpdate(BaseModel):
    """评估标准更新模型"""
    name: str = None
    description: str = None


class InterviewAudioTranscriptCreate(BaseModel):
    """面试音频转写创建模型"""
    session_id: int
    content: str


class InterviewAudioTranscriptUpdate(BaseModel):
    """面试音频转写更新模型"""
    session_id: int = None
    content: str = None
