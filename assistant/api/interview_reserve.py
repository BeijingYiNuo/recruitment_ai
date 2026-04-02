from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from assistant.config.database import get_db
from assistant.entity import InterviewSession
from assistant.enums import SessionStatus
from assistant.entity.DTO import (
    InterviewSessionCreate, InterviewSessionUpdate,
    InterviewSessionQuestionCreate, InterviewSessionStandardCreate,
    InterviewEvaluationCreate, InterviewEvaluationUpdate
)
from assistant.entity.VO import (
    InterviewSessionResponse, InterviewSessionQuestionResponse,
    InterviewSessionStandardResponse, InterviewEvaluationResponse
)
from assistant.api.interview_reserve_utils import create_interview_session as create_session
from assistant.api.interview_reserve_utils import update_interview_session as update_session
from assistant.api.interview_reserve_utils import delete_interview_session as delete_session
from assistant.user_management.auth_middleware import get_current_user_id

router = APIRouter(prefix="/api/reserve", tags=["面试预约"])

# 面试会话预约相关接口
@router.post("/sessions", response_model=InterviewSessionResponse, status_code=status.HTTP_201_CREATED)
def create_interview_session(
    user_id: int,
    session: InterviewSessionCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """创建面试会话"""
    return create_session(db, user_id, session)



@router.get("/sessions/user/{user_id}", response_model=List[InterviewSessionResponse])
def get_interview_sessions_by_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    """根据用户ID获取所有面试会话"""
    sessions = db.query(InterviewSession).filter(InterviewSession.recruiter_id == user_id).all()
    if not sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该用户没有面试会话"
        )
    return sessions




@router.put("/sessions/{session_id}", response_model=InterviewSessionResponse)
def update_interview_session(
    user_id: int,
    session_id: int,
    session: InterviewSessionUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    return update_session(db, user_id, session_id, session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interview_session(
    user_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """删除面试会话"""
    delete_session(db, user_id, session_id)
    return None

