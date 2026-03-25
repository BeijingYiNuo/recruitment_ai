import bcrypt
import uuid
import datetime
from typing import Optional
from jose import JWTError, jwt
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()

# JWT配置
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")  # 实际项目中应该使用环境变量
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

class AuthUtils:
    @staticmethod
    def hash_password(password: str) -> str:
        """
        对密码进行哈希处理
        
        Args:
            password: 原始密码
            
        Returns:
            str: 哈希后的密码
        """
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        验证密码
        
        Args:
            plain_password: 原始密码
            hashed_password: 哈希后的密码
            
        Returns:
            bool: 密码是否正确
        """
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    
    @staticmethod
    def generate_reset_token() -> str:
        """
        生成密码重置令牌
        
        Returns:
            str: 密码重置令牌
        """
        return str(uuid.uuid4())
    
    @staticmethod
    def get_token_expiry() -> datetime.datetime:
        """
        获取令牌过期时间（默认24小时）
        
        Returns:
            datetime.datetime: 过期时间
        """
        return datetime.datetime.now() + datetime.timedelta(hours=24)
    
    @staticmethod
    def create_access_token(data: dict) -> str:
        """
        生成访问令牌
        
        Args:
            data: 要包含在令牌中的数据
            
        Returns:
            str: 生成的JWT令牌
        """
        to_encode = data.copy()
        expire = datetime.datetime.now() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def verify_token(token: str) -> Optional[dict]:
        """
        验证令牌
        
        Args:
            token: 要验证的JWT令牌
            
        Returns:
            Optional[dict]: 令牌中的数据，如果验证失败返回None
        """
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None
