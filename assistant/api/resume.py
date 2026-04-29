import urllib
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List
from assistant.config.database import get_db
from assistant.entity import Resume, ResumeStatus, ResumeEducation, ResumeWorkExperience, ResumeSkill, ResumeProject, User
from fastapi import UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
import urllib.parse
import os
import tempfile
from datetime import datetime
from typing import Dict, Any
from fastapi import BackgroundTasks
from assistant.api.resume_utils import process_resume_background_with_images, store_resume_details, extract_text
from assistant.LLM.llm_resume_analysis import analyze_resume_with_llm
from assistant.file.file_manager import TosFileManager
from assistant.entity.DTO import (
    ResumeCreate, ResumeUpdate, ResumeEducationCreate,
    ResumeWorkExperienceCreate, ResumeSkillCreate, ResumeProjectCreate
)
from assistant.entity.VO import (
    ResumeResponse, ResumeEducationResponse,
    ResumeWorkExperienceResponse, ResumeSkillResponse, ResumeProjectResponse
)
from assistant.user_management.auth_middleware import get_current_user_id
from assistant.utils.logger import logger
from passlib.context import CryptContext
from slowapi import Limiter, _rate_limit_exceeded_handler
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
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """获取当前用户的所有简历"""
    resumes = db.query(Resume).filter(Resume.user_id == current_user_id).offset(skip).limit(limit).all()
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
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件内容为空"
        )
    
    max_size = 10 * 1024 * 1024  # 10MB
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件大小超过限制（{max_size // 1024 // 1024}MB）"
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
    # 传入文件二进制内容和文件名，后台自行判断是否需要图片识别
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
    """下载简历文件"""
    # 检查简历是否存在且属于当前用户
    resume = db.query(Resume).filter(
        Resume.id == resume_id, 
        Resume.user_id == current_user_id
    ).first()
    
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或不属于当前用户所有"
        )
    
    # 记录下载日志
    logger.info(f"User {current_user_id} downloaded resume {resume_id}")
    
    # 下载文件
    file_content = file_manager.download_file(resume.file_path)
    filename = os.path.basename(resume.file_path)
    encoded_filename = urllib.parse.quote(filename)
    
    # 返回文件
    return StreamingResponse(
            iter([file_content]),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
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
    # 根据简历ID查找简历
    db_resume = db.query(Resume).filter(Resume.id == resume_id).first()
    if not db_resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在"
        )
    
    # 验证权限
    if current_user_id and current_user_id > 0:
        recruiter = db.query(User).filter(User.id == current_user_id).first()
        if not recruiter:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        if db_resume.user_id != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="简历不存在或不属于当前用户所有"
            )
    
    # 保存文件路径用于后台删除
    file_path = db_resume.file_path
    
    # 删除关联表数据
    db.query(ResumeEducation).filter(ResumeEducation.resume_id == db_resume.id).delete()
    db.query(ResumeWorkExperience).filter(ResumeWorkExperience.resume_id == db_resume.id).delete()
    db.query(ResumeSkill).filter(ResumeSkill.resume_id == db_resume.id).delete()
    db.query(ResumeProject).filter(ResumeProject.resume_id == db_resume.id).delete()
    db.query(User).filter(User.username == db_resume.candidate_name).delete()
    
    # 删除主表记录
    db.delete(db_resume)
    db.commit()
    
    # 后台删除文件
    if skip_background:
        delete_resume_file(file_path, db)
    else:
        background_tasks.add_task(delete_resume_file, file_path, db)
    
    return None


def delete_resume_file(file_path: str, db: Session = None):
    """后台删除简历文件"""
    try:
        file_manager.delete_file(file_path, db)
    except Exception as e:
        logger.error(f"删除文件失败: {e}")


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
