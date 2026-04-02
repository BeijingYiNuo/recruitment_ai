from pydantic import BaseModel
from datetime import datetime


class ResumeCreate(BaseModel):
    """简历创建模型"""
    user_id: int
    file_path: str
    file_type: str
    content: str = None


class ResumeUpdate(BaseModel):
    """简历更新模型"""
    user_id: int = None
    file_path: str = None
    file_type: str = None
    status: str = None
    content: str = None


class ResumeEducationCreate(BaseModel):
    """教育经历创建模型"""
    resume_id: int
    school_name: str
    degree: str
    major: str
    start_date: datetime
    end_date: datetime
    is_985: bool = False
    is_211: bool = False


class ResumeWorkExperienceCreate(BaseModel):
    """工作经历创建模型"""
    resume_id: int
    company_name: str
    position: str
    start_date: datetime
    end_date: datetime
    description: str = None


class ResumeSkillCreate(BaseModel):
    """技能创建模型"""
    resume_id: int
    skill_name: str
    proficiency_level: str


class ResumeProjectCreate(BaseModel):
    """项目经历创建模型"""
    resume_id: int
    project_name: str
    description: str = None
    start_date: datetime
    end_date: datetime
    role: str = None
