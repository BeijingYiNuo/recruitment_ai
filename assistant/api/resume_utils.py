from assistant.utils.logger import logger
import pdfplumber
from docx import Document
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional
from assistant.LLM.llm_resume_analysis import sync_analyze_resume_with_llm
from assistant.entity import Resume, ResumeStatus, ResumeEducation, ResumeWorkExperience, ResumeSkill, ResumeProject, User
import io
from assistant.enums import UserRole, UserStatus
def extract_text_from_pdf(pdf_path):
    """
    使用 pdfplumber 从 PDF 文件中提取文本
    
    Args:
        pdf_path: PDF 文件路径
    
    Returns:
        提取的文本内容
    """
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"解析 PDF 文件失败: {e}")
    return text


def extract_text_from_docx(docx_path):
    """
    从 Word 文件中提取文本
    
    Args:
        docx_path: Word 文件路径
    
    Returns:
        提取的文本内容
    """
    text = ""
    try:
        doc = Document(docx_path)
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
    except Exception as e:
        print(f"解析 Word 文件失败: {e}")
    return text


def extract_text(file_path: str, file_bytes: bytes):
    """
    根据文件类型提取文本
    
    Args:
        file_path: 文件路径
        file_bytes: 文件内容
    
    Returns:
        提取的文本内容
    """
    file_extension = os.path.splitext(file_path)[1].lower()
    try:
        # 2. 按文件类型提取文本
        if file_extension == ".pdf":
            return extract_text_from_pdf_stream(file_bytes)
        elif file_extension in [".docx", ".doc"]:
            return extract_text_from_docx_stream(file_bytes)
        else:
            # 文本文件：直接解码
            return file_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"简历文本提取失败: {e}")
        return ""

def extract_text_from_pdf_stream(pdf_bytes: bytes) -> str:
    """从PDF二进制流提取文本（PyPDF2实现）"""
    from PyPDF2 import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "".join([page.extract_text() or "" for page in reader.pages])


def extract_text_from_docx_stream(docx_bytes: bytes) -> str:
    """从Word二进制流提取文本"""
    from docx import Document
    doc = Document(io.BytesIO(docx_bytes))
    return "\n".join([para.text for para in doc.paragraphs])

def parse_resume(file_path):
    """
    解析简历文件
    
    Args:
        file_path: 简历文件路径
    
    Returns:
        解析后的结构化数据
    """
    # 提取文本
    text = extract_text(file_path)
    if not text:
        print("提取文本失败")
        return None
    
    print("提取的文本内容:", text[:500], "..." if len(text) > 500 else "")
    
    # 使用 LLM 解析文本
    parsed_data = sync_analyze_resume_with_llm(text)
    if not parsed_data:
        print("LLM 解析失败")
        return None
    
    print("解析结果 (JSON 格式):", json.dumps(parsed_data, ensure_ascii=False, indent=2))
    
    return parsed_data


def store_resume_details(db, resume_id, parsed_data,current_user_id: int):
    """
    存储简历详情到相关表
    
    Args:
        db: 数据库会话
        resume_id: 简历 ID
        parsed_data: 解析后的结构化数据
    """

    person_info = parsed_data.get("person_info", {})
    if person_info:
        # Validate and truncate fields to ensure they fit in database columns
        username = (person_info.get("name") or "")[:50]
        email = (person_info.get("email") or "")[:100]
        # Remove non-digit characters and truncate to 15 digits (reasonable phone number length)
        phone = ''.join(filter(str.isdigit, person_info.get("phone") or ""))[:15]

        db_user = db.query(User).filter(User.username == username).first()
        if db_user:
            db_user.email = email
            db_user.recruiter_id = current_user_id
            db_user.phone = phone
            db.commit()
            logger.info(f"[用户 {username} 已更新]，跳过存储")
        else:
            db_user = User(
                username=username,
                recruiter_id=current_user_id,
                email=email,
                phone=phone,
                role=UserRole.CANDIDATE,
                status=UserStatus.ACTIVATE,
            )
            db.add(db_user)
    
    # 存储教育经历
    for edu in parsed_data.get("educations", []):
        # 处理日期字段，确保不为 None
        start_date_str = edu.get("start_date", "2023-01-01")
        end_date_str = edu.get("end_date", "2023-12-31")
        
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d") if start_date_str else datetime.now()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d") if end_date_str else datetime.now()
        except (ValueError, TypeError):
            start_date = datetime.now()
            end_date = datetime.now()
        
        db_education = ResumeEducation(
            resume_id=resume_id,
            school_name=(edu.get("school_name") or "")[:100],
            degree=(edu.get("degree") or "")[:50],
            major=(edu.get("major") or "")[:100],
            start_date=start_date,
            end_date=end_date,
            is_985=edu.get("is_985", 0),
            is_211=edu.get("is_211", 0)
        )
        db.add(db_education)
    
    # 存储工作经历
    for work in parsed_data.get("work_experiences", []):
        # 处理日期字段，确保不为 None
        start_date_str = work.get("start_date", "2023-01-01")
        end_date_str = work.get("end_date", "2023-12-31")
        
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d") if start_date_str else datetime.now()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d") if end_date_str else datetime.now()
        except (ValueError, TypeError):
            start_date = datetime.now()
            end_date = datetime.now()
        
        db_work = ResumeWorkExperience(
            resume_id=resume_id,
            company_name=(work.get("company_name") or "")[:100],
            position=(work.get("position") or "")[:100],
            start_date=start_date,
            end_date=end_date,
            description=work.get("description") or ""
        )
        db.add(db_work)
    
    # 存储技能
    for skill in parsed_data.get("skills", []):
        db_skill = ResumeSkill(
            resume_id=resume_id,
            skill_name=(skill.get("skill_name") or "")[:100],
            proficiency_level=(skill.get("proficiency_level") or "")[:20]
        )
        db.add(db_skill)
    
    # 存储项目经历
    for project in parsed_data.get("projects", []):
        # 处理日期字段，确保不为 None
        start_date_str = project.get("start_date", "2023-01-01")
        end_date_str = project.get("end_date", "2023-12-31")
        
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d") if start_date_str else datetime.now()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d") if end_date_str else datetime.now()
        except (ValueError, TypeError):
            start_date = datetime.now()
            end_date = datetime.now()
        
        db_project = ResumeProject(
            resume_id=resume_id,
            project_name=(project.get("project_name") or "")[:100],
            description=project.get("description") or "",
            start_date=start_date,
            end_date=end_date,
            role=(project.get("role") or "")[:100]
        )
        db.add(db_project)
    
    db.commit()
    if username:
        return username
    else:
        return "未知"


def process_resume(db, user_id, file_path, file_type):
    """
    处理简历文件，包括解析和存储
    
    Args:
        db: 数据库会话
        user_id: 用户 ID
        file_path: 简历文件路径
        file_type: 文件类型
    
    Returns:
        简历 ID 和解析结果
    """
    try:
        # 提取文本
        content = extract_text(file_path)
        
        # 解析简历
        parsed_data = parse_resume(file_path)
        if not parsed_data:
            print("解析失败")
            return None, None
        
        return None, parsed_data
    except Exception as e:
        print(f"处理简历失败: {e}")
        db.rollback()
        return None, None


async def process_resume_background(db, resume_id, resume_text: str, current_user_id: int):
    """
    后台处理简历分析
    
    Args:
        db: 数据库会话
        resume_id: 简历 ID
        file_path: 简历文件路径
        file_type: 文件类型
    """
    try:
        from assistant.LLM.llm_resume_analysis import analyze_resume_with_llm
        
        # 1. 解析简历（直接使用异步函数）
        parsed_data = await analyze_resume_with_llm(resume_text)

        # 2. 查询简历记录
        resume = db.query(Resume).filter(Resume.id == resume_id).first()
        if not resume:
            print(f"后台任务错误：简历{resume_id}不存在")
            return
        # 3. 存储解析结果
        if parsed_data:
            candidate_name = store_resume_details(db, resume_id, parsed_data,current_user_id)
            resume.status = ResumeStatus.ANALYZED
            resume.extracted_at = datetime.now()
            resume.candidate_name = candidate_name
            db.commit()
        else:
            resume.status = ResumeStatus.FAILED_ANALYSIS
            db.commit()
    
    except Exception as e:
        logger.error(f"简历{resume_id}后台分析失败: {str(e)}")
        resume = db.query(Resume).filter(Resume.id == resume_id).first()
        if resume:
            resume.status = ResumeStatus.FAILED_ANALYSIS
            db.commit()
        db.rollback()
