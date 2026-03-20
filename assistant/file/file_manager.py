import os
import json
from typing import List, Optional
import uuid
from datetime import datetime

class FileManager:
    def __init__(self):
        self.base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'files')
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)
    
    def save_conversation(self, user_id: str, conversation: dict) -> str:
        """
        保存用户对话
        
        Args:
            user_id: 用户ID
            conversation: 对话内容
            
        Returns:
            str: 文件路径
        """
        user_dir = os.path.join(self.base_dir, user_id)
        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
        
        file_name = f"conversation_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        file_path = os.path.join(user_dir, file_name)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(conversation, f, ensure_ascii=False, indent=2)
        
        return file_path
    
    def load_conversation(self, file_path: str) -> dict:
        """
        加载对话文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            dict: 对话内容
        """
        if not os.path.exists(file_path):
            return {}
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def save_report(self, user_id: str, report: dict) -> str:
        """
        保存用户报告
        
        Args:
            user_id: 用户ID
            report: 报告内容
            
        Returns:
            str: 文件路径
        """
        user_dir = os.path.join(self.base_dir, user_id)
        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
        
        file_name = f"report_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        file_path = os.path.join(user_dir, file_name)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        return file_path
    
    def list_user_files(self, user_id: str, file_type: Optional[str] = None) -> List[str]:
        """
        列出用户的文件
        
        Args:
            user_id: 用户ID
            file_type: 文件类型
            
        Returns:
            List[str]: 文件列表
        """
        user_dir = os.path.join(self.base_dir, user_id)
        if not os.path.exists(user_dir):
            return []
        
        files = []
        for file_name in os.listdir(user_dir):
            if file_type:
                if file_type == 'conversation' and file_name.startswith('conversation_'):
                    files.append(file_name)
                elif file_type == 'report' and file_name.startswith('report_'):
                    files.append(file_name)
            else:
                files.append(file_name)
        
        return files
