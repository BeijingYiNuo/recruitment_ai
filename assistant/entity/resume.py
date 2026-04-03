from sqlalchemy import Column, Integer, String, DateTime, Enum, Text, func
from sqlalchemy.orm import relationship
from assistant.config.database import Base
from assistant.enums import ResumeStatus


class Resume(Base):
    """简历表"""
    __tablename__ = "resume"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="简历ID")
    user_id = Column(Integer, nullable=False, comment="面试官ID")
    file_path = Column(String(255), nullable=False, comment="简历文件路径")
    candidate_name = Column(String(20), nullable=False, comment="候选人姓名")
    file_type = Column(String(100), nullable=False, comment="文件类型")
    status = Column(Enum(ResumeStatus), nullable=False, default=ResumeStatus.UPLOADED, comment="状态")
    content = Column(Text, comment="简历原始文本内容")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    extracted_at = Column(DateTime, comment="提取时间")
    
    # 逻辑关联关系
    # 与User的关系（多对一）
    # 与ResumeEducation的关系（一对多）
    # 与ResumeWorkExperience的关系（一对多）
    # 与ResumeSkill的关系（一对多）
    # 与ResumeProject的关系（一对多）
    # 与InterviewSession的关系（一对多）


class ResumeEducation(Base):
    """教育经历表"""
    __tablename__ = "resume_education"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="教育经历ID")
    resume_id = Column(Integer, nullable=False, comment="所属简历ID")
    school_name = Column(String(100), nullable=False, comment="学校名称")
    degree = Column(String(50), comment="学位")
    major = Column(String(100), comment="专业")
    start_date = Column(DateTime, comment="开始日期")
    end_date = Column(DateTime, comment="结束日期")
    is_985 = Column(Integer, default=0, comment="是否985院校")
    is_211 = Column(Integer, default=0, comment="是否211院校")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 逻辑关联关系
    # 与Resume的关系（多对一）


class ResumeWorkExperience(Base):
    """工作经历表"""
    __tablename__ = "resume_work_experience"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="工作经历ID")
    resume_id = Column(Integer, nullable=False, comment="所属简历ID")
    company_name = Column(String(100), nullable=False, comment="公司名称")
    position = Column(String(100), comment="职位")
    start_date = Column(DateTime, comment="开始日期")
    end_date = Column(DateTime, comment="结束日期")
    description = Column(Text, comment="工作描述")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 逻辑关联关系
    # 与Resume的关系（多对一）


class ResumeSkill(Base):
    """技能表"""
    __tablename__ = "resume_skill"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="技能ID")
    resume_id = Column(Integer, nullable=False, comment="所属简历ID")
    skill_name = Column(String(100), nullable=False, comment="技能名称")
    proficiency_level = Column(String(20), comment="熟练程度")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 逻辑关联关系
    # 与Resume的关系（多对一）


class ResumeProject(Base):
    """项目经历表"""
    __tablename__ = "resume_project"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="项目经历ID")
    resume_id = Column(Integer, nullable=False, comment="简历ID")
    project_name = Column(String(100), nullable=False, comment="项目名称")
    description = Column(Text, comment="项目描述")
    start_date = Column(DateTime, comment="开始日期")
    end_date = Column(DateTime, comment="结束日期")
    role = Column(String(100), comment="担任角色")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 逻辑关联关系
    # 与Resume的关系（多对一）
