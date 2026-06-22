import asyncio
import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from assistant.config.database import get_db
from assistant.entity import (
    InterviewSession, InterviewSessionRound, InterviewReport, ReportStatus
)
from assistant.entity.DTO import (
    InterviewReportCreate, InterviewReportUpdate
)
from assistant.entity.VO import (
    InterviewReportResponse
)
from assistant.user_management.auth_middleware import get_current_user_id
from assistant.report.report_manager import ReportManager
from assistant.utils.logger import logger
from assistant.enums import SessionStatus

router = APIRouter(prefix="/api/interviews/reports", tags=["面试报告"])

report_manager = ReportManager()


@router.get("/candidate-groups")
def get_candidate_groups(
    keyword: Optional[str] = Query(None, description="按候选人姓名搜索"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取按候选人分组的报告列表（用于文件夹根视图）"""
    # 查询当前用户已结束面试的候选人
    relevant_statuses = [
        SessionStatus.COMPLETED, SessionStatus.PASSED, SessionStatus.FAILED,
        SessionStatus.ONGOING, SessionStatus.SCHEDULED, SessionStatus.PENDING
    ]

    query = db.query(
        InterviewSession.candidate_name,
        InterviewSession.id.label("session_id"),
        InterviewSession.started_at,
        InterviewReport.id.label("report_id"),
        InterviewReport.round_id,
        InterviewReport.status.label("report_status"),
        InterviewReport.generated_at,
        InterviewSessionRound.round_name,
    ).outerjoin(
        InterviewReport,
        InterviewReport.session_id == InterviewSession.id
    ).outerjoin(
        InterviewSessionRound,
        (InterviewSessionRound.session_id == InterviewSession.id) &
        (InterviewReport.round_id == InterviewSessionRound.id)
    ).filter(
        InterviewSession.recruiter_id == current_user_id,
        InterviewSession.status.in_(relevant_statuses)
    )

    if keyword:
        query = query.filter(InterviewSession.candidate_name.ilike(f"%{keyword}%"))

    query = query.order_by(InterviewSession.started_at.desc())
    rows = query.all()

    # 按候选人聚合
    groups = {}
    for row in rows:
        name = row.candidate_name or "未知"
        if name not in groups:
            groups[name] = {
                "candidate_name": name,
                "sessions": [],
            }
        groups[name]["sessions"].append({
            "session_id": row.session_id,
            "round_id": row.round_id,
            "round_name": row.round_name,
            "interview_date": str(row.started_at.date()) if row.started_at else None,
            "report_id": row.report_id,
            "report_status": row.report_status.value if row.report_status else None,
            "generated_at": str(row.generated_at) if row.generated_at else None,
        })

    # 转换为列表，包含统计信息
    result = []
    for name, group in groups.items():
        sessions = group["sessions"]
        report_dates = [
            s["generated_at"] for s in sessions if s["generated_at"]
        ]
        latest_at = max(report_dates) if report_dates else None
        result.append({
            "candidate_name": name,
            "session_count": len(set(s["session_id"] for s in sessions)),
            "report_count": sum(1 for s in sessions if s["report_status"] == "final"),
            "latest_report_at": latest_at,
            "sessions": sessions,
        })

    # 按最新报告时间倒序
    result.sort(key=lambda x: x["latest_report_at"] or "", reverse=True)
    return result


@router.get("/by-candidate")
def get_reports_by_candidate(
    name: str = Query(..., description="候选人姓名"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """按候选人获取所有面试 session 及其报告状态"""
    relevant_statuses = [
        SessionStatus.COMPLETED, SessionStatus.PASSED, SessionStatus.FAILED,
        SessionStatus.ONGOING, SessionStatus.SCHEDULED, SessionStatus.PENDING
    ]

    sessions = db.query(InterviewSession).filter(
        InterviewSession.recruiter_id == current_user_id,
        InterviewSession.candidate_name == name,
        InterviewSession.status.in_(relevant_statuses)
    ).order_by(InterviewSession.started_at.desc()).all()

    result_sessions = []
    for session in sessions:
        # 获取轮次信息
        rounds = db.query(InterviewSessionRound).filter(
            InterviewSessionRound.session_id == session.id
        ).order_by(InterviewSessionRound.round_number).all()

        round_list = [
            {
                "round_id": r.id,
                "round_name": r.round_name,
                "round_number": r.round_number,
                "status": r.status,
            }
            for r in rounds
        ]

        # 获取报告
        reports = db.query(InterviewReport).filter(
            InterviewReport.session_id == session.id
        ).all()

        report_list = [
            {
                "report_id": r.id,
                "round_id": r.round_id,
                "status": r.status.value if r.status else None,
                "generated_at": str(r.generated_at) if r.generated_at else None,
            }
            for r in reports
        ]

        result_sessions.append({
            "session_id": session.id,
            "candidate_name": session.candidate_name,
            "interview_date": str(session.started_at.date()) if session.started_at else None,
            "session_status": session.status.value if session.status else None,
            "rounds": round_list,
            "reports": report_list,
        })

    return {
        "candidate_name": name,
        "sessions": result_sessions,
    }


@router.get("/list", response_model=List[InterviewReportResponse])
def get_interview_reports(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取面试报告列表"""
    reports = db.query(InterviewReport).offset(skip).limit(limit).all()
    return reports


@router.get("/{report_id}", response_model=InterviewReportResponse)
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


@router.get("/session/{session_id}", response_model=dict)
def get_report_by_session(
    session_id: int,
    round_id: int = Query(..., description="面试轮次 ID"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """根据面试会话 ID 和轮次 ID 获取报告（含结构化数据）"""
    # 验证 session 存在且有权限
    session = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.recruiter_id == current_user_id
    ).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在或用户没有权限访问"
        )

    report = db.query(InterviewReport).filter(
        InterviewReport.session_id == session_id,
        InterviewReport.round_id == round_id
    ).first()

    if not report:
        return {
            "id": None,
            "session_id": session_id,
            "round_id": round_id,
            "report_data": None,
            "status": "not_generated",
            "message": "报告尚未生成，请先触发生成",
        }

    report_data = None
    if report.report_data:
        try:
            report_data = json.loads(report.report_data)
        except json.JSONDecodeError:
            pass

    return {
        "id": report.id,
        "session_id": report.session_id,
        "round_id": report.round_id,
        "report_content": report.report_content,
        "report_data": report_data,
        "generated_at": str(report.generated_at) if report.generated_at else None,
        "status": report.status.value if report.status else None,
    }


@router.post("/generate/{session_id}", response_model=dict, status_code=status.HTTP_201_CREATED)
async def generate_interview_report(
    session_id: int,
    round_id: int = Query(..., description="面试轮次 ID"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """触发面试报告生成（后台异步任务，立即返回）"""
    # 验证 session 存在且有权限
    session = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.recruiter_id == current_user_id
    ).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在或用户没有权限访问"
        )

    # 1. 检查是否已有 final 报告（有数据则直接返回）
    existing = db.query(InterviewReport).filter(
        InterviewReport.session_id == session_id,
        InterviewReport.round_id == round_id
    ).first()

    if existing and existing.status == ReportStatus.FINAL and existing.report_data:
        report_data = None
        try:
            report_data = json.loads(existing.report_data)
        except json.JSONDecodeError:
            pass
        return {
            "id": existing.id,
            "session_id": existing.session_id,
            "round_id": existing.round_id,
            "report_content": existing.report_content,
            "report_data": report_data,
            "generated_at": str(existing.generated_at) if existing.generated_at else None,
            "status": "final",
        }

    # 2. 如果正在生成中且未超时，直接返回生成中状态
    now = datetime.now()
    if existing and existing.status == ReportStatus.GENERATING:
        if existing.generated_at and (now - existing.generated_at).total_seconds() < 300:
            return {
                "id": existing.id,
                "session_id": existing.session_id,
                "round_id": existing.round_id,
                "report_data": None,
                "generated_at": str(existing.generated_at) if existing.generated_at else None,
                "status": "generating",
            }
        logger.warning(f"[ReportAPI] 报告生成超时，重新触发: report_id={existing.id}")

    # 3. 创建/更新 GENERATING 记录
    if existing:
        existing.status = ReportStatus.GENERATING
        existing.generated_at = now
        existing.report_data = None
        existing.report_content = None
        db.commit()
        report_id = existing.id
    else:
        db_report = InterviewReport(
            session_id=session_id,
            round_id=round_id,
            status=ReportStatus.GENERATING,
            generated_at=now,
        )
        db.add(db_report)
        db.commit()
        report_id = db_report.id

    # 4. 启动后台任务（不等待）
    asyncio.create_task(
        report_manager.background_generate(report_id, session_id, round_id)
    )
    logger.info(f"[ReportAPI] 后台报告任务已提交: report_id={report_id}, session_id={session_id}")

    # 5. 立即返回生成中状态
    return {
        "id": report_id,
        "session_id": session_id,
        "round_id": round_id,
        "report_data": None,
        "generated_at": str(now),
        "status": "generating",
    }


@router.post("", response_model=InterviewReportResponse, status_code=status.HTTP_201_CREATED)
def create_interview_report(
    report: InterviewReportCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """创建面试报告（手动）"""
    session = db.query(InterviewSession).filter(InterviewSession.id == report.session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在"
        )

    db_report = InterviewReport(
        session_id=report.session_id,
        round_id=report.round_id,
        report_content=report.report_content,
        report_data=report.report_data,
        status=report.status or ReportStatus.GENERATING,
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    return db_report


@router.put("/{report_id}", response_model=InterviewReportResponse)
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

    update_data = report.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_report, key, value)

    db.commit()
    db.refresh(db_report)
    return db_report
