from typing import Optional, List
from pydantic import BaseModel


class KnowledgeBaseResponse(BaseModel):
    """知识库响应"""
    id: int
    name: str
    description: str
    user_id: int
    role: str
    project: str
    version: int
    chunking_strategy: str
    chunking_identifier: Optional[List[str]]
    chunk_length: int
    merge_small_chunks: bool
    enabled: bool
    created_at: str
    updated_at: str