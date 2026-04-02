from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from assistant.enums import ResumeStatus


class ResumeResponse(BaseModel):
    """简历响应模型"""
    id: int
    user_id: int
    file_path: str
    file_type: str
    status: ResumeStatus
    created_at: datetime
    updated_at: datetime
    extracted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ResumeEducationResponse(BaseModel):
    """教育经历响应模型"""
    id: int
    resume_id: int
    school_name: str
    degree: str
    major: str
    start_date: datetime
    end_date: datetime
    is_985: bool
    is_211: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResumeWorkExperienceResponse(BaseModel):
    """工作经历响应模型"""
    id: int
    resume_id: int
    company_name: str
    position: str
    start_date: datetime
    end_date: datetime
    description: str = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResumeSkillResponse(BaseModel):
    """技能响应模型"""
    id: int
    resume_id: int
    skill_name: str
    proficiency_level: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResumeProjectResponse(BaseModel):
    """项目经历响应模型"""
    id: int
    resume_id: int
    project_name: str
    description: str = None
    start_date: datetime
    end_date: datetime
    role: str = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
