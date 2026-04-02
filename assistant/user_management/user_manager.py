from typing import Optional, Dict, Any
from datetime import datetime
from assistant.user_management.db_manager import db_manager
from assistant.user_management.auth_utils import AuthUtils

class UserManager:
    def __init__(self):
        # 初始化数据库表
        db_manager.init_database()
    
    def register_user(self, username: str, email: str, password: str) -> Dict[str, Any]:
        """
        注册新用户
        
        Args:
            username: 用户名
            email: 邮箱
            password: 密码
            
        Returns:
            Dict[str, Any]: 注册结果
        """
        # 检查用户名是否已存在
        success, existing_user = db_manager.execute_query(
            "SELECT id FROM users WHERE username = %(username)s",
            {"username": username}
        )
        
        if success and existing_user:
            return {"success": False, "message": "用户名已存在"}
        
        # 检查邮箱是否已存在
        success, existing_email = db_manager.execute_query(
            "SELECT id FROM users WHERE email = %(email)s",
            {"email": email}
        )
        
        if success and existing_email:
            return {"success": False, "message": "邮箱已被注册"}
        
        # 对密码进行哈希处理
        password_hash = AuthUtils.hash_password(password)
        
        # 插入新用户
        success, result = db_manager.execute_query(
            "INSERT INTO users (username, email, password_hash) VALUES (%(username)s, %(email)s, %(password_hash)s)",
            {"username": username, "email": email, "password_hash": password_hash}
        )
        
        if success and result > 0:
            return {"success": True, "message": "注册成功"}
        else:
            return {"success": False, "message": "注册失败"}
    
    def login_user(self, email: str, password: str) -> Dict[str, Any]:
        """
        用户登录
        
        Args:
            email: 邮箱
            password: 密码
            
        Returns:
            Dict[str, Any]: 登录结果
        """
        # 查询用户
        success, users = db_manager.execute_query(
            "SELECT id, username, email, password_hash FROM users WHERE email = %(email)s",
            {"email": email}
        )
        
        if not success or not users:
            return {"success": False, "message": "邮箱或密码错误"}
        
        user = users[0]
        
        # 验证密码
        if not AuthUtils.verify_password(password, user["password_hash"]):
            return {"success": False, "message": "邮箱或密码错误"}
        
        # 生成JWT token
        access_token = AuthUtils.create_access_token(
            data={"sub": str(user["id"]), "user_id": user["id"]}
        )
        
        return {
            "success": True,
            "message": "登录成功",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"]
            },
            "access_token": access_token,
            "token_type": "bearer"
        }
    
    def forgot_password(self, email: str) -> Dict[str, Any]:
        """
        忘记密码
        
        Args:
            email: 邮箱
            
        Returns:
            Dict[str, Any]: 操作结果
        """
        # 查询用户
        success, users = db_manager.execute_query(
            "SELECT id FROM users WHERE email = %(email)s",
            {"email": email}
        )
        
        if not success or not users:
            return {"success": False, "message": "邮箱不存在"}
        
        user_id = users[0]["id"]
        
        # 生成重置令牌
        token = AuthUtils.generate_reset_token()
        expires_at = AuthUtils.get_token_expiry()
        
        # 删除该用户之前的重置令牌
        db_manager.execute_query(
            "DELETE FROM password_reset_tokens WHERE user_id = %(user_id)s",
            {"user_id": user_id}
        )
        
        # 插入新的重置令牌
        success, result = db_manager.execute_query(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%(user_id)s, %(token)s, %(expires_at)s)",
            {"user_id": user_id, "token": token, "expires_at": expires_at}
        )
        
        if success and result > 0:
            # 这里应该发送邮件给用户，包含重置链接
            # 实际项目中需要配置邮件服务
            reset_link = f"http://localhost:8001/api/auth/reset-password?token={token}"
            print(f"密码重置链接: {reset_link}")
            return {
                "success": True,
                "message": "密码重置链接已发送到您的邮箱",
                "reset_link": reset_link  # 仅用于测试
            }
        else:
            return {"success": False, "message": "生成重置令牌失败"}
    
    def reset_password(self, token: str, new_password: str) -> Dict[str, Any]:
        """
        重置密码
        
        Args:
            token: 重置令牌
            new_password: 新密码
            
        Returns:
            Dict[str, Any]: 操作结果
        """
        # 查询令牌
        success, tokens = db_manager.execute_query(
            "SELECT user_id, expires_at FROM password_reset_tokens WHERE token = %(token)s",
            {"token": token}
        )
        
        if not success or not tokens:
            return {"success": False, "message": "无效的重置令牌"}
        
        token_info = tokens[0]
        
        # 检查令牌是否过期
        if datetime.now() > token_info["expires_at"]:
            return {"success": False, "message": "重置令牌已过期"}
        
        user_id = token_info["user_id"]
        
        # 对新密码进行哈希处理
        password_hash = AuthUtils.hash_password(new_password)
        
        # 更新用户密码
        success, result = db_manager.execute_query(
            "UPDATE users SET password_hash = %(password_hash)s WHERE id = %(id)s",
            {"password_hash": password_hash, "id": user_id}
        )
        
        if success and result > 0:
            # 删除使用过的令牌
            db_manager.execute_query(
                "DELETE FROM password_reset_tokens WHERE token = %(token)s",
                {"token": token}
            )
            return {"success": True, "message": "密码重置成功"}
        else:
            return {"success": False, "message": "密码重置失败"}

user_manager = UserManager()
