# 面试报告相关接口
@router.get("/interviews/reports", response_model=List[InterviewReportResponse])
def get_interview_reports(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取面试报告列表"""
    reports = db.query(InterviewReport).offset(skip).limit(limit).all()
    return reports


@router.get("/interviews/reports/{report_id}", response_model=InterviewReportResponse)
def get_interview_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取单个面试报告"""
    report = db.query(InterviewReport).filter(InterviewReport.id == report_id).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试报告不存在"
        )
    return report


@router.post("/interviews/reports", response_model=InterviewReportResponse, status_code=status.HTTP_201_CREATED)
def create_interview_report(
    report: InterviewReportCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """创建面试报告"""
    # 检查面试会话是否存在
    session = db.query(InterviewSession).filter(InterviewSession.id == report.session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在"
        )
    
    db_report = InterviewReport(
        session_id=report.session_id,
        report_content=report.report_content,
        status=report.status
    )
    
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    
    return db_report


@router.put("/interviews/reports/{report_id}", response_model=InterviewReportResponse)
def update_interview_report(
    report_id: int,
    report: InterviewReportUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """更新面试报告"""
    db_report = db.query(InterviewReport).filter(InterviewReport.id == report_id).first()
    if not db_report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试报告不存在"
        )
    
    update_data = report.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_report, key, value)
    
    db.commit()
    db.refresh(db_report)
    
    return db_report
