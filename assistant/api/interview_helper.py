from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from assistant.config.database import get_db
from assistant.entity import InterviewQuestion, QuestionType, EvaluationStandard, InterviewAudioTranscript
from assistant.entity.DTO import (
    InterviewQuestionCreate, InterviewQuestionUpdate,
    EvaluationStandardCreate, EvaluationStandardUpdate,
    InterviewAudioTranscriptCreate, InterviewAudioTranscriptUpdate
)
from assistant.entity.VO import (
    InterviewQuestionResponse, EvaluationStandardResponse,
    InterviewAudioTranscriptResponse
)
from assistant.user_management.auth_middleware import get_current_user_id

router = APIRouter(prefix="/api/interview-helper", tags=["面试辅助"])


# 面试问题相关接口
@router.get("/questions", response_model=List[InterviewQuestionResponse])
def get_interview_questions(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取面试问题列表"""
    questions = db.query(InterviewQuestion).offset(skip).limit(limit).all()
    return questions


@router.get("/questions/{question_id}", response_model=InterviewQuestionResponse)
def get_interview_question(
    question_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取单个面试问题"""
    question = db.query(InterviewQuestion).filter(InterviewQuestion.id == question_id).first()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试问题不存在"
        )
    return question


@router.post("/questions", response_model=InterviewQuestionResponse, status_code=status.HTTP_201_CREATED)
def create_interview_question(
    question: InterviewQuestionCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """创建面试问题"""
    db_question = InterviewQuestion(**question.dict())
    db.add(db_question)
    db.commit()
    db.refresh(db_question)
    
    return db_question


@router.put("/questions/{question_id}", response_model=InterviewQuestionResponse)
def update_interview_question(
    question_id: int,
    question: InterviewQuestionUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """更新面试问题"""
    db_question = db.query(InterviewQuestion).filter(InterviewQuestion.id == question_id).first()
    if not db_question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试问题不存在"
        )
    
    update_data = question.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_question, key, value)
    
    db.commit()
    db.refresh(db_question)
    
    return db_question


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interview_question(
    question_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """删除面试问题"""
    db_question = db.query(InterviewQuestion).filter(InterviewQuestion.id == question_id).first()
    if not db_question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试问题不存在"
        )
    
    db.delete(db_question)
    db.commit()
    
    return None


# 评估标准相关接口
@router.get("/standards", response_model=List[EvaluationStandardResponse])
def get_evaluation_standards(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取评估标准列表"""
    standards = db.query(EvaluationStandard).offset(skip).limit(limit).all()
    return standards


@router.get("/standards/{standard_id}", response_model=EvaluationStandardResponse)
def get_evaluation_standard(
    standard_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取单个评估标准"""
    standard = db.query(EvaluationStandard).filter(EvaluationStandard.id == standard_id).first()
    if not standard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="评估标准不存在"
        )
    return standard


@router.post("/standards", response_model=EvaluationStandardResponse, status_code=status.HTTP_201_CREATED)
def create_evaluation_standard(
    standard: EvaluationStandardCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """创建评估标准"""
    db_standard = EvaluationStandard(**standard.dict())
    db.add(db_standard)
    db.commit()
    db.refresh(db_standard)
    
    return db_standard


@router.put("/standards/{standard_id}", response_model=EvaluationStandardResponse)
def update_evaluation_standard(
    standard_id: int,
    standard: EvaluationStandardUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """更新评估标准"""
    db_standard = db.query(EvaluationStandard).filter(EvaluationStandard.id == standard_id).first()
    if not db_standard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="评估标准不存在"
        )
    
    update_data = standard.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_standard, key, value)
    
    db.commit()
    db.refresh(db_standard)
    
    return db_standard


@router.delete("/standards/{standard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluation_standard(
    standard_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """删除评估标准"""
    db_standard = db.query(EvaluationStandard).filter(EvaluationStandard.id == standard_id).first()
    if not db_standard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="评估标准不存在"
        )
    
    db.delete(db_standard)
    db.commit()
    
    return None


# 面试音频转写相关接口
@router.get("/transcripts", response_model=List[InterviewAudioTranscriptResponse])
def get_interview_audio_transcripts(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取面试音频转写列表"""
    transcripts = db.query(InterviewAudioTranscript).offset(skip).limit(limit).all()
    return transcripts


@router.get("/transcripts/{transcript_id}", response_model=InterviewAudioTranscriptResponse)
def get_interview_audio_transcript(
    transcript_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取单个面试音频转写"""
    transcript = db.query(InterviewAudioTranscript).filter(InterviewAudioTranscript.id == transcript_id).first()
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试音频转写不存在"
        )
    return transcript


@router.post("/transcripts", response_model=InterviewAudioTranscriptResponse, status_code=status.HTTP_201_CREATED)
def create_interview_audio_transcript(
    transcript: InterviewAudioTranscriptCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """创建面试音频转写"""
    db_transcript = InterviewAudioTranscript(**transcript.dict())
    db.add(db_transcript)
    db.commit()
    db.refresh(db_transcript)
    
    return db_transcript


@router.put("/transcripts/{transcript_id}", response_model=InterviewAudioTranscriptResponse)
def update_interview_audio_transcript(
    transcript_id: int,
    transcript: InterviewAudioTranscriptUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """更新面试音频转写"""
    db_transcript = db.query(InterviewAudioTranscript).filter(InterviewAudioTranscript.id == transcript_id).first()
    if not db_transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试音频转写不存在"
        )
    
    update_data = transcript.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_transcript, key, value)
    
    db.commit()
    db.refresh(db_transcript)
    
    return db_transcript


@router.delete("/transcripts/{transcript_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interview_audio_transcript(
    transcript_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """删除面试音频转写"""
    db_transcript = db.query(InterviewAudioTranscript).filter(InterviewAudioTranscript.id == transcript_id).first()
    if not db_transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试音频转写不存在"
        )
    
    db.delete(db_transcript)
    db.commit()
    
    return None
