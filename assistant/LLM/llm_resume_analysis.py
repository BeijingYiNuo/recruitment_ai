from openai import AsyncOpenAI
import json
import asyncio
from typing import Dict, Any
from assistant.config.config_manager import ConfigManager

# 初始化配置管理器
config_manager = ConfigManager()
llm_config = config_manager.get_llm_config()

# 创建 AsyncOpenAI 客户端
client = AsyncOpenAI(
    api_key=llm_config.get('api_key'),
    base_url=llm_config.get('url'),
)

# 简历解析的 prompt 提示词
RESUME_ANALYSIS_PROMPT = """
你是一个专业的简历解析助手，负责将简历文本解析为结构化数据。

请根据以下简历文本，提取相关信息并按照指定的 JSON 格式输出：

{resume_text}

请提取以下信息：
1. 教育经历 (educations)：包括学校名称、学位、专业、开始日期、结束日期、是否985院校、是否211院校
2. 工作经历 (work_experiences)：包括公司名称、职位、开始日期、结束日期、工作描述
3. 技能 (skills)：包括技能名称、熟练程度
4. 项目经历 (projects)：包括项目名称、描述、开始日期、结束日期、担任角色

输出格式必须是 JSON，字段名必须与以下格式一致：
{{
  "educations": [
    {{
      "school_name": "学校名称",
      "degree": "学位",
      "major": "专业",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "is_985": 0或1,
      "is_211": 0或1
    }}
  ],
  "work_experiences": [
    {{
      "company_name": "公司名称",
      "position": "职位",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "description": "工作描述"
    }}
  ],
  "skills": [
    {{
      "skill_name": "技能名称",
      "proficiency_level": "熟练程度"
    }}
  ],
  "projects": [
    {{
      "project_name": "项目名称",
      "description": "项目描述",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "role": "担任角色"
    }}
  ]
}}

请确保输出的 JSON 格式正确，如果简历内容没有对应值则设置为null。
"""

async def analyze_resume_with_llm(resume_text: str) -> Dict[str, Any]:
    """
    使用大模型解析简历文本
    
    Args:
        resume_text: 简历文本内容
    
    Returns:
        解析后的结构化数据
    """
    try:
        # 构建提示词
        prompt = RESUME_ANALYSIS_PROMPT.format(resume_text=resume_text)
        
        # 构建消息
        messages = [
            {"role": "system", "content": "你是一个专业的简历解析助手"},
            {"role": "user", "content": prompt}
        ]
        
        # 调用 LLM
        response = await client.chat.completions.create(
            model=llm_config.get('model', 'doubao-seed-1-6-251015'),
            messages=messages,
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=2000,
            stream=False,
        )
        
        # 解析响应
        response_content = response.choices[0].message.content
        
        # 尝试清理输出，去除可能的额外字符
        import re
        # 提取 JSON 部分
        json_match = re.search(r'\{[\s\S]*\}', response_content)
        if json_match:
            json_content = json_match.group(0)
            try:
                parsed_data = json.loads(json_content)
                return parsed_data
            except Exception as e:
                logger.error(f"JSON 解析失败: {e}")
                import traceback
                traceback.print_exc()
        else:
            logger.error("未找到 JSON 部分")
        
        # 尝试直接解析整个响应
        try:
            parsed_data = json.loads(response_content)
            return parsed_data
        except Exception as e:
            logger.error(f"直接解析失败: {e}")
            import traceback
            traceback.print_exc()
        
        # 如果所有解析都失败，返回默认值
        logger.error("所有解析都失败，返回默认值")
        return {
            "educations": [],
            "work_experiences": [],
            "skills": [],
            "projects": []
        }
    except Exception as e:
        logger.error(f"LLM 解析失败: {e}")
        import traceback
        traceback.print_exc()
        # 返回默认值
        return {
            "educations": [],
            "work_experiences": [],
            "skills": [],
            "projects": []
        }

def sync_analyze_resume_with_llm(resume_text: str) -> Dict[str, Any]:
    """
    同步调用 analyze_resume_with_llm 函数
    
    Args:
        resume_text: 简历文本内容
    
    Returns:
        解析后的结构化数据
    """
    return asyncio.run(analyze_resume_with_llm(resume_text))
