"""
面试报告管理器
负责收集面试数据并调用 LLM 生成结构化报告
"""

import json
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session

from assistant.LLM.llm_report_generator import ReportGenerator
from assistant.entity import InterviewReport, ReportStatus
from assistant.utils.logger import logger


class ReportManager:
    """面试报告管理器"""

    def __init__(self):
        self.generator = ReportGenerator()

    async def generate_and_save(self, session_id: int, db: Session, round_id: Optional[int] = None) -> Optional[InterviewReport]:
        """
        生成并保存面试报告

        Args:
            session_id: 面试会话 ID
            db: 数据库会话
            round_id: 面试轮次 ID（可选）

        Returns:
            InterviewReport: 保存后的报告对象，失败返回 None
        """
        # 1. 检查是否已有报告
        query = db.query(InterviewReport).filter(InterviewReport.session_id == session_id)
        if round_id:
            query = query.filter(InterviewReport.round_id == round_id)

        existing = query.first()

        # 如果已有 final 报告，直接返回
        if existing and existing.status == ReportStatus.FINAL:
            logger.info(f"[ReportManager] session_id={session_id}, round_id={round_id} 已有最终报告，直接返回")
            return existing

        # 如果正在生成中，不重复触发，直接返回
        if existing and existing.status == ReportStatus.GENERATING:
            # 检查是否已超时（超过 5 分钟认为上一次生成已挂掉，允许重新生成）
            if existing.generated_at and (datetime.now() - existing.generated_at).total_seconds() < 300:
                logger.info(f"[ReportManager] session_id={session_id}, round_id={round_id} 正在生成中，跳过")
                return existing
            logger.warning(f"[ReportManager] session_id={session_id}, round_id={round_id} 生成超时，重新触发")

        # 2. 创建/更新为 GENERATING 状态占位，保存 ID 以供后续重新查询
        if existing:
            existing.status = ReportStatus.GENERATING
            db.commit()
            db_report_id = existing.id
        else:
            db_report = InterviewReport(
                session_id=session_id,
                round_id=round_id,
                status=ReportStatus.GENERATING,
                generated_at=datetime.now(),
            )
            db.add(db_report)
            db.commit()
            db_report_id = db_report.id

        # 3. 调用 LLM 生成结构化报告
        report_data = await self.generator.generate(session_id, db, round_id=round_id)

        # 4. 通过 ID 重新查询（不依赖 refresh，避免 Enum 映射异常阻断流程）
        db_report = db.query(InterviewReport).filter(InterviewReport.id == db_report_id).first()

        if not db_report:
            logger.error(f"[ReportManager] 报告记录丢失: session_id={session_id}")
            return None

        # 5. 生成完成 → 更新状态
        if report_data:
            report_json = json.dumps(report_data, ensure_ascii=False)
            conclusion = report_data.get("conclusion", {})
            report_summary = (
                f"综合评分: {report_data.get('overall_score', 'N/A')}\n"
                f"推荐意见: {report_data.get('final_decision', 'N/A')}\n"
                f"优势: {'; '.join(conclusion.get('strengths', [])[:3])}\n"
                f"不足: {'; '.join(conclusion.get('weaknesses', [])[:3])}"
            )
            db_report.report_data = report_json
            db_report.report_content = report_summary
            db_report.status = ReportStatus.FINAL
            logger.info(f"[ReportManager] 报告生成成功: report_id={db_report.id}, session_id={session_id}")
        else:
            # 生成失败 → 标记为 FAILED
            db_report.status = ReportStatus.FAILED
            logger.error(f"[ReportManager] 报告生成失败: report_id={db_report.id}, session_id={session_id}")

        db.commit()
        return db_report

    async def get_report(self, session_id: int, db: Session, round_id: Optional[int] = None) -> Optional[dict]:
        """
        获取面试报告数据

        Args:
            session_id: 面试会话 ID
            db: 数据库会话
            round_id: 面试轮次 ID（可选）

        Returns:
            dict: 结构化报告数据（已解析为 dict），不存在返回 None
        """
        query = db.query(InterviewReport).filter(InterviewReport.session_id == session_id)
        if round_id:
            query = query.filter(InterviewReport.round_id == round_id)

        report = query.first()

        if not report or not report.report_data:
            return None

        try:
            return json.loads(report.report_data)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"[ReportManager] 报告数据解析失败: report_id={report.id}, error={e}")
            return None

    async def background_generate(self, report_id: int, session_id: int, round_id: Optional[int] = None):
        """后台异步任务：使用独立数据库会话生成报告并保存结果"""
        from assistant.config.database import SessionLocal

        db = SessionLocal()
        try:
            report_data = await self.generator.generate(session_id, db, round_id=round_id)
            db_report = db.query(InterviewReport).filter(InterviewReport.id == report_id).first()
            if not db_report:
                logger.error(f"[ReportManager] 后台生成: 报告记录不存在 report_id={report_id}")
                return

            if report_data:
                report_json = json.dumps(report_data, ensure_ascii=False)
                conclusion = report_data.get("conclusion", {})
                report_summary = (
                    f"综合评分: {report_data.get('overall_score', 'N/A')}\n"
                    f"推荐意见: {report_data.get('final_decision', 'N/A')}\n"
                    f"优势: {'; '.join(conclusion.get('strengths', [])[:3])}\n"
                    f"不足: {'; '.join(conclusion.get('weaknesses', [])[:3])}"
                )
                db_report.report_data = report_json
                db_report.report_content = report_summary
                db_report.status = ReportStatus.FINAL
                logger.info(f"[ReportManager] 后台报告生成成功: report_id={db_report.id}, session_id={session_id}")
            else:
                db_report.status = ReportStatus.FAILED
                logger.error(f"[ReportManager] 后台报告生成失败: report_id={db_report.id}, session_id={session_id}")

            db.commit()
        except Exception as e:
            logger.error(f"[ReportManager] 后台生成任务异常: {e}", exc_info=True)
            try:
                db.query(InterviewReport).filter(InterviewReport.id == report_id).update({"status": ReportStatus.FAILED})
                db.commit()
            except Exception:
                pass
        finally:
            db.close()
