from openai import AsyncOpenAI
import json
import asyncio
from typing import Dict, Any, AsyncGenerator
from assistant.config.config_manager import ConfigManager
from assistant.utils.logger import logger
from assistant.prompt.prompt_manager import PromptManager

config_manager = ConfigManager()
llm_config = config_manager.get_llm_config()

client = AsyncOpenAI(
    api_key=llm_config.get('api_key'),
    base_url=llm_config.get('url'),
)


async def ai_review_resume(resume_details: dict, position: str, jd: str,
                           custom_requirements: str, headcount: int) -> Dict[str, Any]:
    """
    使用 LLM 辅助审核简历，给出通过/待定/淘汰建议

    Args:
        resume_details: 简历详情 dict（含 candidate_name, educations, work_experiences, skills, projects）
        position: 岗位名称
        jd: 岗位描述
        custom_requirements: 自定义要求
        headcount: 需求人数

    Returns:
        {"suggestion": str, "reason": str, "matched_points": list, "gaps": list}
    """
    try:
        prompt_manager = PromptManager()
        resume_text = json.dumps(resume_details, ensure_ascii=False, indent=2)
        prompt = prompt_manager.generate_prompt(
            user_id="",
            template_name="ai_review",
            position=position,
            headcount=str(headcount),
            jd=jd,
            custom_requirements=custom_requirements,
            resume_details=resume_text,
        )

        messages = [
            {"role": "system", "content": "你是一位专业的招聘顾问，负责简历审核"},
            {"role": "user", "content": prompt}
        ]

        response = await client.chat.completions.create(
            model=llm_config.get('model', 'doubao-seed-1-6-251015'),
            messages=messages,
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=2000,
            stream=False,
        )

        content = response.choices[0].message.content
        result = _extract_json(content)
        logger.info(f"AI 审核建议: {result}")
        return result

    except Exception as e:
        logger.error(f"AI 审核建议生成失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "suggestion": "PENDING",
            "reason": f"AI 分析失败: {str(e)}",
            "matched_points": [],
            "gaps": []
        }


async def generate_interview_questions(resume_details: dict, instruction: str = "") -> Dict[str, Any]:
    """
    根据简历项目经历生成面试提问问题，按项目顺序返回

    Args:
        resume_details: 简历详情 dict（含 candidate_name, projects）
        instruction: 用户额外要求（自然语言），为空则按默认规则生成

    Returns:
        {"questions": [{"project": "项目名", "questions": ["问题1", ...]}, ...]}
    """
    try:
        prompt_manager = PromptManager()
        project_details = json.dumps(
            resume_details.get("projects", []), ensure_ascii=False, indent=2
        )
        prompt = prompt_manager.generate_prompt(
            user_id="",
            template_name="interview_questions",
            candidate_name=resume_details.get("candidate_name", ""),
            project_details=project_details,
            user_instruction=instruction or "无额外要求，按默认规则生成",
        )

        messages = [
            {"role": "system", "content": "你是一位资深技术面试官，负责生成面试问题"},
            {"role": "user", "content": prompt}
        ]

        response = await client.chat.completions.create(
            model=llm_config.get('model', 'doubao-seed-1-6-251015'),
            messages=messages,
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=2000,
            stream=False,
        )

        content = response.choices[0].message.content
        result = _parse_interview_text(content)
        logger.info(f"AI 面试问题: {result}")
        return result

    except Exception as e:
        logger.error(f"面试问题生成失败: {e}")
        import traceback
        traceback.print_exc()
        return {"questions": []}


async def stream_interview_questions(resume_details: dict, instruction: str = "") -> AsyncGenerator[dict, None]:
    """
    流式生成面试提问问题，逐 token 产出事件。

    与 generate_interview_questions 使用相同的 prompt 和 client，
    区别在于 stream=True 且以 async generator 形式 yield 事件。

    Yields:
        {"type": "token", "content": str}  — 增量 token
        {"type": "done", "result": dict}    — 完成（包含完整 JSON）
        {"type": "error", "message": str}   — 出错
    """
    try:
        prompt_manager = PromptManager()
        project_details = json.dumps(
            resume_details.get("projects", []), ensure_ascii=False, indent=2
        )
        prompt = prompt_manager.generate_prompt(
            user_id="",
            template_name="interview_questions",
            candidate_name=resume_details.get("candidate_name", ""),
            project_details=project_details,
            user_instruction=instruction or "无额外要求，按默认规则生成",
        )

        messages = [
            {"role": "system", "content": "你是一位资深技术面试官，负责生成面试问题"},
            {"role": "user", "content": prompt}
        ]

        stream = await client.chat.completions.create(
            model=llm_config.get('model', 'doubao-seed-1-6-251015'),
            messages=messages,
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=2000,
            stream=True,
        )

        full_content = ""

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta:
                content = chunk.choices[0].delta.content or ""
                full_content += content
                if content:
                    yield {"type": "token", "content": content}

        result = _parse_interview_text(full_content)
        logger.info(f"流式面试问题完成: {result}")
        yield {"type": "done", "result": result}

    except asyncio.CancelledError:
        logger.info("流式面试问题生成被取消")
    except Exception as e:
        logger.error(f"流式面试问题生成失败: {e}")
        import traceback
        traceback.print_exc()
        yield {"type": "error", "message": str(e)}


def _parse_interview_text(text: str) -> dict:
    """将带标签的文本格式解析为结构化 JSON。

    输入格式：
        【项目】项目名
        - 问题1
        - 问题2

    输出：
        {"questions": [{"project": "项目名", "questions": ["问题1", "问题2"]}, ...]}
    """
    import re
    questions = []
    current_project = None
    current_questions = []

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue

        proj_match = re.match(r'【项目】(.+)', line)
        if proj_match:
            if current_project:
                questions.append({"project": current_project, "questions": current_questions})
            current_project = proj_match.group(1).strip()
            current_questions = []
        elif line.startswith('-') or line.startswith('·') or line.startswith('*'):
            q_text = line[1:].strip()
            if q_text:
                current_questions.append(q_text)

    if current_project:
        questions.append({"project": current_project, "questions": current_questions})

    return {"questions": questions}


def _extract_json(response_content: str) -> dict:
    """从 LLM 响应中提取 JSON（复用 extract_json_safe 逻辑）"""
    import re
    try:
        return json.loads(response_content)
    except json.JSONDecodeError:
        pass

    match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', response_content)
    candidate = match.group(1) if match else response_content

    candidate = candidate.replace("'", '"')
    candidate = re.sub(r",\s*}", "}", candidate)
    candidate = re.sub(r",\s*]", "]", candidate)

    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(candidate):
        try:
            obj, end = decoder.raw_decode(candidate[idx:])
            if isinstance(obj, dict):
                return obj
            idx += end
        except json.JSONDecodeError:
            idx += 1

    logger.error(f"JSON解析失败: {response_content[:200]}")
    return {}
