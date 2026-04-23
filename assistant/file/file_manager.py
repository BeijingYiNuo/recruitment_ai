import os
import hashlib
import time
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy.orm import Session
import tos
from assistant.utils.logger import logger
from assistant.config.config_manager import ConfigManager
from assistant.entity.tos_file import TosFile


class TosFileManager:
    """基于 TOS SDK 的文件管理器（单例模式）"""
    
    _instance = None
    _lock = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TosFileManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.config_manager = ConfigManager()
        tos_config = self.config_manager.config['tos']
        
        # 初始化 TOS 客户端
        self.client = tos.TosClientV2(
            ak=tos_config['access_key'],
            sk=tos_config['secret_key'],
            endpoint=tos_config['endpoint'],
            region=tos_config['region']
        )
        
        self.bucket_name = tos_config['bucket_name']
        self._initialized = True
        logger.info(f"TOS FileManager initialized with bucket: {self.bucket_name}")
    
    def _calculate_file_hash(self, file_content: bytes) -> str:
        """计算文件哈希值（用于去重）"""
        return hashlib.sha256(file_content).hexdigest()
    
    def _get_file_type(self, filename: str) -> str:
        """根据文件扩展名判断文件类型"""
        ext = filename.split('.')[-1].lower()
        return ext
    
    def get_tos_key(self, user_id: int, file_type: str, filename: str) -> str:
        """
        生成 TOS 存储路径（key）
        
        Args:
            user_id: 用户 ID
            file_type: 文件类别（resume/voice/dialogue）
            filename: 文件名
            
        Returns:
            str: TOS 对象键
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{filename}"
        key = f"{user_id}/{file_type}/{safe_filename}"
        return key
    
    def upload_file(
        self,
        db: Session,
        user_id: int,
        file_content: bytes,
        filename: str,
        file_type: str
    ) -> Dict[str, Any]:
        """
        上传文件到 TOS
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            file_content: 文件内容
            filename: 文件名
            file_type: 文件类别（resume/voice/dialogue）
            
        Returns:
            Dict: 上传结果信息
        """
        try:
            # 验证类别
            valid_categories = ['resume', 'voice', 'dialogue']
            if file_type not in valid_categories:
                raise ValueError(f"Invalid file_type: {file_type}. Must be one of {valid_categories}")
            
            # 生成 TOS key
            tos_key = self.get_tos_key(user_id, file_type, filename)
            
            # 上传到 TOS
            self.client.put_object(
                bucket=self.bucket_name,
                key=tos_key,
                content=file_content
            )
            
            # 获取文件扩展名（不要覆盖 file_type 参数）
            file_ext = self._get_file_type(filename)
            
            # 保存到数据库 - file_uri 存储 tos_key 的值
            db_file = TosFile(
                user_id=user_id,
                file_name=filename,
                file_type=file_type,  # 使用传入的 file_type 参数（resume/voice/dialogue）
                file_size=len(file_content),
                file_uri=tos_key,  # file_uri 存储 tos_key
            )
            db.add(db_file)
            db.commit()
            db.refresh(db_file)
            
            logger.info(f"File uploaded to TOS: {tos_key}, size: {len(file_content)} bytes")
            
            return {
                'success': True,
                'tos_key': tos_key,  # 添加 tos_key 字段
                'file_id': db_file.id,
                'file_uri': tos_key,  # 返回 tos_key 作为 file_uri
                'file_name': filename,
                'file_type': file_ext,  # 返回文件扩展名给前端
                'file_size': len(file_content),
                'user_id': user_id
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Unknown error uploading to TOS: {e}")
            raise Exception(f"TOS upload failed: {str(e)}")
    
    def download_file(self, tos_key: str) -> bytes:
        """
        从 TOS 下载文件
        
        Args:
            tos_key: TOS 对象键
            
        Returns:
            bytes: 文件内容
        """
        try:
            result = self.client.get_object(
                bucket=self.bucket_name,
                key=tos_key
            )
            
            return result.read()
            
        except Exception as e:
            logger.error(f"Failed to download file from TOS: {e}")
            raise
    
    def delete_file(self, tos_key: str, db: Optional[Session] = None) -> bool:
        """
        从 TOS 删除文件，并删除数据库记录
        
        Args:
            tos_key: TOS 对象键
            db: 数据库会话（可选）
            
        Returns:
            bool: 删除是否成功
        """
        try:
            # 从 TOS 删除
            self.client.delete_object(
                bucket=self.bucket_name,
                key=tos_key
            )
            
            # 从数据库删除记录
            if db:
                db_file = db.query(TosFile).filter(TosFile.file_uri == tos_key).first()
                if db_file:
                    db.delete(db_file)
                    db.commit()
                    logger.info(f"Deleted file record from database: {db_file.id}")
            
            logger.info(f"File deleted from TOS: {tos_key}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to delete file from TOS: {e}")
            return False
    
    def get_file_by_uri(self, db: Session, file_uri: str) -> Optional[TosFile]:
        """
        通过 file_uri 获取文件信息
        
        Args:
            db: 数据库会话
            file_uri: 文件访问 URI
            
        Returns:
            TosFile: 文件对象，如果不存在则返回 None
        """
        try:
            db_file = db.query(TosFile).filter(TosFile.file_uri == file_uri).first()
            return db_file
        except Exception as e:
            logger.error(f"Failed to get file by uri: {e}")
            return None
    
    def get_file_content_by_uri(self, db: Session, file_uri: str) -> Optional[bytes]:
        """
        通过 file_uri 获取文件内容
        
        Args:
            db: 数据库会话
            file_uri: 文件访问 URI
            
        Returns:
            bytes: 文件内容，如果不存在则返回 None
        """
        try:
            db_file = self.get_file_by_uri(db, file_uri)
            if not db_file:
                return None
            
            result = self.client.get_object(
                bucket=self.bucket_name,
                key=db_file.tos_key
            )
            
            return result.read()
        except Exception as e:
            logger.error(f"Failed to get file content by uri: {e}")
            return None
    
    def get_file_url(self, tos_key: str, expires: int = 3600) -> str:
        """
        生成预签名 URL（用于临时访问）
        
        Args:
            tos_key: TOS 对象键
            expires: 过期时间（秒）
            
        Returns:
            str: 预签名 URL
        """
        try:
            # 使用 TosClientV2 的 pre_signed_url 方法
            # 注意：不同版本的 TOS SDK 参数可能不同，不要传递 method 参数
            url = self.client.pre_signed_url(
                bucket=self.bucket_name,
                key=tos_key,
                expires=expires
            )
            
            return url
            
        except Exception as e:
            logger.error(f"Failed to generate pre-signed URL: {e}")
            raise

    def format_time_fast(self, ms: int | None) -> str:
        if ms is None:
            return "00:00"
        m = ms // 60000
        s = (ms % 60000) // 1000
        return f"{m:02d}:{s:02d}"
    
    def save_asr_data_to_markdown(
        self,
        asr_data_list: List[Dict[str, Any]],
        session_id: str,
        current_user_id: int,
        db: Optional[Session] = None
    ) -> bool:
        """
        保存 ASR 数据到 Markdown 文件并上传到 TOS
        
        Args:
            asr_data_list: ASR 数据列表
            session_id: 会话ID
            current_user_id: 当前用户ID
            db: 数据库会话（可选）
            
        Returns:
            bool: 保存是否成功
        """
        try:
            if not asr_data_list:
                logger.info(f"No ASR data to save for session {session_id}")
                return False
            
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            md_file_path = f"/tmp/interview_{current_user_id}_{session_id}_{timestamp}.md"
            
            # 生成 Markdown 文件
            with open(md_file_path, 'w', encoding='utf-8') as md_file:
                md_file.write(f"# 面试记录 - {timestamp}\n\n")
                md_file.write("## 语音识别内容\n\n")
                for asr_data in asr_data_list:
                    text = asr_data.get('text', '')
                    speaker_id = asr_data.get('speaker_id', '未知')
                    start_time = asr_data.get('start_time')
                    start_time_str = self.format_time_fast(start_time)
                    md_file.write(f"**说话人 {speaker_id}**: {start_time_str}\n")
                    md_file.write(f"{text}\n\n")
            
            logger.info(f"Markdown file created: {md_file_path}")
            
            # 上传到 TOS
            if db:
                try:
                    with open(md_file_path, 'rb') as f:
                        file_content = f.read()
                    
                    self.upload_file(
                        db=db,
                        user_id=current_user_id,
                        file_content=file_content,
                        filename=f"interview_{current_user_id}_{session_id}_{timestamp}.md",
                        file_type='dialogue'
                    )
                    
                    # 删除临时文件
                    os.remove(md_file_path)
                    logger.info(f"Markdown file uploaded to TOS and temporary file removed")
                    return True
                except Exception as e:
                    logger.error(f"Error uploading markdown file: {e}")
                    # 删除临时文件
                    if os.path.exists(md_file_path):
                        os.remove(md_file_path)
                    return False
            else:
                logger.warning("No database session provided, skipping TOS upload")
                return False
                
        except Exception as e:
            logger.error(f"Failed to save ASR data to markdown: {e}")
            return False
