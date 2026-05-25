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
    ResumeWorkExperienceCreate, ResumeSkillCreate, ResumeProjectCreate,
    BatchUploadUrlRequest, UploadUrlResult, TosImportItem, BatchTosImportRequest,
    ProcessPendingRequest
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

# ========== 并发与限流参数（可环境变量覆盖）==========
MAX_CONCURRENT_ANALYSIS = int(os.getenv("RESUME_MAX_CONCURRENT_ANALYSIS", "5"))
RATE_LIMIT_UPLOAD = os.getenv("RESUME_RATE_LIMIT_UPLOAD", "60/minute")
RATE_LIMIT_IMPORT = os.getenv("RESUME_RATE_LIMIT_IMPORT", "30/minute")
MAX_BATCH_FILES = int(os.getenv("RESUME_MAX_BATCH_FILES", "20"))

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


@router.post("/import/batch", response_model=List[Dict[str, Any]], status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_IMPORT)
async def import_resumes_batch(
    request: Request,
    user_id: int,
    files: List[UploadFile] = File(...),
    candidate_names: str = Form("[]"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """批量导入简历，仅快速建库后立即返回，TOS上传和分析均在后台执行"""
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
    max_files = MAX_BATCH_FILES
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

    # 解析候选人姓名
    try:
        parsed_names = json.loads(candidate_names) if candidate_names else []
    except json.JSONDecodeError:
        parsed_names = []
    for i, fd in enumerate(file_datas):
        if isinstance(fd, dict) and i < len(parsed_names) and parsed_names[i]:
            fd["candidate_name"] = parsed_names[i].strip()

    # ========== 阶段2：快速创建DB记录（不等待TOS上传）==========
    def _create_resume_record(file_data: dict) -> dict:
        """创建简历DB记录，状态为PENDING_UPLOAD"""
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

        session = SessionLocal()
        try:
            file_ext = os.path.splitext(filename)[1].lower().lstrip('.')
            db_resume = Resume(
                user_id=user_id,
                file_path="",  # TOS上传后更新
                file_type=file_ext or "unknown",
                candidate_name=candidate_name,
                status=ResumeStatus.PENDING_UPLOAD,
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

    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, _create_resume_record, fd) for fd in file_datas]
    processed = await asyncio.gather(*tasks)

    # ========== 阶段3：后台TOS上传 + 分析（不阻塞响应）==========
    async def _background_process(item: dict):
        """后台任务：TOS上传 → 更新状态 → 简历分析"""
        if not item.get("success"):
            return
        session = SessionLocal()
        try:
            # Step 1: 上传文件到 TOS（同步操作，在线程池执行避免阻塞事件循环）
            def _upload_to_tos():
                upload_session = SessionLocal()
                try:
                    return file_manager.upload_file(
                        db=upload_session,
                        user_id=current_user_id,
                        file_content=item["content"],
                        filename=item["filename"],
                        file_type="resume"
                    )
                finally:
                    upload_session.close()

            result = await loop.run_in_executor(None, _upload_to_tos)

            # Step 2: 更新简历记录（TOS key + 状态）
            resume = session.query(Resume).filter(Resume.id == item["resume_id"]).first()
            if resume:
                resume.file_path = result['tos_key']
                resume.file_type = result['file_type']
                resume.status = ResumeStatus.UPLOADED
                session.commit()

            # Step 3: 简历分析（PDF转图片 + LLM，使用信号量控制并发数）
            async with analysis_semaphore:
                await process_resume_background_with_images(
                    session, item["resume_id"], item["content"], item["filename"], current_user_id
                )
        except Exception as e:
            logger.error(f"简历后台处理失败 [{item['filename']}]: {e}")
            # 避免记录永久卡在 PENDING_UPLOAD 状态
            try:
                resume = session.query(Resume).filter(Resume.id == item["resume_id"]).first()
                if resume and resume.status == ResumeStatus.PENDING_UPLOAD:
                    resume.status = ResumeStatus.FAILED_ANALYSIS
                    session.commit()
            except Exception:
                pass
        finally:
            session.close()

    asyncio.ensure_future(asyncio.gather(
        *[asyncio.create_task(_background_process(item)) for item in processed],
        return_exceptions=True
    ))

    # ========== 立即返回（不等待TOS上传和分析）==========
    results = []
    for item in processed:
        if item.get("success"):
            results.append({
                "id": item["resume_id"],
                "filename": item["filename"],
                "success": True,
                "status": ResumeStatus.PENDING_UPLOAD.value,
            })
        else:
            results.append({
                "filename": item["filename"],
                "success": False,
                "error": item["error"],
            })

    return results


@router.post("/batch/upload-urls", response_model=Dict[str, Any])
@limiter.limit(RATE_LIMIT_UPLOAD)
async def get_batch_upload_urls(
    request: Request,
    data: BatchUploadUrlRequest,
    current_user_id: int = Depends(get_current_user_id)
):
    """批量获取预签名上传URL（客户端直传TOS，绕过服务器带宽瓶颈）"""
    if not data.files or len(data.files) == 0:
        raise HTTPException(status_code=400, detail="请至少提供一个文件")

    if len(data.files) > MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=f"单次最多 {MAX_BATCH_FILES} 个文件")

    upload_urls = []
    for item in data.files:
        url_info = file_manager.generate_upload_url(
            user_id=current_user_id,
            filename=item.filename,
            file_type="resume"
        )
        upload_urls.append({
            "filename": item.filename,
            "url": url_info["url"],
            "tos_key": url_info["tos_key"],
        })

    return {"upload_urls": upload_urls}


@router.post("/batch/import-from-tos", response_model=List[Dict[str, Any]], status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_IMPORT)
async def import_resumes_batch_from_tos(
    request: Request,
    data: BatchTosImportRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """从TOS批量导入简历（文件已上传到TOS，仅建库后后台分析，不阻塞响应）"""
    if not data.resumes or len(data.resumes) == 0:
        raise HTTPException(status_code=400, detail="请至少提供一个简历")

    if len(data.resumes) > MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=f"单次最多 {MAX_BATCH_FILES} 个文件")

    loop = asyncio.get_event_loop()

    # ========== 创建DB记录（跳过默认名"待解析"的去重，避免相互覆盖） ==========
    def _create_record(item: TosImportItem) -> dict:
        session = SessionLocal()
        try:
            file_ext = os.path.splitext(item.filename)[1].lower().lstrip('.')

            # 跳过默认名"待解析"的去重
            existing = None
            if item.candidate_name and item.candidate_name != "待解析":
                existing = session.query(Resume).filter(
                    Resume.candidate_name == item.candidate_name,
                    Resume.user_id == current_user_id
                ).first()

            if existing:
                old_file_path = existing.file_path
                if old_file_path:
                    try:
                        del_session = SessionLocal()
                        try:
                            file_manager.delete_file(old_file_path, del_session)
                        finally:
                            del_session.close()
                    except Exception as e:
                        logger.warning(f"删除旧简历文件失败 [{item.candidate_name}]: {e}")

                existing.file_path = item.tos_key
                existing.file_type = file_ext or "unknown"
                existing.status = ResumeStatus.UPLOADED
                existing.content = None
                existing.extracted_at = datetime.now()
                session.commit()
                session.refresh(existing)

                return {
                    "filename": item.filename,
                    "tos_key": item.tos_key,
                    "resume_id": existing.id,
                    "candidate_name": item.candidate_name,
                    "success": True,
                    "updated": True,
                }
            else:
                db_resume = Resume(
                    user_id=current_user_id,
                    file_path=item.tos_key,
                    file_type=file_ext or "unknown",
                    candidate_name=item.candidate_name,
                    status=ResumeStatus.UPLOADED,
                    content=None,
                    extracted_at=datetime.now()
                )
                session.add(db_resume)
                session.commit()
                session.refresh(db_resume)

                return {
                    "filename": item.filename,
                    "tos_key": item.tos_key,
                    "resume_id": db_resume.id,
                    "candidate_name": item.candidate_name,
                    "success": True,
                    "updated": False,
                }
        except Exception as e:
            session.rollback()
            return {"filename": item.filename, "success": False, "error": str(e)}
        finally:
            session.close()

    tasks = [loop.run_in_executor(None, _create_record, item) for item in data.resumes]
    processed = await asyncio.gather(*tasks)

    # ========== 不启动后台分析，只返回建库结果（分析与导入解耦）==========
    results = []
    for item in processed:
        if item.get("success"):
            results.append({
                "id": item["resume_id"],
                "filename": item["filename"],
                "success": True,
                "status": ResumeStatus.UPLOADED.value,
            })
        else:
            results.append({
                "filename": item["filename"],
                "success": False,
                "error": item["error"],
            })
    return results


@router.post("/batch/process-pending", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def process_pending_resumes(
    request: Request,
    data: ProcessPendingRequest = None,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    批量处理待分析的简历（分析与导入解耦）

    从 TOS 下载简历文件并执行 LLM 分析。
    不传 resume_ids 则处理当前用户所有 UPLOADED / FAILED_ANALYSIS 的简历。
    """
    # 查询待处理简历
    query = db.query(Resume).filter(Resume.user_id == current_user_id)
    if data and data.resume_ids:
        query = query.filter(Resume.id.in_(data.resume_ids))
    else:
        query = query.filter(
            Resume.status.in_([ResumeStatus.UPLOADED, ResumeStatus.FAILED_ANALYSIS])
        )
    pending = query.all()

    if not pending:
        return {"queued": 0, "message": "没有待分析的简历"}

    # 逐个异步处理（同步阻塞操作在线程池执行，避免卡事件循环）
    async def _process_one(resume: Resume):
        loop = asyncio.get_event_loop()
        try:
            # TOS 下载是同步 IO，放线程池里
            file_bytes = await loop.run_in_executor(
                None, file_manager.download_file, resume.file_path
            )

            session = SessionLocal()
            try:
                # 如果是重试，先清除旧的解析数据
                if resume.status == ResumeStatus.FAILED_ANALYSIS:
                    session.query(ResumeEducation).filter(
                        ResumeEducation.resume_id == resume.id
                    ).delete()
                    session.query(ResumeWorkExperience).filter(
                        ResumeWorkExperience.resume_id == resume.id
                    ).delete()
                    session.query(ResumeSkill).filter(
                        ResumeSkill.resume_id == resume.id
                    ).delete()
                    session.query(ResumeProject).filter(
                        ResumeProject.resume_id == resume.id
                    ).delete()
                    session.commit()
                    logger.info(f"已清除简历 {resume.id} 的旧解析数据，准备重新分析")

                async with analysis_semaphore:
                    await process_resume_background_with_images(
                        session, resume.id, file_bytes,
                        resume.file_path.split("/")[-1] or "resume.pdf",
                        current_user_id
                    )
            finally:
                session.close()
        except Exception as e:
            logger.error(f"简历后台处理失败 [{resume.id}]: {e}")
            try:
                session = SessionLocal()
                r = session.query(Resume).filter(Resume.id == resume.id).first()
                if r and r.status in (ResumeStatus.UPLOADED, ResumeStatus.PENDING_UPLOAD):
                    r.status = ResumeStatus.FAILED_ANALYSIS
                    session.commit()
                session.close()
            except Exception:
                pass

    for resume in pending:
        asyncio.create_task(_process_one(resume))

    return {"queued": len(pending), "message": f"已加入 {len(pending)} 份简历到分析队列"}


@router.post("/batch/upload-file", response_model=Dict[str, str])
@limiter.limit(RATE_LIMIT_UPLOAD)
async def batch_upload_file(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """接收前端单文件并上传到TOS（CORS中转，代替浏览器直传TOS）"""
    content = await file.read()
    is_valid, err_msg = file_manager.validate_file_size(content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=err_msg)

    result = file_manager.upload_file(
        db=db,
        user_id=current_user_id,
        file_content=content,
        filename=file.filename,
        file_type="resume"
    )
    return {"tos_key": result["tos_key"], "filename": file.filename}


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
