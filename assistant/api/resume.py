import asyncio
import hashlib
import urllib
from email.utils import formatdate, parsedate_to_datetime
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from assistant.config.database import get_db, SessionLocal
from assistant.entity import Resume, ResumeStatus, ResumeEducation, ResumeWorkExperience, ResumeSkill, ResumeProject, User
from fastapi import UploadFile, File, Form
from fastapi.responses import JSONResponse, Response, StreamingResponse
import urllib.parse
import os
import tempfile
from pathlib import Path
from typing import Dict, Any
from fastapi import BackgroundTasks
from assistant.api.resume_utils import (
    process_resume_background_with_images,
    analyze_resume_only,
    save_resume_to_db,
    store_resume_details,
    extract_text,
    delete_resume_file,
    delete_resume_data
)
from assistant.LLM.llm_resume_analysis import analyze_resume_with_llm
from assistant.LLM.resume_reviewer import ai_review_resume, batch_ai_review_resumes, generate_interview_questions, stream_interview_questions
from assistant.streaming.session import StreamManager
from assistant.file.file_manager import TosFileManager
from assistant.entity.DTO import (
    ResumeCreate, ResumeUpdate, ResumeReviewRequest, ResumeRemarkRequest, ResumeEducationCreate,
    ResumeWorkExperienceCreate, ResumeSkillCreate, ResumeProjectCreate,
    ResumeUpdateDetailRequest,
    AiReviewRequest, BatchAiReviewRequest, InterviewQuestionsRequest, InterviewQuestionsResponse,
    ResumePositionRequest,
)
from assistant.entity.VO import (
    ResumeResponse, ResumeEducationResponse,
    ResumeWorkExperienceResponse, ResumeSkillResponse, ResumeProjectResponse
)
from assistant.user_management.auth_middleware import get_current_user_id
from assistant.user_management.auth_utils import verify_token
import json
from assistant.utils.logger import logger
from slowapi import Limiter
from slowapi.util import get_remote_address

# 限流配置
limiter = Limiter(key_func=get_remote_address)
file_manager = TosFileManager()

# ========== 并发与限流参数（可环境变量覆盖）==========
MAX_CONCURRENT_ANALYSIS = int(os.getenv("RESUME_MAX_CONCURRENT_ANALYSIS", "3"))
RATE_LIMIT_IMPORT = os.getenv("RESUME_RATE_LIMIT_IMPORT", "30/minute")
MAX_BATCH_FILES = int(os.getenv("RESUME_MAX_BATCH_FILES", "10"))

analysis_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSIS)

router = APIRouter(prefix="/api/resumes", tags=["简历管理"])


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """解析 'YYYY-MM-DD' 字符串为 datetime，无效返回 None"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


# 简历相关接口
@router.get("")
def get_resumes(
    skip: int = 0,
    limit: int = 100,
    review_status: str = None,
    keyword: str = "",
    start_time: str = None,
    end_time: str = None,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取当前用户的所有简历，支持按审核状态筛选、搜索、时间范围筛选和分页"""
    query = db.query(Resume).filter(Resume.user_id == current_user_id)

    if keyword:
        query = query.filter(Resume.candidate_name.ilike(f"%{keyword}%"))

    if review_status == "null":
        from sqlalchemy import or_
        query = query.filter(
            or_(Resume.review_status.is_(None), Resume.review_status == "")
        )
    elif review_status:
        query = query.filter(Resume.review_status == review_status)

    if start_time:
        query = query.filter(Resume.created_at >= start_time)
    if end_time:
        query = query.filter(Resume.created_at <= end_time)

    query = query.order_by(Resume.updated_at.desc())
    total = query.count()
    resumes = query.offset(skip).limit(limit).all()
    return {"items": [ResumeResponse.model_validate(r) for r in resumes], "total": total}


@router.post("/import", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def import_resume(
    request: Request,
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user_id: int = Depends(get_current_user_id)
):
    """导入简历：PDF 转图片后用视觉 LLM 识别，后台异步分析"""
    # 1. 检查用户是否存在
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    # 2. 读取文件 + 校验
    content = await file.read()
    is_valid, err_msg = file_manager.validate_file_size(content)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg
        )

    # 3. 上传文件到 TOS（保存原始文件）
    result = file_manager.upload_file(
        db=db,
        user_id=current_user_id,
        file_content=content,
        filename=file.filename,
        file_type="resume"
    )

    # 预热本地缓存，preview 端点直接走磁盘，无需跨公网拉取 TOS
    if file_manager.cache:
        file_manager.cache.put(result['tos_key'], content)

    # 4. 创建新简历记录（姓名由后续 LLM 分析解析填充）
    db_resume = Resume(
        user_id=user_id,
        file_path=result['tos_key'],
        file_type=result['file_type'],
        candidate_name="待解析",
        original_file_name=file.filename,
        status=ResumeStatus.UPLOADED,
        content=None,
        extracted_at=datetime.now()
    )
    db.add(db_resume)
    db.commit()
    db.refresh(db_resume)

    # 5. 后台处理简历分析（PDF 转图片 + 视觉 LLM 识别）
    background_tasks.add_task(
        process_resume_background_with_images,
        db,
        db_resume.id,
        content,  # 文件二进制内容
        file.filename,  # 文件名（用于判断文件类型）
        current_user_id
    )

    # 立即返回响应
    return {
        "id": db_resume.id,
        "user_id": db_resume.user_id,
        "file_path": db_resume.file_path,
        "file_type": db_resume.file_type,
        "status": db_resume.status,
    }



@router.post("/batch/import-local", response_model=Dict[str, Any])
@limiter.limit(RATE_LIMIT_IMPORT)
async def batch_import_local(
    request: Request,
    files: List[UploadFile] = File(...),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    批量导入简历：三阶段隔离架构

    Phase 1（端点内同步）：保存到本地 → 上传 TOS → 创建 DB 记录（status=UPLOADED）
    Phase 2（后台异步）：纯 LLM 分析，不碰数据库
    Phase 3（后台线程）：批量统一写入 DB
    """
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")

    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=f"单次最多 {MAX_BATCH_FILES} 个文件")

    # ========== 保存到本地临时目录 ==========
    batch_dir = Path(tempfile.gettempdir()) / f"resume_batch_{current_user_id}_{datetime.now().strftime('%Y%m%d%H%M%S_%f')}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    local_files = []
    async def _save_one(idx: int, file: UploadFile) -> dict:
        content = await file.read()
        if not content or len(content) > 10 * 1024 * 1024:
            pass
        local_path = batch_dir / f"{idx:03d}_{file.filename}"
        local_path.write_bytes(content)
        return {"local_path": str(local_path), "filename": file.filename}

    tasks = [_save_one(i, f) for i, f in enumerate(files)]
    local_files = await asyncio.gather(*tasks)

    # ========== Phase 1: 上传 TOS + 创建 DB 记录（在线程池中执行，避免阻塞事件循环）==========
    def _phase1_sync(item: dict) -> dict:
        """同步执行：读取 → 校验 → 上传TOS → 创建DB记录"""
        content = Path(item["local_path"]).read_bytes()

        is_valid, err_msg = file_manager.validate_file_size(content)
        if not is_valid:
            logger.warning(f"文件 {item['filename']} 大小超限，跳过: {err_msg}")
            Path(item["local_path"]).unlink(missing_ok=True)
            return None

        session = SessionLocal()
        try:
            tos_result = file_manager.upload_file(
                db=session, user_id=current_user_id,
                file_content=content, filename=item["filename"],
                file_type="resume"
            )
            tos_key = tos_result["tos_key"]
            logger.info(f"本地文件上传TOS成功: {item['filename']} → {tos_key}")

            file_ext = os.path.splitext(item["filename"])[1].lower().lstrip('.')
            existing = session.query(Resume).filter(
                Resume.user_id == current_user_id,
                Resume.original_file_name == item["filename"]
            ).first()

            if existing:
                existing.file_path = tos_key
                existing.file_type = file_ext or "unknown"
                existing.candidate_name = "待解析"
                existing.status = ResumeStatus.UPLOADED
                existing.extracted_at = datetime.now()
                existing.updated_at = datetime.now()
                existing.content = None
                session.commit()
                session.refresh(existing)
                resume_id = existing.id
                logger.info(f"更新已有简历记录: id={resume_id}, file={item['filename']}")
            else:
                db_resume = Resume(
                    user_id=current_user_id, file_path=tos_key,
                    file_type=file_ext or "unknown",
                    candidate_name="待解析",
                    original_file_name=item["filename"],
                    status=ResumeStatus.UPLOADED, content=None,
                    extracted_at=datetime.now()
                )
                session.add(db_resume)
                session.commit()
                session.refresh(db_resume)
                resume_id = db_resume.id

            return {
                "resume_id": resume_id,
                "content": content,
                "filename": item["filename"],
                "tos_key": tos_key,
                "local_path": item["local_path"],
            }
        except Exception as e:
            logger.error(f"Phase 1 处理失败 [{item['filename']}]: {e}")
            session.rollback()
            return None
        finally:
            session.close()

    # 并发执行 Phase 1（在线程池中，不阻塞事件循环）
    phase1_tasks = [asyncio.to_thread(_phase1_sync, item) for item in local_files]
    phase1_results = await asyncio.gather(*phase1_tasks)
    phase1_results = [r for r in phase1_results if r is not None]

    # 预热本地缓存
    for r in phase1_results:
        if file_manager.cache:
            file_manager.cache.put(r["tos_key"], r["content"])

    if not phase1_results:
        return {"imported": 0, "message": "所有文件均未通过校验"}

    # ========== Phase 2 + Phase 3: 后台分析 + 写入 ==========
    async def _analyze_and_save():
        """后台执行 Phase 2（纯异步并发分析）→ Phase 3（批量写入DB）"""
        try:
            # Phase 2: 纯异步并发 LLM 分析（受信号量控制并发数）
            async def _analyze_one(item: dict) -> dict:
                async with analysis_semaphore:
                    parsed_data = await analyze_resume_only(item["content"], item["filename"])
                return {
                    "resume_id": item["resume_id"],
                    "parsed_data": parsed_data,
                    "tos_key": item["tos_key"],
                    "filename": item["filename"],
                    "local_path": item["local_path"],
                }

            analysis_results = await asyncio.gather(
                *[_analyze_one(item) for item in phase1_results],
                return_exceptions=True
            )

            # Phase 3: 逐个写入 DB（各自独立 session+commit，互不影响）
            def _batch_save():
                for result in analysis_results:
                    if isinstance(result, Exception):
                        logger.error(f"分析任务异常: {result}")
                        continue
                    parsed_data = result.get("parsed_data", {})
                    if not parsed_data:
                        logger.warning(f"简历 {result['resume_id']} 分析结果为空")
                        continue
                    try:
                        session = SessionLocal()
                        try:
                            save_resume_to_db(
                                session, result["resume_id"],
                                parsed_data, current_user_id,
                                result["tos_key"], result["filename"]
                            )
                        finally:
                            session.close()
                    except Exception as e:
                        logger.error(f"保存简历 {result['resume_id']} 失败: {e}")

                # 清理本地临时文件
                for item in phase1_results:
                    try:
                        Path(item["local_path"]).unlink(missing_ok=True)
                    except Exception:
                        pass
                try:
                    batch_dir.rmdir()
                except OSError:
                    pass

            await asyncio.to_thread(_batch_save)
        finally:
            # 确保即使 Phase 2/3 意外异常也清理临时文件
            for item in phase1_results:
                try:
                    Path(item["local_path"]).unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                batch_dir.rmdir()
            except OSError:
                pass

    asyncio.create_task(_analyze_and_save())

    return {
        "imported": len(phase1_results),
        "message": f"已接收 {len(phase1_results)} 份文件，后台分析中"
    }


@router.post("/{resume_id}/review", response_model=ResumeResponse)
def review_resume(
    resume_id: int,
    data: ResumeReviewRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """审核简历: PASS=通过, PENDING=待定, FAIL=淘汰"""
    if data.decision not in ("PASS", "PENDING", "FAIL"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的审核决策，请使用 PASS/PENDING/FAIL"
        )

    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户"
        )

    resume.review_status = data.decision
    resume.reviewer_id = current_user_id
    resume.reviewed_at = datetime.now()
    resume.review_comment = data.comment
    db.commit()
    db.refresh(resume)

    logger.info(f"User {current_user_id} reviewed resume {resume_id}: {data.decision}")
    return resume


@router.patch("/{resume_id}/remark", response_model=ResumeResponse)
def save_resume_remark(
    resume_id: int,
    data: ResumeRemarkRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """保存简历审核备注（不改变审核状态）"""
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户"
        )

    resume.review_comment = data.comment
    db.commit()
    db.refresh(resume)

    logger.info(f"User {current_user_id} saved remark for resume {resume_id}")
    return resume


@router.post("/{resume_id}/unreview", response_model=ResumeResponse)
def unreview_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """重置简历审核状态为未审核（待审核）"""
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户"
        )

    resume.review_status = None
    resume.reviewer_id = None
    resume.reviewed_at = None
    resume.review_comment = None
    db.commit()
    db.refresh(resume)

    logger.info(f"User {current_user_id} unreviewed resume {resume_id}")
    return resume


@router.put("/{resume_id}/position", response_model=ResumeResponse)
def set_resume_position(
    resume_id: int,
    data: ResumePositionRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """设置简历的关联岗位"""
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")

    resume.position_id = data.position_id
    db.commit()
    db.refresh(resume)

    logger.info(f"User {current_user_id} set position_id={data.position_id} for resume {resume_id}")
    return resume


@router.post("/{resume_id}/ai-review")
async def resume_ai_review(
    resume_id: int,
    data: AiReviewRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """AI 辅助审核简历：分析简历与岗位的匹配度并给出建议"""
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户"
        )

    # 获取所有子表数据
    educations = db.query(ResumeEducation).filter(ResumeEducation.resume_id == resume_id).all()
    work_experiences = db.query(ResumeWorkExperience).filter(ResumeWorkExperience.resume_id == resume_id).all()
    skills = db.query(ResumeSkill).filter(ResumeSkill.resume_id == resume_id).all()
    projects = db.query(ResumeProject).filter(ResumeProject.resume_id == resume_id).all()

    resume_details = {
        "candidate_name": resume.candidate_name,
        "educations": [
            {
                "school_name": e.school_name,
                "degree": e.degree,
                "major": e.major,
                "start_date": str(e.start_date) if e.start_date else None,
                "end_date": str(e.end_date) if e.end_date else None,
                "is_985": e.is_985,
                "is_211": e.is_211,
            }
            for e in educations
        ],
        "work_experiences": [
            {
                "company_name": w.company_name,
                "position": w.position,
                "start_date": str(w.start_date) if w.start_date else None,
                "end_date": str(w.end_date) if w.end_date else None,
                "description": w.description,
            }
            for w in work_experiences
        ],
        "skills": [
            {"skill_name": s.skill_name, "proficiency_level": s.proficiency_level}
            for s in skills
        ],
        "projects": [
            {
                "project_name": p.project_name,
                "description": p.description,
                "start_date": str(p.start_date) if p.start_date else None,
                "end_date": str(p.end_date) if p.end_date else None,
                "role": p.role,
            }
            for p in projects
        ],
    }

    result = await ai_review_resume(
        resume_details=resume_details,
        position=data.position,
        jd=data.jd,
        custom_requirements=data.custom_requirements,
        headcount=data.headcount,
    )

    # 持久化 AI 审核结果到数据库
    resume.ai_review_data = json.dumps(result, ensure_ascii=False)
    db.commit()

    logger.info(f"AI review resume {resume_id}: suggestion={result.get('suggestion')}")
    return result


@router.post("/ai-review/batch")
async def resume_batch_ai_review(
    data: BatchAiReviewRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """批量 AI 横向比较审核简历（所有候选人一次性发给 LLM 比较）"""
    total = len(data.resume_ids)
    if total == 0:
        return {"total": 0, "results": []}

    logger.info(f"[Batch AI Review] 开始横向比较审核，共 {total} 份简历，headcount={data.headcount}")

    # 1. 收集所有候选人简历详情
    resumes_details = []
    for resume_id in data.resume_ids:
        resume = db.query(Resume).filter(
            Resume.id == resume_id,
            Resume.user_id == current_user_id
        ).first()
        if not resume:
            continue

        educations = db.query(ResumeEducation).filter(ResumeEducation.resume_id == resume_id).all()
        work_experiences = db.query(ResumeWorkExperience).filter(ResumeWorkExperience.resume_id == resume_id).all()
        skills = db.query(ResumeSkill).filter(ResumeSkill.resume_id == resume_id).all()
        projects = db.query(ResumeProject).filter(ResumeProject.resume_id == resume_id).all()

        resumes_details.append({
            "resume_id": resume_id,
            "candidate_name": resume.candidate_name,
            "educations": [
                {"school_name": e.school_name, "degree": e.degree, "major": e.major,
                 "start_date": str(e.start_date) if e.start_date else None,
                 "end_date": str(e.end_date) if e.end_date else None, "is_985": e.is_985, "is_211": e.is_211}
                for e in educations
            ],
            "work_experiences": [
                {"company_name": w.company_name, "position": w.position,
                 "start_date": str(w.start_date) if w.start_date else None,
                 "end_date": str(w.end_date) if w.end_date else None, "description": w.description}
                for w in work_experiences
            ],
            "skills": [{"skill_name": s.skill_name, "proficiency_level": s.proficiency_level} for s in skills],
            "projects": [
                {"project_name": p.project_name, "description": p.description,
                 "start_date": str(p.start_date) if p.start_date else None,
                 "end_date": str(p.end_date) if p.end_date else None, "role": p.role}
                for p in projects
            ],
        })

    # 2. 一次性调用 LLM 进行横向比较
    batch_results = await batch_ai_review_resumes(
        resumes_details=resumes_details,
        position=data.position,
        jd=data.jd,
        custom_requirements=data.custom_requirements,
        headcount=data.headcount,
    )

    # 3. 持久化每个简历的 AI 审核结果并构建返回
    results = []
    for item in batch_results:
        resume_id = item["resume_id"]
        try:
            resume = db.query(Resume).filter(Resume.id == resume_id).first()
            if resume:
                resume.ai_review_data = json.dumps({
                    "suggestion": item["suggestion"],
                    "reason": item["reason"],
                    "matched_points": item["matched_points"],
                    "gaps": item["gaps"],
                }, ensure_ascii=False)
                db.commit()
            results.append({
                "resume_id": resume_id,
                "candidate_name": item.get("candidate_name", ""),
                "result": {
                    "suggestion": item["suggestion"],
                    "reason": item["reason"],
                    "matched_points": item["matched_points"],
                    "gaps": item["gaps"],
                },
            })
        except Exception as e:
            logger.error(f"[Batch AI Review] 持久化失败 resume_id={resume_id}: {e}")
            results.append({
                "resume_id": resume_id,
                "candidate_name": item.get("candidate_name", ""),
                "error": str(e),
            })

    logger.info(f"[Batch AI Review] 横向比较审核完成，共 {len(results)} 份简历")
    return {"total": total, "results": results}
@router.get("/{resume_id}/interview-questions/cache")
async def get_cached_interview_questions(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """仅读取缓存的面试问题，不触发生成"""
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    if resume.interview_questions:
        try:
            cached = json.loads(resume.interview_questions)
            if cached.get("questions"):
                return cached
        except (json.JSONDecodeError, TypeError):
            pass
    return {"questions": []}


@router.post("/{resume_id}/interview-questions")
async def resume_interview_questions(
    resume_id: int,
    data: InterviewQuestionsRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """生成/获取面试提问问题（有缓存则直接返回，无则调 LLM 生成并持久化）"""
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户"
        )

    # 1. 检查是否已有缓存的面试问题（仅当无额外指令时走缓存）
    if not data.instruction and resume.interview_questions:
        try:
            cached = json.loads(resume.interview_questions)
            if cached.get("questions"):
                logger.info(f"Interview questions cache hit for resume {resume_id}")
                return cached
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. 获取项目经历
    projects = db.query(ResumeProject).filter(ResumeProject.resume_id == resume_id).order_by(ResumeProject.id).all()

    resume_details = {
        "candidate_name": resume.candidate_name,
        "projects": [
            {
                "project_name": p.project_name,
                "description": p.description,
                "role": p.role,
                "start_date": str(p.start_date) if p.start_date else None,
                "end_date": str(p.end_date) if p.end_date else None,
            }
            for p in projects
        ],
    }

    # 3. 调用 LLM 生成（带用户指令）
    result = await generate_interview_questions(resume_details, instruction=data.instruction)

    # 4. 持久化到 DB（始终覆盖）
    if result.get("questions"):
        resume.interview_questions = json.dumps(result, ensure_ascii=False)
        db.commit()

    logger.info(f"Interview questions generated for resume {resume_id}")
    return result


@router.post("/{resume_id}/interview-questions/stream")
async def resume_interview_questions_stream(
    resume_id: int,
    data: InterviewQuestionsRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """启动流式面试问题生成，返回 stream_id。"""
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户"
        )

    projects = db.query(ResumeProject).filter(
        ResumeProject.resume_id == resume_id
    ).order_by(ResumeProject.id).all()

    resume_details = {
        "candidate_name": resume.candidate_name,
        "projects": [
            {
                "project_name": p.project_name,
                "description": p.description,
                "role": p.role,
                "start_date": str(p.start_date) if p.start_date else None,
                "end_date": str(p.end_date) if p.end_date else None,
            }
            for p in projects
        ],
    }

    stream_manager = StreamManager.get_instance()
    session = stream_manager.create_session(
        stream_interview_questions,
        resume_details,
        instruction=data.instruction,
        metadata={"resume_id": resume_id, "user_id": current_user_id},
        on_complete=lambda result: _save_questions(result, resume_id),
    )
    await session.start()

    logger.info(f"Stream interview questions started for resume {resume_id}, session={session.id}")
    return {"stream_id": session.id}


async def _save_questions(result: dict, resume_id: int):
    """流式生成完成后，将结果持久化到 resume.interview_questions"""
    logger.info(f"[_save_questions] 被调用 resume_id={resume_id}, result_keys={list(result.keys()) if result else None}, questions_count={len(result.get('questions', [])) if result else 0}")

    if not result or not result.get("questions"):
        logger.warning(f"[_save_questions] result 中没有 questions，跳过持久化。result={result}")
        return

    from assistant.config.database import SessionLocal
    from assistant.entity import Resume
    import json

    try:
        db = SessionLocal()
        try:
            resume = db.query(Resume).filter(Resume.id == resume_id).first()
            if resume:
                json_str = json.dumps(result, ensure_ascii=False)
                resume.interview_questions = json_str
                db.commit()
                logger.info(f"[_save_questions] 持久化成功 resume_id={resume_id}, questions_count={len(result['questions'])}")
            else:
                logger.error(f"[_save_questions] 简历不存在 resume_id={resume_id}")
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[_save_questions] 持久化失败: {e}", exc_info=True)


@router.get("/{resume_id}", response_model=ResumeResponse)
def get_resume_by_user(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """根据简历ID获取简历"""
    # 检查用户是否存在
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 根据简历ID查询简历
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user_id).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户所有"
        )
    return resume


@router.put("/{resume_id}/details", response_model=Dict[str, Any])
def update_resume_details(
    resume_id: int,
    data: ResumeUpdateDetailRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """编辑简历详情：更新候选人姓名及所有子表数据，若修改后的姓名已存在则执行覆盖"""
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在或不属于当前用户")

    new_name = data.candidate_name[:50] if data.candidate_name else resume.candidate_name

    # 第 1 步：检查是否存在同名简历（排除自身）
    existing = None
    if new_name and new_name != "待解析":
        existing = db.query(Resume).filter(
            Resume.user_id == current_user_id,
            Resume.candidate_name == new_name,
            Resume.id != resume_id
        ).first()

    if existing:
        # ====== 覆盖模式：将当前编辑的数据迁移到同名简历 ======
        old_tos_key = existing.file_path

        # 更新现有简历的基础信息
        existing.candidate_name = new_name
        existing.file_path = resume.file_path
        existing.file_type = resume.file_type
        existing.content = resume.content
        existing.original_file_name = resume.original_file_name
        existing.status = resume.status

        # 删除旧简历的子表数据，重新写入编辑后的数据
        db.query(ResumeEducation).filter(ResumeEducation.resume_id == existing.id).delete()
        db.query(ResumeWorkExperience).filter(ResumeWorkExperience.resume_id == existing.id).delete()
        db.query(ResumeSkill).filter(ResumeSkill.resume_id == existing.id).delete()
        db.query(ResumeProject).filter(ResumeProject.resume_id == existing.id).delete()

        target_id = existing.id
        _insert_resume_details(db, target_id, data)

        # 删除当前（被编辑的）简历记录
        db.delete(resume)
        db.commit()

        # 后台删除旧的 TOS 文件
        if old_tos_key:
            try:
                delete_resume_file(old_tos_key, db)
            except Exception as e:
                logger.warning(f"删除旧 TOS 文件失败: {e}")

        logger.info(f"编辑保存触发覆盖：{new_name} 已合并到简历 {target_id}，原简历 {resume_id} 已删除")
        return {"id": target_id, "merged": True, "candidate_name": new_name}

    # ====== 普通模式：更新自身 ======
    if data.candidate_name is not None:
        resume.candidate_name = new_name

    db.query(ResumeEducation).filter(ResumeEducation.resume_id == resume_id).delete()
    db.query(ResumeWorkExperience).filter(ResumeWorkExperience.resume_id == resume_id).delete()
    db.query(ResumeSkill).filter(ResumeSkill.resume_id == resume_id).delete()
    db.query(ResumeProject).filter(ResumeProject.resume_id == resume_id).delete()

    _insert_resume_details(db, resume_id, data)

    db.commit()
    db.refresh(resume)
    logger.info(f"User {current_user_id} updated details for resume {resume_id}")
    return {"id": resume.id, "merged": False, "candidate_name": resume.candidate_name}


def _insert_resume_details(db, resume_id: int, data: ResumeUpdateDetailRequest):
    """通用：将编辑后的详情数据写入指定简历"""
    for edu in data.educations:
        db.add(ResumeEducation(
            resume_id=resume_id,
            school_name=(edu.school_name or "")[:100],
            degree=(edu.degree or "")[:50],
            major=(edu.major or "")[:100],
            start_date=_parse_date(edu.start_date),
            end_date=_parse_date(edu.end_date),
            is_985=edu.is_985 or 0,
            is_211=edu.is_211 or 0,
        ))
    for work in data.work_experiences:
        db.add(ResumeWorkExperience(
            resume_id=resume_id,
            company_name=(work.company_name or "")[:100],
            position=(work.position or "")[:100],
            start_date=_parse_date(work.start_date),
            end_date=_parse_date(work.end_date),
            description=work.description or "",
        ))
    for skill in data.skills:
        db.add(ResumeSkill(
            resume_id=resume_id,
            skill_name=(skill.skill_name or "")[:100],
            proficiency_level=(skill.proficiency_level or "")[:20],
        ))
    for project in data.projects:
        db.add(ResumeProject(
            resume_id=resume_id,
            project_name=(project.project_name or "")[:100],
            description=project.description or "",
            start_date=_parse_date(project.start_date),
            end_date=_parse_date(project.end_date),
            role=(project.role or "")[:100],
        ))


@router.post("/{resume_id}/reparse", response_model=Dict[str, Any])
async def reparse_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user_id: int = Depends(get_current_user_id)
):
    """重新解析简历：下载原始文件，重新调用 LLM 分析"""
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在或不属于当前用户")

    # 重置状态，清除旧数据
    resume.status = ResumeStatus.UPLOADED
    resume.content = None
    resume.candidate_name = "待解析"
    resume.extracted_at = None
    db.query(ResumeEducation).filter(ResumeEducation.resume_id == resume_id).delete()
    db.query(ResumeWorkExperience).filter(ResumeWorkExperience.resume_id == resume_id).delete()
    db.query(ResumeSkill).filter(ResumeSkill.resume_id == resume_id).delete()
    db.query(ResumeProject).filter(ResumeProject.resume_id == resume_id).delete()
    db.commit()

    # 下载原始文件
    try:
        file_bytes = file_manager.download_file(resume.file_path)
        filename = os.path.basename(resume.file_path)
    except Exception as e:
        logger.error(f"重新解析下载文件失败 {resume.file_path}: {e}")
        resume.status = ResumeStatus.FAILED_ANALYSIS
        db.commit()
        raise HTTPException(status_code=500, detail="无法读取原始简历文件")

    # 后台异步分析
    background_tasks.add_task(
        process_resume_background_with_images,
        db,
        resume.id,
        file_bytes,
        filename,
        current_user_id
    )

    return {
        "id": resume.id,
        "status": resume.status.value,
        "message": "简历重新解析已启动，请稍后查看结果"
    }


@router.get("/download/{resume_id}")
async def download_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """下载简历文件（支持大文件流式下载）"""
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()

    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户所有"
        )

    logger.info(f"User {current_user_id} downloaded resume {resume_id}")

    filename = os.path.basename(resume.file_path)
    encoded_filename = urllib.parse.quote(filename)

    return StreamingResponse(
        file_manager.stream_file_content(resume.file_path),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Transfer-Encoding": "chunked"
        }
    )


@router.get("/preview/{resume_id}")
async def preview_resume(
    resume_id: int,
    token: str = None,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """HTTP 协商缓存 304 — 简历 PDF 预览

    前端（axios `responseType: blob` + `createObjectURL`）零改动，
    浏览器 HTTP 缓存全部在后端实现。

    ── 缓存头设计 ──
    Cache-Control: public, no-cache, max-age=86400
      - public    → 允许浏览器 / CDN 缓存
      - no-cache  → 强制每次使用缓存前重新验证（发条件请求）
      - max-age   → 与 no-cache 配合，兼容老旧实现

    ETag: "文件二进制 MD5"
      - 文件内容不变 → ETag 不变 → 命中缓存
      - 文件重新上传 → 内容变 → MD5 变 → ETag 变 → 自动刷新

    Last-Modified: 简历修改时间（GMT 格式）
      - ETag 不匹配时的二级备选验证

    ── 协商流程 ──
    1）首次请求             → 200 + PDF + ETag + Last-Modified → 浏览器缓存
    2）再次请求（no-cache） → 浏览器自动带 If-None-Match
       ETag 一致            → 304 No Content（无响应体）
       ETag 不一致，比对 If-Modified-Since → 304
       资源已变更            → 200 + 新 PDF + 新 ETag + 新 Last-Modified
    3）前端收到 304 → Axios 自动使用本地缓存 blob → createObjectURL 生成新 blob: URL

    ── 约束 ──
    - 前端 axios/fetch 不加额外请求头，不操作 blob
    - 仅在后端实现缓存逻辑
    """
    # ── 1. 认证（token 查询参数，兼容 iframe 无自定义 header） ──
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证凭据")
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="无效的认证凭据")
    user_id = int(payload.get("sub"))

    # ── 2. 查询简历 ──
    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == user_id
    ).first()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")

    # ── 3. 读取文件二进制 → 计算内容 MD5 = ETag ──
    try:
        file_bytes = file_manager.download_file(resume.file_path)
    except Exception:
        raise HTTPException(status_code=500, detail="文件读取失败")

    file_md5 = hashlib.md5(file_bytes).hexdigest()
    etag_value = f'"{file_md5}"'

    # ── 4. 简历修改时间 → Last-Modified（GMT） ──
    modified_at = resume.updated_at or resume.extracted_at or resume.created_at
    if modified_at:
        if modified_at.tzinfo is None:
            modified_at = modified_at.replace(tzinfo=timezone.utc)
        last_modified = formatdate(modified_at.timestamp(), usegmt=True)
    else:
        last_modified = None

    # ── 5. 优先比对 ETag（If-None-Match） ──
    if_none_match = request.headers.get("If-None-Match") if request else None
    if if_none_match:
        trimmed = if_none_match.strip()
        if trimmed == '*' or trimmed == etag_value:
            logger.info(
                f"[304 ETag HIT] resume_id={resume_id} "
                f"etag={etag_value}"
            )
            return Response(
                status_code=304,
                headers={
                    "Cache-Control": "private, max-age=86400",
                    "ETag": etag_value,
                }
            )

    # ── 6. ETag 不匹配 → 比对 Last-Modified（If-Modified-Since） ──
    if last_modified and request:
        if_modified_since = request.headers.get("If-Modified-Since")
        if if_modified_since:
            try:
                since = parsedate_to_datetime(if_modified_since)
                if since.tzinfo is None:
                    since = since.replace(tzinfo=timezone.utc)
                if modified_at is not None and modified_at <= since:
                    logger.info(
                        f"[304 Last-Modified HIT] resume_id={resume_id} "
                        f"last_modified={last_modified}"
                    )
                    return Response(
                        status_code=304,
                        headers={
                            "Cache-Control": "private, max-age=86400",
                            "ETag": etag_value,
                        }
                    )
            except (ValueError, TypeError):
                pass

    # ── 7. 资源已变更 → 200 + PDF + 新缓存头 ──
    logger.info(
        f"[200 MISS] resume_id={resume_id} size={len(file_bytes)} "
        f"etag={etag_value} last_modified={last_modified}"
    )
    headers = {
        "Cache-Control": "private, max-age=86400",
        "ETag": etag_value,
    }
    if last_modified:
        headers["Last-Modified"] = last_modified

    return Response(
        content=file_bytes,
        media_type="application/pdf",
        headers=headers,
    )


@router.post("/precache", response_model=Dict[str, Any])
async def precache_resumes(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """预热所有已有简历的本地缓存，下次预览直接走磁盘而非 TOS"""
    if not file_manager.cache:
        return {"cached": 0, "message": "本地缓存未启用，无需预热"}

    resumes = db.query(Resume).filter(
        Resume.user_id == current_user_id,
        Resume.file_path.isnot(None),
        Resume.file_path != ""
    ).all()

    cached = 0
    for r in resumes:
        try:
            content = file_manager.download_file(r.file_path)
            file_manager.cache.put(r.file_path, content)
            cached += 1
        except Exception as e:
            logger.warning(f"预热缓存失败 resume_id={r.id}: {e}")

    return {"cached": cached, "total": len(resumes), "message": f"已预热 {cached}/{len(resumes)} 份简历"}


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume_by_user(
    resume_id: int,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user_id: int = Depends(get_current_user_id),
    skip_background: bool = False
):
    """根据简历ID删除简历"""
    try:
        delete_resume_data(resume_id, db, current_user_id, skip_background)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    return None


@router.post("/batch/delete", response_model=Dict[str, Any])
async def batch_delete_resumes(
    request: Request,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user_id: int = Depends(get_current_user_id)
):
    """批量删除简历"""
    body = await request.json()
    ids = body.get("ids", [])
    if not ids or not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="请提供要删除的简历 ID 列表")

    deleted = 0
    errors = []
    for resume_id in ids:
        try:
            delete_resume_data(resume_id, db, current_user_id)
            deleted += 1
        except ValueError as e:
            errors.append({"id": resume_id, "error": str(e)})
        except Exception as e:
            errors.append({"id": resume_id, "error": str(e)})
            db.rollback()

    return {"deleted": deleted, "errors": errors}


# 教育经历相关接口
@router.get("/{resume_id}/educations", response_model=List[ResumeEducationResponse])
def get_resume_educations(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取简历的教育经历"""
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user_id).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户所有"
        )
    
    educations = db.query(ResumeEducation).filter(ResumeEducation.resume_id == resume_id).all()
    return educations


# 工作经历相关接口
@router.get("/{resume_id}/work-experiences", response_model=List[ResumeWorkExperienceResponse])
def get_resume_work_experiences(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取简历的工作经历"""
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user_id).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户所有"
        )
    
    work_experiences = db.query(ResumeWorkExperience).filter(ResumeWorkExperience.resume_id == resume_id).all()
    return work_experiences


# 技能相关接口
@router.get("/{resume_id}/skills", response_model=List[ResumeSkillResponse])
def get_resume_skills(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取简历的技能"""
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user_id).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户所有"
        )
    
    skills = db.query(ResumeSkill).filter(ResumeSkill.resume_id == resume_id).all()
    return skills


# 项目经历相关接口
@router.get("/{resume_id}/projects", response_model=List[ResumeProjectResponse])
def get_resume_projects(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取简历的项目经历"""
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user_id).first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户所有"
        )
    
    projects = db.query(ResumeProject).filter(ResumeProject.resume_id == resume_id).all()
    return projects
