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

# 初始化 TOS 文件管理器
file_manager = TosFileManager()

router = APIRouter(prefix="/api/file", tags=["文件管理"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(..., description="上传的文件"),
    file_type: str = Form(..., description="文件类别：resume | voice | dialogue"),
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
            file_type=file_type
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
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    获取用户所有文件列表
    """
    files = db.query(TosFile).filter(TosFile.user_id == current_user_id).all()
    return {
        "message": "文件列表",
        "data": files
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
