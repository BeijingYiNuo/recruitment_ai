import mysql.connector
from mysql.connector import Error
from typing import Optional, Dict, Any

class DBManager:
    def __init__(self):
        self.connection = None
    
    def connect(self):
        """
        连接到MySQL数据库
        """
        try:
            self.connection = mysql.connector.connect(
                host='127.0.0.1',
                port=3307,
                user='root',
                password='123456',
                database='ai_recruitment'
            )
            if self.connection.is_connected():
                return True
        except Error as e:
            print(f"数据库连接错误: {e}")
            return False
    
    def disconnect(self):
        """
        断开数据库连接
        """
        if self.connection and self.connection.is_connected():
            self.connection.close()
    
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None):
        """
        执行SQL查询
        
        Args:
            query: SQL查询语句
            params: 查询参数
            
        Returns:
            tuple: (是否成功, 结果或错误信息)
        """
        if not self.connection or not self.connection.is_connected():
            if not self.connect():
                print("数据库连接失败")
                return False, "数据库连接失败"
        
        try:
            cursor = self.connection.cursor(dictionary=True)
            if params:
                print(f"执行查询: {query}")
                print(f"参数: {params}")
                cursor.execute(query, params)
            else:
                print(f"执行查询: {query}")
                cursor.execute(query)
            
            if query.strip().upper().startswith('SELECT'):
                result = cursor.fetchall()
                print(f"查询结果: {result}")
            else:
                self.connection.commit()
                result = cursor.rowcount
                print(f"影响行数: {result}")
            
            cursor.close()
            return True, result
        except Error as e:
            print(f"执行查询错误: {e}")
            return False, f"执行查询错误: {e}"
    
    def init_database(self):
        """
        初始化数据库表结构
        """
        # 创建用户表
        create_users_table = """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            email VARCHAR(100) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """
        
        # 创建密码重置令牌表
        create_reset_tokens_table = """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            token VARCHAR(255) NOT NULL UNIQUE,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """
        
        # 执行创建表的SQL
        success1, _ = self.execute_query(create_users_table)
        success2, _ = self.execute_query(create_reset_tokens_table)
        
        return success1 and success2

db_manager = DBManager()
