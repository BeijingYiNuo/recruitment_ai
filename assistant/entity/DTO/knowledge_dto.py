from pydantic import BaseModel, Field


class CreateKnowledgeBaseRequest(BaseModel):
    """创建知识库请求"""
    name: str = Field(..., description="知识库名称", min_length=1, max_length=128)
    description: str = Field(..., description="知识库描述信息")