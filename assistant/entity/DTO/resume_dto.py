from pydantic import BaseModel
from datetime import datetime
from typing import Optional


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


class ResumeReviewRequest(BaseModel):
    """简历审核请求模型"""
    decision: str  # PASS / PENDING / FAIL
    comment: Optional[str] = None


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


class BatchUploadUrlItem(BaseModel):
    """批量上传URL - 单个文件信息"""
    filename: str


class BatchUploadUrlRequest(BaseModel):
    """获取批量预签名上传URL的请求"""
    files: list[BatchUploadUrlItem]


class UploadUrlResult(BaseModel):
    """预签名上传URL结果"""
    filename: str
    url: str
    tos_key: str


class BatchUploadUrlResponse(BaseModel):
    """批量预签名上传URL响应"""
    upload_urls: list[UploadUrlResult]


class TosImportItem(BaseModel):
    """TOS导入 - 单个简历信息"""
    tos_key: str
    filename: str
    candidate_name: str = "待解析"


class BatchTosImportRequest(BaseModel):
    """从TOS批量导入简历的请求"""
    resumes: list[TosImportItem]


class ProcessPendingRequest(BaseModel):
    """处理待分析简历的请求（不传 resume_ids 则处理所有待分析的简历）"""
    resume_ids: Optional[list[int]] = None


class ResumeEducationDetail(BaseModel):
    """编辑简历时的教育经历条目"""
    school_name: str = ""
    degree: Optional[str] = ""
    major: Optional[str] = ""
    start_date: Optional[str] = None  # "YYYY-MM-DD"
    end_date: Optional[str] = None
    is_985: Optional[int] = 0
    is_211: Optional[int] = 0


class ResumeWorkExperienceDetail(BaseModel):
    """编辑简历时的工作经历条目"""
    company_name: str = ""
    position: Optional[str] = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = ""


class ResumeSkillDetail(BaseModel):
    """编辑简历时的技能条目"""
    skill_name: str = ""
    proficiency_level: Optional[str] = ""


class ResumeProjectDetail(BaseModel):
    """编辑简历时的项目经历条目"""
    project_name: str = ""
    description: Optional[str] = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    role: Optional[str] = ""


class ResumeUpdateDetailRequest(BaseModel):
    """编辑简历详情请求：一次性提交全部数据，后端 delete-then-insert"""
    candidate_name: Optional[str] = None
    educations: list[ResumeEducationDetail] = []
    work_experiences: list[ResumeWorkExperienceDetail] = []
    skills: list[ResumeSkillDetail] = []
    projects: list[ResumeProjectDetail] = []
