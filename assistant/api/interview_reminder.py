# 面试提醒相关接口
@router.get("/interviews/reminders", response_model=List[InterviewReminderResponse])
def get_interview_reminders(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取面试提醒列表"""
    reminders = db.query(InterviewReminder).offset(skip).limit(limit).all()
    return reminders


@router.get("/interviews/reminders/{reminder_id}", response_model=InterviewReminderResponse)
def get_interview_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取单个面试提醒"""
    reminder = db.query(InterviewReminder).filter(InterviewReminder.id == reminder_id).first()
    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试提醒不存在"
        )
    return reminder


@router.post("/interviews/reminders", response_model=InterviewReminderResponse, status_code=status.HTTP_201_CREATED)
def create_interview_reminder(
    reminder: InterviewReminderCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """创建面试提醒"""
    # 检查面试会话是否存在
    session = db.query(InterviewSession).filter(InterviewSession.id == reminder.session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在"
        )
    
    db_reminder = InterviewReminder(
        session_id=reminder.session_id,
        user_id=reminder.user_id,
        reminder_time=reminder.reminder_time,
        message=reminder.message,
        status=ReminderStatus.PENDING,
        send_method=reminder.send_method
    )
    
    db.add(db_reminder)
    db.commit()
    db.refresh(db_reminder)
    
    return db_reminder


@router.put("/interviews/reminders/{reminder_id}", response_model=InterviewReminderResponse)
def update_interview_reminder(
    reminder_id: int,
    reminder: InterviewReminderUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    
    """更新面试提醒"""
    db_reminder = db.query(InterviewReminder).filter(InterviewReminder.id == reminder_id).first()
    if not db_reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试提醒不存在"
        )
    
    update_data = reminder.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_reminder, key, value)
    
    db.commit()
    db.refresh(db_reminder)
    
    return db_reminder
