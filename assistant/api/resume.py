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
    ResumeWorkExperienceCreate, ResumeSkillCreate, ResumeProjectCreate
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
from slowapi.errors import RateLimitExceeded

# 限流配置
limiter = Limiter(key_func=get_remote_address)
file_manager = TosFileManager()

router = APIRouter(prefix="/api/resumes", tags=["简历管理"])


# 简历相关接口
@router.get("", response_model=List[ResumeResponse])
def get_resumes(
    skip: int = 0,
    limit: int = 100,
    review_status: str = None,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取当前用户的所有简历，支持按审核状态筛选"""
    query = db.query(Resume).filter(Resume.user_id == current_user_id)

    if review_status == "null":
        query = query.filter(Resume.review_status.is_(None))
    elif review_status:
        query = query.filter(Resume.review_status == review_status)

    query = query.order_by(Resume.created_at.desc())
    resumes = query.offset(skip).limit(limit).all()
    return resumes


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


@router.post("/import/batch", response_model=List[Dict[str, Any]], status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def import_resumes_batch(
    request: Request,
    user_id: int,
    files: List[UploadFile] = File(...),
    candidate_names: str = Form("[]"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """批量导入简历，并行解析，支持一次上传多个 PDF/Word 文件"""
    # 1. 检查用户是否存在
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    if not files or len(files) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请至少上传一个文件"
        )

    max_size = 10 * 1024 * 1024  # 10MB
    max_files = 20
    if len(files) > max_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"单次最多上传 {max_files} 个文件"
        )

    # ========== 阶段1：并发读取所有文件 ==========
    async def _read_file(file: UploadFile) -> dict:
        content = await file.read()
        return {"filename": file.filename, "content": content}

    file_datas = await asyncio.gather(*[_read_file(f) for f in files], return_exceptions=True)

    # Parse candidate names (JSON array string) and pair with files
    try:
        parsed_names = json.loads(candidate_names) if candidate_names else []
    except json.JSONDecodeError:
        parsed_names = []
    for i, fd in enumerate(file_datas):
        if isinstance(fd, dict) and i < len(parsed_names) and parsed_names[i]:
            fd["candidate_name"] = parsed_names[i].strip()

    # ========== 阶段2：并行处理每个文件（上传TOS + 创建DB记录）==========
    def _process_single_file(file_data: dict) -> dict:
        """同步处理单个文件的上传和入库"""
        filename = file_data["filename"]
        content = file_data["content"]
        candidate_name = file_data.get("candidate_name", "待解析")

        if isinstance(content, Exception):
            return {"filename": filename, "success": False, "error": f"读取文件失败: {content}"}

        if not content:
            return {"filename": filename, "success": False, "error": "文件内容为空"}

        if len(content) > max_size:
            return {
                "filename": filename,
                "success": False,
                "error": f"文件大小超过限制（{max_size // 1024 // 1024}MB）"
            }

        # 每个文件使用独立数据库会话，避免并发冲突
        session = SessionLocal()
        try:
            result = file_manager.upload_file(
                db=session,
                user_id=current_user_id,
                file_content=content,
                filename=filename,
                file_type="resume"
            )

            db_resume = Resume(
                user_id=user_id,
                file_path=result['tos_key'],
                file_type=result['file_type'],
                candidate_name=candidate_name,
                status=ResumeStatus.UPLOADED,
                content=None,
                extracted_at=datetime.now()
            )
            session.add(db_resume)
            session.commit()
            session.refresh(db_resume)

            return {
                "filename": filename,
                "content": content,
                "resume_id": db_resume.id,
                "candidate_name": candidate_name,
                "success": True,
            }
        except Exception as e:
            session.rollback()
            return {"filename": filename, "success": False, "error": str(e)}
        finally:
            session.close()

    # 使用线程池执行同步 IO 操作（TOS上传），并行处理
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, _process_single_file, fd) for fd in file_datas]
    processed = await asyncio.gather(*tasks)

    # ========== 阶段3：并发启动所有后台分析任务 ==========
    async def _run_analysis(item: dict):
        if not item.get("success"):
            return item
        session = SessionLocal()
        try:
            await process_resume_background_with_images(
                session, item["resume_id"], item["content"], item["filename"], current_user_id
            )
        except Exception as e:
            logger.error(f"简历分析失败 [{item['filename']}]: {e}")
        finally:
            session.close()

    # 所有分析任务并发执行（不等待完成，立即返回）
    analysis_tasks = [asyncio.create_task(_run_analysis(item)) for item in processed]
    asyncio.ensure_future(asyncio.gather(*analysis_tasks, return_exceptions=True))

    # ========== 返回结果 ==========
    results = []
    for item in processed:
        if item.get("success"):
            results.append({
                "id": item["resume_id"],
                "filename": item["filename"],
                "success": True,
                "status": "UPLOADED",
            })
        else:
            results.append({
                "filename": item["filename"],
                "success": False,
                "error": item["error"],
            })

    return results


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
