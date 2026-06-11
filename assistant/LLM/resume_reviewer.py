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


async def batch_ai_review_resumes(
    resumes_details: list[dict], position: str, jd: str,
    custom_requirements: str, headcount: int
) -> list[dict]:
    """
    批量横向比较审核简历：将所有候选人一次性发给 LLM 进行横向比较，
    并强制按 1:3 比例控制通过/待定人数上限。

    Args:
        resumes_details: list[dict]，每个 dict 含 resume_id, candidate_name, educations, work_experiences, skills, projects
        position: 岗位名称
        jd: 岗位描述
        custom_requirements: 自定义要求
        headcount: 需求人数

    Returns:
        list[dict]，每个 dict 含 resume_id, candidate_name, suggestion, reason, matched_points, gaps
    """
    try:
        max_passing = headcount * 3
        prompt_manager = PromptManager()

        # 格式化候选人列表文本
        candidates_lines = []
        for i, rd in enumerate(resumes_details, start=1):
            details = {k: v for k, v in rd.items() if k != "resume_id"}
            details_text = json.dumps(details, ensure_ascii=False, indent=2)
            candidates_lines.append(f"## 候选人{i}（{rd.get('candidate_name', f'候选人{i}')}）\n{details_text}")

        candidates_text = "\n\n".join(candidates_lines)

        prompt = prompt_manager.generate_prompt(
            user_id="",
            template_name="ai_review_batch",
            position=position,
            headcount=str(headcount),
            jd=jd,
            custom_requirements=custom_requirements,
            max_passing=str(max_passing),
            candidates=candidates_text,
        )

        messages = [
            {"role": "system", "content": "你是一位专业的招聘顾问，负责简历横向比较审核"},
            {"role": "user", "content": prompt}
        ]

        response = await client.chat.completions.create(
            model=llm_config.get('model', 'doubao-seed-1-6-251015'),
            messages=messages,
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=4096,
            stream=False,
        )

        content = response.choices[0].message.content
        llm_results = _extract_json_array(content)

        # 将 LLM 返回的结果映射回 resume_id
        result_map = {}
        for rd in resumes_details:
            result_map[rd.get("candidate_name", "")] = rd["resume_id"]

        mapped_results = []
        for item in llm_results:
            candidate_name = item.get("candidate_name", "")
            resume_id = result_map.get(candidate_name)
            if resume_id is None:
                # 如果根据姓名找不到，尝试用 index 字段（用户可能修改了姓名）
                idx = item.get("index", 0)
                if 1 <= idx <= len(resumes_details):
                    resume_id = resumes_details[idx - 1]["resume_id"]
                    candidate_name = resumes_details[idx - 1].get("candidate_name", candidate_name)
                else:
                    continue
            mapped_results.append({
                "resume_id": resume_id,
                "candidate_name": candidate_name,
                "suggestion": item.get("suggestion", "PENDING"),
                "reason": item.get("reason", ""),
                "matched_points": item.get("matched_points", []),
                "gaps": item.get("gaps", []),
            })

        logger.info(f"批量横向比较审核完成，共 {len(mapped_results)} 份简历")
        return mapped_results

    except Exception as e:
        logger.error(f"批量横向比较审核失败: {e}")
        import traceback
        traceback.print_exc()
        # 降级：逐个返回 PENDING
        return [
            {
                "resume_id": rd["resume_id"],
                "candidate_name": rd.get("candidate_name", ""),
                "suggestion": "PENDING",
                "reason": f"AI 横向比较分析失败: {str(e)}",
                "matched_points": [],
                "gaps": [],
            }
            for rd in resumes_details
        ]


def _extract_json_array(response_content: str) -> list:
    """从 LLM 响应中提取 JSON 数组"""
    import re
    try:
        return json.loads(response_content)
    except (json.JSONDecodeError, TypeError):
        pass

    match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', response_content)
    candidate = match.group(1) if match else response_content

    candidate = candidate.replace("'", '"')
    candidate = re.sub(r",\s*}", "}", candidate)
    candidate = re.sub(r",\s*]", "]", candidate)

    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        pass

    # 尝试从响应中寻找 JSON 数组片段
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(candidate):
        try:
            obj, end = decoder.raw_decode(candidate[idx:])
            if isinstance(obj, list):
                return obj
            idx += end
        except json.JSONDecodeError:
            idx += 1

    logger.error(f"JSON数组解析失败: {response_content[:200]}")
    return []


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
