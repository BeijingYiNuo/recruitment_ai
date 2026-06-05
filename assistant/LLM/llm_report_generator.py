"""
面试报告生成器
收集面试全链路数据，调用 LLM 生成结构化面试报告
"""

import json
import time
from typing import Optional, Tuple, List
from openai import AsyncOpenAI
from sqlalchemy.orm import Session
from assistant.config.config_manager import ConfigManager
from assistant.utils.logger import logger
from assistant.entity import (
    InterviewSession, Resume, ResumeEducation,
    ResumeWorkExperience, ResumeSkill, ResumeProject,
    Position
)
from assistant.entity.tos_file import TosFile
from assistant.file.file_manager import TosFileManager

REPORT_SYSTEM_PROMPT = """你是一位资深技术面试官和人才评估专家。请根据提供的面试完整信息，生成一份结构化的面试评估报告。

## 输出要求
请严格按照以下 JSON 格式输出，不要包含任何 markdown 标记或其他文字。

## 示例输出（仅作格式参考）
{
  "overall_score": "B",
  "tech_match": 78,
  "final_decision": "neutral",
  "risk_level": "medium",
  "ability_indicators": [
    {
      "name": "逻辑思维",
      "score": "B",
      "status": "normal",
      "desc": "能清晰阐述技术方案，逻辑链条完整，但在复杂场景下的推导略显不足",
      "value": 75
    },
    {
      "name": "沟通表达",
      "score": "A",
      "status": "good",
      "desc": "表达流畅，能准确理解问题并给出有针对性的回答",
      "value": 88
    },
    {
      "name": "技术深度",
      "score": "C",
      "status": "abnormal",
      "desc": "对核心框架原理理解停留在使用层面，缺乏源码级认识",
      "value": 55
    },
    {
      "name": "项目匹配度",
      "score": "B",
      "status": "normal",
      "desc": "过往项目经验与岗位要求有一定重合度",
      "value": 72
    }
  ],
  "stage_data": [
    {
      "name": "项目深挖",
      "score": "A",
      "value": 85,
      "insight": "候选人对自己主导的项目细节掌握扎实，能清晰说明技术选型原因和遇到的挑战"
    },
    {
      "name": "基础知识",
      "score": "C",
      "value": 58,
      "insight": "基础知识掌握不够系统，部分核心概念理解有偏差"
    }
  ],
  "abnormal_findings": [
    {
      "item": "分布式事务",
      "finding": "对 Seata AT 模式原理理解有误",
      "detail": "在追问分布式事务实现时，将 TCC 模式与 AT 模式概念混淆",
      "severity": "中",
      "suggested_action": "建议补充 Seata 源码级学习，重点关注 AT 模式的两阶段提交实现"
    }
  ],
  "tech_keywords": [
    { "text": "Java", "freq": "high" },
    { "text": "Spring Boot", "freq": "high" },
    { "text": "MySQL", "freq": "high" },
    { "text": "Redis", "freq": "mid" },
    { "text": "Seata", "freq": "mid" },
    { "text": "Kafka", "freq": "low" }
  ],
  "conclusion": {
    "strengths": [
      "项目实战经验丰富，主导过核心模块的设计与开发",
      "沟通表达能力强，思路清晰"
    ],
    "weaknesses": [
      "基础知识体系不够系统，底层原理理解不足",
      "分布式系统设计经验欠缺"
    ],
    "suggestions": [
      "建议系统学习分布式理论（CAP、BASE、一致性协议）",
      "可以参与更多高并发场景的项目历练"
    ],
    "next_focus": [
      "分布式系统设计能力",
      "源码阅读习惯培养"
    ]
  }
}

## 字段约束（必须严格遵守）
- overall_score: 只能是 "A"、"B"、"C"、"D" 之一
  - A=优秀(90+), B=良好(75-89), C=一般(60-74), D=不足(<60)
- tech_match: 0-100 的整数，代表技术能力与岗位要求的匹配百分比
- final_decision: 只能是 "recommend"（建议录用）、"neutral"（待定）、"not_recommend"（不建议录用）之一
- risk_level: 只能是 "low"、"medium"、"high" 之一
- ability_indicators: 至少 4 个维度，最多 8 个
  - score 只能是 "A"、"B"、"C"、"D" 之一
  - status 只能是 "normal"、"good"、"abnormal" 之一
  - value 是 0-100 的整数评分
  - desc 必须是有实际内容的中文评语，不能为空
- stage_data: 至少 1 项
  - score 只能是 "A"、"B"、"C"、"D" 之一
  - value 是 0-100 的整数
  - insight 必须是有实际内容的中文洞察，不能为空
- abnormal_findings: 没有异常发现时返回空数组 []
  - severity 只能是 "高"、"中"、"低" 之一
- tech_keywords: 至少 5 个关键词
  - freq 只能是 "high"、"mid"、"low" 之一
- conclusion: 每项列表至少 2 条，所有字段不可为空
  - strengths: 优势列表
  - weaknesses: 不足列表
  - suggestions: 建议列表
  - next_focus: 下阶段重点关注列表

## 分析要求
1. 仔细阅读面试对话转录原文，基于候选人的实际回答给出评分，不得凭空编造
2. 每个评分项都应能从对话原文中找到依据
3. ability_indicators 的 desc 必须结合对话中的具体表现来说明
4. 异常发现应基于对话中暴露的技术盲区或风险点
5. 结论中的优点和不足应具体、可操作，避免笼统评价
6. 不要使用 "..." 等占位符，不要使用 "等" 省略，每项都要填写完整内容
7. 所有评语使用中文
8. 每个字段都要有实际内容，不允许空字符串或空数组
"""


class ReportGenerator:
    """面试报告生成器"""

    def __init__(self):
        self.config_manager = ConfigManager()
        llm_config = self.config_manager.get_llm_config()
        self.llm_client = AsyncOpenAI(
            api_key=llm_config['api_key'],
            base_url=llm_config['url'],
            timeout=120,
        )
        self.llm_model = llm_config['model']

    @staticmethod
    def validate_report_schema(data: dict) -> Tuple[bool, List[str]]:
        """校验 LLM 输出的结构化数据是否完整且符合 schema"""
        errors = []

        # 校验 overall_score
        if data.get("overall_score") not in ("A", "B", "C", "D"):
            errors.append(f"overall_score={data.get('overall_score')} 不在 A/B/C/D 中")

        # 校验 tech_match
        tm = data.get("tech_match")
        if not isinstance(tm, int) or tm < 0 or tm > 100:
            errors.append(f"tech_match={tm} 不是 0-100 整数")

        # 校验 final_decision
        if data.get("final_decision") not in ("recommend", "neutral", "not_recommend"):
            errors.append(f"final_decision 无效: {data.get('final_decision')}")

        # 校验 risk_level
        if data.get("risk_level") not in ("low", "medium", "high"):
            errors.append(f"risk_level 无效: {data.get('risk_level')}")

        # 校验 ability_indicators（至少 4 项）
        indicators = data.get("ability_indicators", [])
        if len(indicators) < 4:
            errors.append(f"ability_indicators 数量={len(indicators)}，至少需 4 项")
        for i, ind in enumerate(indicators):
            if ind.get("score") not in ("A", "B", "C", "D"):
                errors.append(f"ability_indicators[{i}].score={ind.get('score')} 无效")
            if ind.get("status") not in ("normal", "good", "abnormal"):
                errors.append(f"ability_indicators[{i}].status={ind.get('status')} 无效")
            if not ind.get("name") or not ind.get("desc"):
                errors.append(f"ability_indicators[{i}] 缺少 name 或 desc")
            val = ind.get("value")
            if not isinstance(val, (int, float)) or val < 0 or val > 100:
                errors.append(f"ability_indicators[{i}].value={val} 不是 0-100 数值")

        # 校验 stage_data（至少 1 项）
        stages = data.get("stage_data", [])
        if len(stages) < 1:
            errors.append("stage_data 为空")
        for i, s in enumerate(stages):
            if s.get("score") not in ("A", "B", "C", "D"):
                errors.append(f"stage_data[{i}].score={s.get('score')} 无效")
            if not s.get("name"):
                errors.append(f"stage_data[{i}] 缺少 name")
            sv = s.get("value")
            if not isinstance(sv, (int, float)) or sv < 0 or sv > 100:
                errors.append(f"stage_data[{i}].value={sv} 不是 0-100 数值")

        # 校验 tech_keywords（至少 5 项）
        keywords = data.get("tech_keywords", [])
        if len(keywords) < 5:
            errors.append(f"tech_keywords 数量={len(keywords)}，至少需 5 项")
        for i, kw in enumerate(keywords):
            if kw.get("freq") not in ("high", "mid", "low"):
                errors.append(f"tech_keywords[{i}].freq={kw.get('freq')} 无效")
            if not kw.get("text"):
                errors.append(f"tech_keywords[{i}] 缺少 text")

        # 校验 conclusion
        conclusion = data.get("conclusion", {})
        if not conclusion:
            errors.append("conclusion 缺失")
        else:
            for field in ("strengths", "weaknesses", "suggestions", "next_focus"):
                items = conclusion.get(field, [])
                if len(items) < 2:
                    errors.append(f"conclusion.{field} 数量={len(items)}，至少需 2 条")
                for j, item in enumerate(items):
                    if not item:
                        errors.append(f"conclusion.{field}[{j}] 为空")

        return len(errors) == 0, errors

    async def generate(self, session_id: int, db: Session, round_id: Optional[int] = None) -> Optional[dict]:
        """
        收集面试数据并调用 LLM 生成结构化报告
        """
        session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
        if not session:
            logger.error(f"面试会话不存在: session_id={session_id}")
            return None

        context_parts = [f"候选人: {session.candidate_name or '未知'}"]

        # 岗位信息
        if session.position_id:
            position = db.query(Position).filter(Position.id == session.position_id).first()
            if position:
                context_parts.append(f"\n## 岗位信息")
                if position.name:
                    context_parts.append(f"岗位名称: {position.name}")
                if position.department:
                    context_parts.append(f"所属部门: {position.department}")
                if position.description:
                    context_parts.append(f"岗位描述: {position.description}")
                if position.requirements:
                    context_parts.append(f"任职要求: {position.requirements}")

        # 候选人简历结构化信息
        if session.resume_id:
            resume = db.query(Resume).filter(Resume.id == session.resume_id).first()
            if resume:
                context_parts.append(f"\n## 候选人简历")
                educations = db.query(ResumeEducation).filter(
                    ResumeEducation.resume_id == resume.id
                ).all()
                for e in educations:
                    tags = []
                    if e.is_985: tags.append("985")
                    if e.is_211: tags.append("211")
                    tag_str = f"({'/'.join(tags)})" if tags else ""
                    context_parts.append(f"教育: {e.school_name or ''} {e.major or ''} {e.degree or ''} {tag_str}")

                work_exps = db.query(ResumeWorkExperience).filter(
                    ResumeWorkExperience.resume_id == resume.id
                ).order_by(ResumeWorkExperience.start_date.desc()).all()
                for w in work_exps:
                    desc = (w.description or "")[:300]
                    context_parts.append(f"工作: {w.company_name or ''} - {w.position or ''} ({desc})")

                skills = db.query(ResumeSkill).filter(
                    ResumeSkill.resume_id == resume.id
                ).all()
                if skills:
                    context_parts.append("技能: " + "、".join([s.skill_name for s in skills if s.skill_name]))

                projects = db.query(ResumeProject).filter(
                    ResumeProject.resume_id == resume.id
                ).order_by(ResumeProject.start_date.desc()).all()
                for p in projects:
                    desc = (p.description or "")[:200]
                    context_parts.append(f"项目: {p.project_name or ''}({p.role or ''}): {desc}")

        # 面试对话转录（.md 文件）
        dialogue_files = db.query(TosFile).filter(
            TosFile.session_id == session_id,
            TosFile.file_type == 'dialogue'
        ).order_by(TosFile.created_at).all()
        if dialogue_files:
            context_parts.append(f"\n## 面试对话转录")
            file_manager = TosFileManager()
            for f in dialogue_files:
                try:
                    result = file_manager.client.get_object(
                        bucket=file_manager.bucket_name,
                        key=f.file_uri
                    )
                    content_bytes = result.read()
                    if content_bytes:
                        context_parts.append(content_bytes.decode('utf-8'))
                except Exception as e:
                    logger.warning(f"[ReportGenerator] 读取对话文件失败: file_id={f.id}, error={e}")

        # 构造 LLM 消息
        context_str = "\n".join(context_parts)
        logger.info(f"[ReportGenerator] session_id={session_id}, 上下文长度={len(context_str)}")

        max_context_len = 40000
        if len(context_str) > max_context_len:
            half = max_context_len // 2
            context_str = context_str[:half] + "\n...(中间内容已截断)...\n" + context_str[-half:]

        messages = [
            {"role": "system", "content": REPORT_SYSTEM_PROMPT},
            {"role": "user", "content": f"请根据以下面试信息生成报告：\n\n{context_str}"}
        ]

        # 调用 LLM（带重试）
        max_attempts = 2
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = await self.llm_client.chat.completions.create(
                    messages=messages,
                    model=self.llm_model,
                    max_tokens=4096,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content.strip()
                report_data = json.loads(content)

                valid, errors = self.validate_report_schema(report_data)
                if valid:
                    report_data["candidate_name"] = session.candidate_name or ""
                    if session.started_at:
                        report_data["interview_date"] = str(session.started_at.date())
                    logger.info(f"[ReportGenerator] session_id={session_id} 报告生成成功")
                    return report_data

                last_error = f"schema 校验失败: {'; '.join(errors[:5])}"
                logger.warning(f"[ReportGenerator] 第{attempt+1}次生成校验失败: {last_error}")

                if attempt < max_attempts - 1:
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user",
                        "content": f"以上输出存在以下问题，请修正后重新输出完整的 JSON：\n" + "\n".join(errors)
                    })
                    continue

            except json.JSONDecodeError as e:
                last_error = f"JSON 解析失败: {e}"
                logger.warning(f"[ReportGenerator] 第{attempt+1}次生成 JSON 解析失败: {e}")
                if attempt < max_attempts - 1:
                    messages.append({
                        "role": "user",
                        "content": f"输出不是有效的 JSON，请确保输出严格的 JSON 格式（不要包含 markdown 代码块标记），重新输出：\n{context_str[:2000]}"
                    })
                    continue
            except Exception as e:
                last_error = f"LLM 调用异常: {e}"
                logger.error(f"[ReportGenerator] LLM 调用失败: {e}")
                if attempt < max_attempts - 1:
                    continue

        logger.error(f"[ReportGenerator] session_id={session_id} 报告生成全部失败: {last_error}")
        return None
