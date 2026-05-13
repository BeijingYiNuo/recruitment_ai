from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from assistant.config.database import get_db
from assistant.entity import InterviewSession, InterviewSessionRound, PositionRound
from assistant.enums import SessionStatus
from assistant.entity import User
from assistant.entity.DTO import (
    InterviewSessionCreate, InterviewSessionUpdate,
    InterviewSessionQuestionCreate, InterviewSessionStandardCreate,
    InterviewEvaluationCreate, InterviewEvaluationUpdate,
    SessionRoundUpdate
)
from assistant.entity.VO import (
    InterviewSessionResponse, InterviewSessionQuestionResponse,
    InterviewSessionStandardResponse, InterviewEvaluationResponse,
    SessionRoundResponse
)
from assistant.api.interview_reserve_utils import create_interview_session as create_session
from assistant.api.interview_reserve_utils import update_interview_session as update_session
from assistant.api.interview_reserve_utils import delete_interview_session as delete_session
from assistant.user_management.auth_middleware import get_current_user_id

router = APIRouter(prefix="/api/reserve", tags=["面试预约"])

# 面试会话预约相关接口
@router.post("/sessions", response_model=InterviewSessionResponse, status_code=status.HTTP_201_CREATED)
def create_interview_session(
    session: InterviewSessionCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """创建面试会话"""
    return create_session(db, current_user_id, session)



@router.get("/sessions", response_model=List[InterviewSessionResponse])
def get_interview_sessions_by_user(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    """根据用户ID获取所有面试会话"""
    sessions = db.query(InterviewSession).filter(InterviewSession.recruiter_id == current_user_id).all()
    return sessions

@router.get("/sessions/{session_id}", response_model=InterviewSessionResponse)
def get_interview_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    """根据用户ID获取所有面试会话"""
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id, InterviewSession.recruiter_id == current_user_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该面试会话不存在"
        )
    return session




@router.put("/sessions/{session_id}", response_model=InterviewSessionResponse)
def update_interview_session(
    session_id: int,
    session: InterviewSessionUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    return update_session(db, current_user_id, session_id, session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interview_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """删除面试会话"""
    delete_session(db, current_user_id, session_id)
    return None


# ====== 面试轮次状态管理 ======

@router.get("/sessions/{session_id}/rounds", response_model=List[SessionRoundResponse])
def get_session_rounds(
    session_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取面试会话的所有轮次状态"""
    session = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.recruiter_id == current_user_id
    ).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在"
        )
    rounds = db.query(InterviewSessionRound).filter(
        InterviewSessionRound.session_id == session_id
    ).order_by(InterviewSessionRound.round_number).all()
    return rounds


@router.patch("/sessions/{session_id}/rounds/{round_id}", response_model=SessionRoundResponse)
def update_session_round(
    session_id: int,
    round_id: int,
    update_data: SessionRoundUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """更新面试轮次状态（通过/未通过/跳过）"""
    session = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.recruiter_id == current_user_id
    ).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在"
        )
    session_round = db.query(InterviewSessionRound).filter(
        InterviewSessionRound.id == round_id,
        InterviewSessionRound.session_id == session_id
    ).first()
    if not session_round:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该轮次记录不存在"
        )

    if update_data.status not in ("pass", "fail", "skip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="状态值必须为: pass/fail/skip"
        )

    session_round.status = update_data.status
    if update_data.score is not None:
        session_round.score = update_data.score
    if update_data.comment is not None:
        session_round.comment = update_data.comment
    if update_data.status in ("pass", "fail"):
        from datetime import datetime
        session_round.evaluated_at = datetime.now()

    db.commit()
    db.refresh(session_round)

    # 检查是否所有轮次都已评估，全部完成则将会话置为已完成
    all_rounds = db.query(InterviewSessionRound).filter(
        InterviewSessionRound.session_id == session_id
    ).all()
    if all_rounds and all(r.status in ("pass", "fail", "skip") for r in all_rounds):
        session.status = SessionStatus.COMPLETED
        session.ended_at = datetime.now()
        db.commit()

    return session_round


@router.post("/sessions/{session_id}/sync-rounds", response_model=List[SessionRoundResponse])
def sync_session_rounds(
    session_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """同步面试轮次，使其与岗位最新面试流程设置一致"""
    session = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.recruiter_id == current_user_id
    ).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在"
        )
    if not session.position_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该面试未关联岗位，无法同步"
        )

    # 获取岗位最新轮次
    position_rounds = db.query(PositionRound).filter(
        PositionRound.position_id == session.position_id
    ).order_by(PositionRound.round_number).all()

    # 获取现有面试轮次
    existing_rounds = db.query(InterviewSessionRound).filter(
        InterviewSessionRound.session_id == session_id
    ).all()
    existing_by_round_id = {r.round_id: r for r in existing_rounds}

    # 记录新轮次ID集合
    current_position_round_ids = {pr.id for pr in position_rounds}

    # 1. 新增轮次 / 更新已有轮次的信息（仅当未评估时）
    for pr in position_rounds:
        if pr.id in existing_by_round_id:
            er = existing_by_round_id[pr.id]
            if er.status == 'pending':
                er.round_name = pr.round_name
                er.round_type = pr.round_type.value if hasattr(pr.round_type, 'value') else pr.round_type
                er.round_number = pr.round_number
        else:
            session_round = InterviewSessionRound(
                session_id=session_id,
                round_id=pr.id,
                round_name=pr.round_name,
                round_type=pr.round_type.value if hasattr(pr.round_type, 'value') else pr.round_type,
                round_number=pr.round_number,
                status="pending"
            )
            db.add(session_round)

    # 2. 删除不再存在于岗位中且状态为 pending 的轮次
    for er in existing_rounds:
        if er.status == 'pending' and er.round_id not in current_position_round_ids:
            db.delete(er)

    db.commit()

    # 返回更新后的轮次列表
    rounds = db.query(InterviewSessionRound).filter(
        InterviewSessionRound.session_id == session_id
    ).order_by(InterviewSessionRound.round_number).all()
    return rounds

