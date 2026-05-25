import asyncio
import json
import urllib
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List
from assistant.config.database import get_db, SessionLocal
from assistant.entity import Resume, ResumeStatus, ResumeEducation, ResumeWorkExperience, ResumeSkill, ResumeProject, User
from fastapi import UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse
import urllib.parse
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
from fastapi import BackgroundTasks
from assistant.api.resume_utils import (
    process_resume_background_with_images,
    store_resume_details,
    extract_text,
    delete_resume_file,
    delete_resume_data
)
from assistant.LLM.llm_resume_analysis import analyze_resume_with_llm
from assistant.file.file_manager import TosFileManager
from assistant.entity.DTO import (
    ResumeCreate, ResumeUpdate, ResumeReviewRequest, ResumeEducationCreate,
    ResumeWorkExperienceCreate, ResumeSkillCreate, ResumeProjectCreate,
)
from assistant.entity.VO import (
    ResumeResponse, ResumeEducationResponse,
    ResumeWorkExperienceResponse, ResumeSkillResponse, ResumeProjectResponse
)
from assistant.user_management.auth_middleware import get_current_user_id
from assistant.user_management.auth_utils import verify_token
from assistant.utils.logger import logger
from slowapi import Limiter
from slowapi.util import get_remote_address

# 限流配置
limiter = Limiter(key_func=get_remote_address)
file_manager = TosFileManager()

# ========== 并发与限流参数（可环境变量覆盖）==========
MAX_CONCURRENT_ANALYSIS = int(os.getenv("RESUME_MAX_CONCURRENT_ANALYSIS", "10"))
RATE_LIMIT_IMPORT = os.getenv("RESUME_RATE_LIMIT_IMPORT", "30/minute")
MAX_BATCH_FILES = int(os.getenv("RESUME_MAX_BATCH_FILES", "10"))

analysis_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSIS)

router = APIRouter(prefix="/api/resumes", tags=["简历管理"])


# 简历相关接口
@router.get("")
def get_resumes(
    skip: int = 0,
    limit: int = 100,
    review_status: str = None,
    keyword: str = "",
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取当前用户的所有简历，支持按审核状态筛选、搜索和分页"""
    query = db.query(Resume).filter(Resume.user_id == current_user_id)

    if keyword:
        query = query.filter(Resume.candidate_name.ilike(f"%{keyword}%"))

    if review_status == "null":
        query = query.filter(Resume.review_status.is_(None))
    elif review_status:
        query = query.filter(Resume.review_status == review_status)

    query = query.order_by(Resume.created_at.desc())
    total = query.count()
    resumes = query.offset(skip).limit(limit).all()
    return {"items": [ResumeResponse.model_validate(r) for r in resumes], "total": total}


@router.post("/import", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def import_resume(
    request: Request,
    user_id: int,
    candidate_name: str,
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

    # 4. 检查用户是否已有简历记录
    existing_resume = db.query(Resume).filter(Resume.candidate_name == candidate_name).first()

    if existing_resume:
        # 更新原有简历记录
        existing_resume.file_path = result['tos_key']
        existing_resume.file_type = result['file_type']
        existing_resume.status = ResumeStatus.UPLOADED
        existing_resume.content = None
        existing_resume.extracted_at = datetime.now()
        db.commit()
        db.refresh(existing_resume)
        db_resume = existing_resume
    else:
        # 创建新简历记录
        db_resume = Resume(
            user_id=user_id,
            file_path=result['tos_key'],
            file_type=result['file_type'],
            candidate_name=candidate_name,
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
    candidate_names: str = Form("[]"),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    批量导入简历：文件存本地后立即返回，后台逐步完成 TOS 上传 → 建库 → 分析

    流程：
    1. 接收前端文件，写入临时目录（毫秒级）
    2. 立即返回给前端，前端不需要等待 TOS
    3. 后台逐步完成：TOS 上传 → DB 建记录 → LLM 分析 → 删除本地临时文件
    """
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")

    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=f"单次最多 {MAX_BATCH_FILES} 个文件")

    # 解析候选人姓名
    parsed_names = []
    try:
        parsed_names = json.loads(candidate_names) if candidate_names else []
    except json.JSONDecodeError:
        pass

    # ========== 保存到本地临时目录 ==========
    batch_dir = Path(tempfile.gettempdir()) / f"resume_batch_{current_user_id}_{datetime.now().strftime('%Y%m%d%H%M%S_%f')}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    local_files = []
    async def _save_one(idx: int, file: UploadFile) -> dict:
        content = await file.read()
        if not content or len(content) > 10 * 1024 * 1024:
            # 超限文件仍然保存，后台会做大小校验
            pass
        local_path = batch_dir / f"{idx:03d}_{file.filename}"
        local_path.write_bytes(content)
        name = parsed_names[idx].strip() if idx < len(parsed_names) and parsed_names[idx] else "待解析"
        return {
            "local_path": str(local_path),
            "filename": file.filename,
            "candidate_name": name,
        }

    # 并发写入本地磁盘
    tasks = [_save_one(i, f) for i, f in enumerate(files)]
    local_files = await asyncio.gather(*tasks)

    # ========== 后台并发处理：TOS 上传 → 建库 → 分析 ==========
    async def _process_one_file(item: dict):
        """并发处理单份简历：读取 → TOS 上传 → 建库 → LLM 分析 → 删本地文件"""
        session = SessionLocal()
        try:
            # 1. 读取本地文件
            content = Path(item["local_path"]).read_bytes()

            # 2. 校验大小
            is_valid, err_msg = file_manager.validate_file_size(content)
            if not is_valid:
                logger.warning(f"文件 {item['filename']} 大小超限，跳过: {err_msg}")
                return

            # 3. 上传到 TOS
            loop = asyncio.get_event_loop()
            tos_result = await loop.run_in_executor(
                None, lambda: file_manager.upload_file(
                    db=session, user_id=current_user_id,
                    file_content=content, filename=item["filename"],
                    file_type="resume"
                )
            )
            tos_key = tos_result["tos_key"]
            logger.info(f"本地文件上传TOS成功: {item['filename']} → {tos_key}")

            # 4. 创建 DB 记录
            file_ext = os.path.splitext(item["filename"])[1].lower().lstrip('.')
            existing = None
            if item["candidate_name"] and item["candidate_name"] != "待解析":
                existing = session.query(Resume).filter(
                    Resume.candidate_name == item["candidate_name"],
                    Resume.user_id == current_user_id
                ).first()

            resume_id = None
            if existing:
                existing.file_path = tos_key
                existing.file_type = file_ext or "unknown"
                existing.status = ResumeStatus.UPLOADED
                existing.extracted_at = datetime.now()
                session.commit()
                session.refresh(existing)
                resume_id = existing.id
            else:
                db_resume = Resume(
                    user_id=current_user_id, file_path=tos_key,
                    file_type=file_ext or "unknown",
                    candidate_name=item["candidate_name"],
                    status=ResumeStatus.UPLOADED, content=None,
                    extracted_at=datetime.now()
                )
                session.add(db_resume)
                session.commit()
                session.refresh(db_resume)
                resume_id = db_resume.id

            # 5. LLM 分析（受信号量控制并发数）
            async with analysis_semaphore:
                await process_resume_background_with_images(
                    session, resume_id, content, item["filename"], current_user_id
                )

        except Exception as e:
            logger.error(f"后台处理文件失败 [{item['filename']}]: {e}")
        finally:
            session.close()
            # 无论 TOS 上传/分析成功与否，均删除本地临时文件
            Path(item["local_path"]).unlink(missing_ok=True)
            logger.info(f"本地临时文件已删除: {item['filename']}")

    async def _background_process_all():
        """并发启动所有文件的处理任务"""
        tasks = [_process_one_file(item) for item in local_files]
        await asyncio.gather(*tasks, return_exceptions=True)
        # 尝试删除空目录
        try:
            batch_dir.rmdir()
        except OSError:
            pass

    asyncio.create_task(_background_process_all())

    return {
        "imported": len(local_files),
        "batch_dir": str(batch_dir),
        "message": f"已接收 {len(local_files)} 份文件，后台处理中"
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
    db: Session = Depends(get_db)
):
    """预览简历文件（内联展示，不触发下载）"""
    # 通过 token 查询参数验证身份（用于 iframe/img 直接 URL 访问）
    if token:
        payload = verify_token(token)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的认证凭据"
            )
        current_user_id = int(payload.get("sub"))
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证凭据"
        )

    resume = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user_id
    ).first()

    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户所有"
        )

    # 根据文件类型设置合适的 media_type
    ext = os.path.splitext(resume.file_path)[1].lower()
    media_type_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    media_type = media_type_map.get(ext, "application/octet-stream")

    filename = os.path.basename(resume.file_path)
    encoded_filename = urllib.parse.quote(filename)

    return StreamingResponse(
        file_manager.stream_file_content(resume.file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
        }
    )


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
