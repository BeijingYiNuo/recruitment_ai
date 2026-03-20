import uuid
import time
from typing import Dict, Any, List

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
    
    def create_session(self) -> str:
        """
        创建用户会话
        
        Returns:
            str: 用户ID
        """
        user_id = str(uuid.uuid4())
        self.sessions[user_id] = {
            'created_at': time.time(),
            'status': 'active'
        }
        return user_id
    
    def get_session(self, user_id: str) -> Dict[str, Any] | None:
        """
        获取用户会话
        
        Args:
            user_id: 用户ID
            
        Returns:
            Dict[str, Any] | None: 会话信息，如果不存在返回None
        """
        return self.sessions.get(user_id)
    
    def remove_session(self, user_id: str) -> None:
        """
        移除用户会话
        
        Args:
            user_id: 用户ID
        """
        if user_id in self.sessions:
            del self.sessions[user_id]
    
    def list_sessions(self) -> List[str]:
        """
        列出所有会话
        
        Returns:
            List[str]: 用户ID列表
        """
        return list(self.sessions.keys())
    
    def get_session_count(self) -> int:
        """
        获取会话数量
        
        Returns:
            int: 会话数量
        """
        return len(self.sessions)
