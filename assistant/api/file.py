from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import tos
import urllib.parse
from assistant.config.database import get_db
from assistant.user_management.auth_middleware import get_current_user_id
from assistant.utils.logger import logger
from assistant.file.file_manager import TosFileManager
from assistant.entity.tos_file import TosFile
from assistant.entity.interview import InterviewSession

# 初始化 TOS 文件管理器
file_manager = TosFileManager()

router = APIRouter(prefix="/api/file", tags=["文件管理"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(..., description="上传的文件"),
    file_type: str = Form(..., description="文件类别：resume | voice | dialogue"),
    session_id: int = Form(0, description="关联的面试会话ID"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    上传文件到 TOS 对象存储

    - **file**: 上传的文件
    - **file_type**: 文件类别（resume | voice | dialogue）
        - resume: 简历文件
        - voice: 语音文件
        - dialogue: 对话文件
    - **session_id**: 关联的面试会话ID

    存储路径格式：{user_id}/{file_type}/{timestamp}_{filename}
    """
    try:
        # 读取文件内容
        content = await file.read()
        
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文件内容为空"
            )
        
        # 验证文件大小（限制 100MB）
        max_size = 100 * 1024 * 1024  # 100MB
        if len(content) > max_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"文件大小超过限制（{max_size // 1024 // 1024}MB）"
            )
        
        # 上传到 TOS
        result = file_manager.upload_file(
            db=db,
            user_id=current_user_id,
            file_content=content,
            filename=file.filename,
            file_type=file_type,
            session_id=session_id
        )
        
        logger.info(f"User {current_user_id} uploaded file: {result['tos_key']}")
        
        return {
            "message": "上传成功",
            "data": result
        }
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to upload file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件上传失败：{str(e)}"
        )


@router.get("/list")
async def list_files(
    skip: int = 0,
    limit: int = 100,
    keyword: str = "",
    file_type: str = "",
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    获取用户所有文件列表，支持搜索和分页

    - **file_type**: 按文件类型过滤，多个类型用逗号分隔，如 "voice,dialogue"
    """
    query = db.query(TosFile).filter(TosFile.user_id == current_user_id)

    if keyword:
        query = query.filter(TosFile.file_name.ilike(f"%{keyword}%"))

    if file_type:
        types = [t.strip() for t in file_type.split(",") if t.strip()]
        if types:
            query = query.filter(TosFile.file_type.in_(types))

    query = query.order_by(TosFile.updated_at.desc())
    total = query.count()
    files = query.offset(skip).limit(limit).all()

    # 获取所有关联的会话名称（候选人姓名）
    session_ids = {f.session_id for f in files if f.session_id and f.session_id != 0}
    session_names = {}
    if session_ids:
        sessions = db.query(InterviewSession.id, InterviewSession.candidate_name).filter(
            InterviewSession.id.in_(session_ids)
        ).all()
        session_names = {s.id: s.candidate_name for s in sessions}

    # 将文件数据转为字典并附加 session_name
    data = []
    for f in files:
        fd = {
            "id": f.id,
            "file_name": f.file_name,
            "file_type": f.file_type,
            "file_size": f.file_size,
            "user_id": f.user_id,
            "session_id": f.session_id,
            "file_uri": f.file_uri,
            "created_at": str(f.created_at) if f.created_at else None,
            "updated_at": str(f.updated_at) if f.updated_at else None,
            "session_name": session_names.get(f.session_id) if f.session_id else None
        }
        data.append(fd)

    return {
        "message": "文件列表",
        "data": data,
        "total": total
    }   


@router.get("/download")
async def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    下载文件
    
    - **file_id**: 文件 ID
    """
    try:
        # 验证文件是否属于当前用户
        db_file = db.query(TosFile).filter(
            TosFile.id == file_id,
            TosFile.user_id == current_user_id
        ).first()
         
        if not db_file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="文件不存在或无权访问"
            )
        
        # 从 TOS 下载文件
        file_content = file_manager.download_file(db_file.file_uri)
        
        # 生成文件名（URL 编码）
        import os
        filename = os.path.basename(db_file.file_uri)
        encoded_filename = urllib.parse.quote(filename)
        
        # 返回文件流
        return StreamingResponse(
            iter([file_content]),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件下载失败：{str(e)}"
        )


@router.delete("/delete")
async def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    删除 TOS 中的文件
    - **file_id**: 文件 ID
    
    返回删除结果
    """
    try:
        # 验证文件是否属于当前用户
        db_file = db.query(TosFile).filter(
            TosFile.user_id == current_user_id,
            TosFile.id == file_id
        ).first()
        
        if not db_file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="文件不存在或无权访问"
            )
        
        # 删除文件
        success = file_manager.delete_file(tos_key=db_file.file_uri, db=db)
        
        if success:
            logger.info(f"User {current_user_id} deleted file: {db_file.file_uri}")
            return {
                "message": "删除成功",
                "data": {
                    "tos_key": db_file.file_uri
                }
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="删除失败"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件删除失败：{str(e)}"
        )


@router.delete("/delete-by-session")
async def delete_files_by_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    删除某个会话文件夹下的所有文件

    - **session_id**: 会话 ID
    """
    try:
        # 查询该会话下属于当前用户的所有文件
        files = db.query(TosFile).filter(
            TosFile.session_id == session_id,
            TosFile.user_id == current_user_id
        ).all()

        if not files:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="该会话下没有文件"
            )

        deleted_count = 0
        for f in files:
            success = file_manager.delete_file(tos_key=f.file_uri, db=db)
            if success:
                deleted_count += 1

        logger.info(f"User {current_user_id} deleted {deleted_count} files in session {session_id}")

        return {
            "message": f"成功删除 {deleted_count} 个文件",
            "data": {
                "deleted_count": deleted_count,
                "session_id": session_id
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete files by session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除失败：{str(e)}"
        )
