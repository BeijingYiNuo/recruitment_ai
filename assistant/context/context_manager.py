from typing import Dict, Any, List
import time

class ContextManager:
    def __init__(self):
        self.contexts: Dict[str, Dict[str, Any]] = {}
    
    def create_context(self, user_id: str) -> None:
        """
        创建用户上下文
        
        Args:
            user_id: 用户ID
        """
        self.contexts[user_id] = {
            'messages': [],
            'created_at': time.time(),
            'last_updated': time.time()
        }
    
    def get_context(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户上下文
        
        Args:
            user_id: 用户ID
            
        Returns:
            Dict[str, Any]: 上下文信息
        """
        if user_id not in self.contexts:
            self.create_context(user_id)
        return self.contexts[user_id]
    
    def update_context(self, user_id: str, update: Dict[str, Any]) -> None:
        """
        更新用户上下文
        
        Args:
            user_id: 用户ID
            update: 更新内容
        """
        if user_id not in self.contexts:
            self.create_context(user_id)
        
        self.contexts[user_id].update(update)
        self.contexts[user_id]['last_updated'] = time.time()
    
    def add_message(self, user_id: str, role: str, content: str) -> None:
        """
        添加消息到用户上下文
        
        Args:
            user_id: 用户ID
            role: 角色
            content: 内容
        """
        if user_id not in self.contexts:
            self.create_context(user_id)
        
        self.contexts[user_id]['messages'].append({
            'role': role,
            'content': content,
            'timestamp': time.time()
        })
        self.contexts[user_id]['last_updated'] = time.time()
    
    def clear_context(self, user_id: str) -> None:
        """
        清空用户上下文
        
        Args:
            user_id: 用户ID
        """
        if user_id in self.contexts:
            del self.contexts[user_id]
    
    def get_active_contexts(self) -> List[str]:
        """
        获取活跃的上下文列表
        
        Returns:
            List[str]: 活跃上下文列表
        """
        return list(self.contexts.keys())
