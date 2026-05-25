from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from assistant.config.database import get_db
from assistant.entity.position import Position, PositionRound
from assistant.entity.DTO.position_dto import (
    PositionCreate, PositionUpdate,
    PositionRoundCreate, PositionRoundUpdate, PositionRoundReorder
)
from assistant.entity.VO.position_vo import (
    PositionResponse, PositionListResponse, PositionRoundResponse
)
from assistant.user_management.auth_middleware import get_current_user_id
from assistant.utils.logger import logger

router = APIRouter(prefix="/api/positions", tags=["岗位管理"])


# ========== 岗位 CRUD ==========

@router.get("")
def list_positions(
    skip: int = 0,
    limit: int = 100,
    keyword: str = "",
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取岗位列表（仅当前用户创建的岗位），支持搜索和分页"""
    query = db.query(Position).filter(
        Position.created_by == current_user_id
    )

    if keyword:
        query = query.filter(Position.name.ilike(f"%{keyword}%"))

    query = query.order_by(Position.created_at.desc())
    total = query.count()
    positions = query.offset(skip).limit(limit).all()

    result = []
    for pos in positions:
        round_count = db.query(PositionRound).filter(
            PositionRound.position_id == pos.id
        ).count()
        result.append(PositionListResponse(
            id=pos.id,
            name=pos.name,
            department=pos.department,
            status=pos.status,
            round_count=round_count,
            created_at=pos.created_at,
        ))
    return {"items": result, "total": total}


@router.post("", response_model=PositionResponse, status_code=status.HTTP_201_CREATED)
def create_position(
    data: PositionCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """创建岗位（可选附带面试轮次）"""
    position = Position(
        name=data.name,
        department=data.department,
        description=data.description,
        requirements=data.requirements,
        salary_range=data.salary_range,
        created_by=current_user_id,
    )
    db.add(position)
    db.commit()
    db.refresh(position)

    # 创建面试轮次
    rounds = []
    for i, round_data in enumerate(data.rounds, start=1):
        pr = PositionRound(
            position_id=position.id,
            round_number=i,
            round_name=round_data.round_name,
            round_type=round_data.round_type,
            duration_minutes=round_data.duration_minutes,
            description=round_data.description,
        )
        db.add(pr)
        rounds.append(pr)

    if rounds:
        db.commit()
        for pr in rounds:
            db.refresh(pr)

    logger.info(f"User {current_user_id} created position {position.id}: {position.name}")
    return _build_position_response(position, rounds)


@router.get("/{position_id}", response_model=PositionResponse)
def get_position(
    position_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取岗位详情（含面试轮次）"""
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.created_by == current_user_id
    ).first()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")

    rounds = db.query(PositionRound).filter(
        PositionRound.position_id == position_id
    ).order_by(PositionRound.round_number).all()

    return _build_position_response(position, rounds)


@router.put("/{position_id}", response_model=PositionResponse)
def update_position(
    position_id: int,
    data: PositionUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """更新岗位信息"""
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.created_by == current_user_id
    ).first()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(position, key, value)

    db.commit()
    db.refresh(position)

    rounds = db.query(PositionRound).filter(
        PositionRound.position_id == position_id
    ).order_by(PositionRound.round_number).all()

    logger.info(f"User {current_user_id} updated position {position_id}")
    return _build_position_response(position, rounds)


@router.delete("/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position(
    position_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """删除岗位（同步删除关联的面试轮次）"""
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.created_by == current_user_id
    ).first()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")

    # 删除关联轮次
    db.query(PositionRound).filter(PositionRound.position_id == position_id).delete()
    db.delete(position)
    db.commit()

    logger.info(f"User {current_user_id} deleted position {position_id}")


# ========== 面试轮次 CRUD ==========

@router.get("/{position_id}/rounds", response_model=List[PositionRoundResponse])
def list_rounds(
    position_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取岗位的所有面试轮次"""
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.created_by == current_user_id
    ).first()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")

    rounds = db.query(PositionRound).filter(
        PositionRound.position_id == position_id
    ).order_by(PositionRound.round_number).all()
    return rounds


@router.post("/{position_id}/rounds", response_model=PositionRoundResponse, status_code=status.HTTP_201_CREATED)
def create_round(
    position_id: int,
    data: PositionRoundCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """为岗位新增一个面试轮次（追加到最后）"""
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.created_by == current_user_id
    ).first()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")

    # 获取当前最大序号
    max_round = db.query(PositionRound).filter(
        PositionRound.position_id == position_id
    ).order_by(PositionRound.round_number.desc()).first()

    next_number = (max_round.round_number + 1) if max_round else 1

    pr = PositionRound(
        position_id=position_id,
        round_number=next_number,
        round_name=data.round_name,
        round_type=data.round_type,
        duration_minutes=data.duration_minutes,
        description=data.description,
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    logger.info(f"User {current_user_id} added round {pr.id} to position {position_id}")
    return pr


@router.put("/{position_id}/rounds/{round_id}", response_model=PositionRoundResponse)
def update_round(
    position_id: int,
    round_id: int,
    data: PositionRoundUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """更新面试轮次信息"""
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.created_by == current_user_id
    ).first()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")

    pr = db.query(PositionRound).filter(
        PositionRound.id == round_id,
        PositionRound.position_id == position_id
    ).first()
    if not pr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="面试轮次不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(pr, key, value)

    db.commit()
    db.refresh(pr)
    return pr


@router.delete("/{position_id}/rounds/{round_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_round(
    position_id: int,
    round_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """删除面试轮次（自动重排剩余轮次序号）"""
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.created_by == current_user_id
    ).first()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")

    pr = db.query(PositionRound).filter(
        PositionRound.id == round_id,
        PositionRound.position_id == position_id
    ).first()
    if not pr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="面试轮次不存在")

    deleted_number = pr.round_number
    db.delete(pr)

    # 重排后续轮次的序号
    remaining = db.query(PositionRound).filter(
        PositionRound.position_id == position_id,
        PositionRound.round_number > deleted_number
    ).order_by(PositionRound.round_number).all()

    for r in remaining:
        r.round_number -= 1

    db.commit()
    logger.info(f"User {current_user_id} deleted round {round_id} from position {position_id}")


@router.put("/{position_id}/rounds/reorder", response_model=List[PositionRoundResponse])
def reorder_rounds(
    position_id: int,
    data: PositionRoundReorder,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """重排面试轮次顺序"""
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.created_by == current_user_id
    ).first()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")

    # 校验所有 round_id 都属于该岗位
    existing = db.query(PositionRound).filter(
        PositionRound.position_id == position_id
    ).all()
    existing_ids = {r.id for r in existing}

    if set(data.round_ids) != existing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="轮次ID列表与岗位现有轮次不匹配"
        )

    # 按新顺序重排 round_number
    for i, round_id in enumerate(data.round_ids, start=1):
        db.query(PositionRound).filter(PositionRound.id == round_id).update(
            {"round_number": i}
        )

    db.commit()

    rounds = db.query(PositionRound).filter(
        PositionRound.position_id == position_id
    ).order_by(PositionRound.round_number).all()
    return rounds


# ========== 内部辅助 ==========

def _build_position_response(position: Position, rounds: list[PositionRound]) -> PositionResponse:
    """构建岗位响应（含轮次列表）"""
    return PositionResponse(
        id=position.id,
        name=position.name,
        department=position.department,
        description=position.description,
        requirements=position.requirements,
        salary_range=position.salary_range,
        status=position.status,
        created_by=position.created_by,
        created_at=position.created_at,
        updated_at=position.updated_at,
        rounds=[
            PositionRoundResponse(
                id=r.id,
                position_id=r.position_id,
                round_number=r.round_number,
                round_name=r.round_name,
                round_type=r.round_type,
                duration_minutes=r.duration_minutes,
                description=r.description,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rounds
        ],
    )
