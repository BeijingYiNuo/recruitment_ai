from openai import AsyncOpenAI
import json
import asyncio
from typing import Dict, Any
from assistant.config.config_manager import ConfigManager
from assistant.utils.logger import logger
import re
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
你是一个严格的JSON生成器，不允许输出任何解释性文本。

你的任务是：从简历中提取信息，并输出【完全合法的JSON字符串】。

⚠️ 强制要求（必须遵守）：
1. 只能输出 JSON，不允许任何额外文字（包括解释、注释、Markdown）
2. JSON 必须能被 Python 的 json.loads() 正确解析
3. 所有 key 必须使用双引号
4. 所有字符串必须使用双引号
5. 不允许出现多余逗号
6. 不允许使用中文标点
7. 所有字段必须存在，不允许缺失

字段规则：
- 不存在的值必须为 null（不能是 "" 或 "无"）
- 年龄 age 必须是整数（例如 25），否则为 null
- is_985 / is_211 必须是整数 0 或 1，无法判断则为 null
- 日期必须为 "YYYY-MM-DD"，无法确定则为 null
- 所有文本字段必须是字符串或 null

简历内容如下：
{resume_text}

输出 JSON 格式如下（必须严格一致）：

{
  "person_info": {
    "name": "string or null",
    "age": number or null,
    "gender": "string or null",
    "phone": "string or null",
    "email": "string or null",
    "address": "string or null"
  },
  "educations": [
    {
      "school_name": "string or null",
      "degree": "string or null",
      "major": "string or null",
      "start_date": "YYYY-MM-DD or null",
      "end_date": "YYYY-MM-DD or null",
      "is_985": 0 or 1 or null,
      "is_211": 0 or 1 or null
    }
  ],
  "work_experiences": [
    {
      "company_name": "string or null",
      "position": "string or null",
      "start_date": "YYYY-MM-DD or null",
      "end_date": "YYYY-MM-DD or null",
      "description": "string or null"
    }
  ],
  "skills": [
    {
      "skill_name": "string or null",
      "proficiency_level": "string or null"
    }
  ],
  "projects": [
    {
      "project_name": "string or null",
      "description": "string or null",
      "start_date": "YYYY-MM-DD or null",
      "end_date": "YYYY-MM-DD or null",
      "role": "string or null"
    }
  ]
}

⚠️ 最终输出必须是一个纯 JSON 字符串，不允许有任何前后缀内容。
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
        # 构建提示词 - 使用字符串替换避免format方法的花括号冲突
        prompt = RESUME_ANALYSIS_PROMPT.replace('{resume_text}', resume_text)
        
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
        # 尝试清理 JSON 字符串
        parsed_data = extract_json_safe(response_content)
        logger.info(f"解析后的数据: {parsed_data}")
        return parsed_data
        
        
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
def extract_json_safe(response_content):
    try:
        # 1️⃣ 优先直接解析
        return json.loads(response_content)
    except:
        pass

    # 2️⃣ 尝试从 ```json 块提取
    match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', response_content)
    if match:
        candidate = match.group(1)
    else:
        candidate = response_content

    # 3️⃣ 清洗
    candidate = candidate.replace("'", '"')
    candidate = re.sub(r",\s*}", "}", candidate)
    candidate = re.sub(r",\s*]", "]", candidate)

    # 4️⃣ 用 decoder 找 JSON
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(candidate):
        try:
            obj, end = decoder.raw_decode(candidate[idx:])
            return obj
        except json.JSONDecodeError:
            idx += 1

    # 5️⃣ 彻底失败
    logger.error("JSON解析失败")
    logger.error(f"原始内容: {response_content}")

    return {
        "person_info": None,
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
