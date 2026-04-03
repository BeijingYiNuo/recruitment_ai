from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from assistant.entity import InterviewSession, User
from assistant.enums import SessionStatus
from assistant.entity.DTO import InterviewSessionCreate, InterviewSessionUpdate


def validate_user_exists(db: Session, user_id: int) -> bool:
    """
    验证用户是否存在
    
    Args:
        db: 数据库会话
        user_id: 用户ID
    
    Returns:
        bool: 用户是否存在
    """
    user = db.query(User).filter(User.id == user_id).first()
    return user is not None


def check_time_conflict(db: Session, scheduled_start_at: str, scheduled_end_at: str, recruiter_id: int, session_id: int = None) -> bool:
    """
    检查面试时间和招聘官是否冲突
    
    Args:
        db: 数据库会话
        scheduled_start_at: 预约开始时间（字符串格式：YYYY-MM-DD HH:MM）
        scheduled_end_at: 预约结束时间（字符串格式：YYYY-MM-DD HH:MM）
        recruiter_id: 招聘官ID
        session_id: 面试会话ID（用于更新时排除自身）
    
    Returns:
        bool: 是否存在冲突
    """
    # 将字符串时间转换为 datetime 对象
    try:
        # 尝试解析不包含秒的格式
        start_time = datetime.strptime(scheduled_start_at, '%Y-%m-%d %H:%M')
        end_time = datetime.strptime(scheduled_end_at, '%Y-%m-%d %H:%M')
    except ValueError:
        # 尝试解析包含秒的格式
        start_time = datetime.strptime(scheduled_start_at, '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(scheduled_end_at, '%Y-%m-%d %H:%M:%S')
    
    # 构建查询，检查招聘官的时间冲突
    query = db.query(InterviewSession).filter(
        InterviewSession.recruiter_id == recruiter_id,
        InterviewSession.status.in_([SessionStatus.SCHEDULED, SessionStatus.ONGOING])
    )
    
    # 如果是更新操作，排除自身
    if session_id:
        query = query.filter(InterviewSession.id != session_id)
    
    # 检查时间冲突
    # 冲突情况：
    # 1. 新预约的开始时间在现有预约的时间范围内
    # 2. 新预约的结束时间在现有预约的时间范围内
    # 3. 新预约的时间范围完全包含现有预约
    # 4. 现有预约的时间范围完全包含新预约
    conflicts = query.filter(
        (
            (InterviewSession.scheduled_start_at <= start_time) & 
            (InterviewSession.scheduled_end_at > start_time)
        ) | (
            (InterviewSession.scheduled_start_at < end_time) & 
            (InterviewSession.scheduled_end_at >= end_time)
        ) | (
            (InterviewSession.scheduled_start_at >= start_time) & 
            (InterviewSession.scheduled_end_at <= end_time)
        )
    ).first()
    
    return conflicts is not None


def create_interview_session(db: Session, user_id: int, session_data: InterviewSessionCreate) -> InterviewSession:
    """
    创建面试会话
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        session_data: 面试会话数据
    
    Returns:
        InterviewSession: 创建的面试会话
    """
    # 1. 首先查看 user_id 是否合法
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 2. 合法就把 user_id 作为 recruiter_id
    recruiter_id = user_id
    
    # 3. 检查新建会话的预约时间和 recruiter_id 已有的预约时间是否冲突
    if check_time_conflict(db, session_data.scheduled_start_at, session_data.scheduled_end_at, recruiter_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="面试时间和招聘官与现有预约冲突"
        )
    
    # 将字符串时间转换为 datetime 对象
    try:
        # 尝试解析不包含秒的格式
        start_time = datetime.strptime(session_data.scheduled_start_at, '%Y-%m-%d %H:%M')
        end_time = datetime.strptime(session_data.scheduled_end_at, '%Y-%m-%d %H:%M')
    except ValueError:
        # 尝试解析包含秒的格式
        start_time = datetime.strptime(session_data.scheduled_start_at, '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(session_data.scheduled_end_at, '%Y-%m-%d %H:%M:%S')
    
    # 5. 如果没有出现问题则写入数据库
    # 创建面试会话
    db_session = InterviewSession(
        candidate_name=session_data.candidate_name,
        recruiter_id=recruiter_id,
        resume_id=session_data.resume_id,
        session_type=session_data.session_type,
        status=SessionStatus.SCHEDULED,
        scheduled_start_at=start_time,
        scheduled_end_at=end_time,
        notes=session_data.notes
    )
    
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    
    return db_session


def update_interview_session(db: Session, user_id: int, session_id: int, session_data: InterviewSessionUpdate) -> InterviewSession:
    """
    更新面试会话
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        session_id: 面试会话ID
        session_data: 面试会话更新数据
    
    Returns:
        InterviewSession: 更新后的面试会话
    """
    # 1. 验证用户是否存在
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 2. 检查面试会话是否存在
    db_session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在"
        )
    
    # 3. 如果更新了时间，检查时间冲突
    if session_data.scheduled_start_at and session_data.scheduled_end_at:
        if check_time_conflict(db, session_data.scheduled_start_at, session_data.scheduled_end_at, user_id, session_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="面试时间和招聘官与现有预约冲突"
            )
        
        # 将字符串时间转换为 datetime 对象
        try:
            # 尝试解析不包含秒的格式
            start_time = datetime.strptime(session_data.scheduled_start_at, '%Y-%m-%d %H:%M')
            end_time = datetime.strptime(session_data.scheduled_end_at, '%Y-%m-%d %H:%M')
        except ValueError:
            # 尝试解析包含秒的格式
            start_time = datetime.strptime(session_data.scheduled_start_at, '%Y-%m-%d %H:%M:%S')
            end_time = datetime.strptime(session_data.scheduled_end_at, '%Y-%m-%d %H:%M:%S')
        
        # 直接更新数据库对象的字段，而不是修改 session_data
        db_session.scheduled_start_at = start_time
        db_session.scheduled_end_at = end_time
    
    # 4. 更新面试会话的其他字段
    update_data = session_data.dict(exclude_unset=True, exclude={'scheduled_start_at', 'scheduled_end_at'})
    for key, value in update_data.items():
        setattr(db_session, key, value)
    
    db.commit()
    db.refresh(db_session)
    
    return db_session


def delete_interview_session(db: Session, user_id: int, session_id: int) -> None:
    """
    删除面试会话
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        session_id: 面试会话ID
    """
    # 1. 验证用户是否存在
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 2. 检查面试会话是否存在
    db_session = db.query(InterviewSession).filter(InterviewSession.id == session_id, InterviewSession.recruiter_id == user_id).first()
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在"
        )
    
    # 3. 检查该面试会话是否属于该用户
    if db_session.recruiter_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权删除该面试会话"
        )
    
    # 4. 删除面试会话
    db.delete(db_session)
    db.commit()