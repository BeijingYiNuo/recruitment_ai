import logging

# 配置日志
logger = logging.getLogger("uvicorn.error")

# 确保日志处理器已配置
if not logger.handlers:
    # 添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 配置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)

# 导出logger实例
__all__ = ["logger"]
