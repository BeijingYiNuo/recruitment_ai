"""
批量简历处理（Phase 2 + Phase 3：LLM分析 → TOS上传 → DB写入）
设计为在独立 worker 进程中运行，与 FastAPI 进程隔离。

前置条件（已在 API 中完成）：
  Phase 1: 文件已保存到本地临时目录、任务已写入 task_queue
Worker 处理：
  Phase 2: 读取本地文件 → LLM 分析（PDF转图片 + Vision API）
  Phase 3: TOS 上传 + 查重 → 创建或更新 Resume 记录（一次性写入）
"""
import asyncio
import os
from pathlib import Path

from assistant.config.database import SessionLocal
from assistant.api.resume_utils import (
    analyze_resume_only,
    create_or_update_resume,
    background_thread_pool,
    get_file_manager,
)
from assistant.utils.logger import logger

# ========== 并发参数（独立控制，不与 API 进程争抢）==========
MAX_CONCURRENT_ANALYSIS = int(os.getenv("WORKER_RESUME_CONCURRENT_ANALYSIS", "4"))
analysis_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSIS)


async def process_batch_resumes(task_id: int, payload: dict) -> None:
    """
    处理批量简历导入任务 — 每份简历分析完立即写入 DB，
    前端轮询即可实时感知状态变化。
    """
    user_id = payload["user_id"]
    files = payload["files"]

    logger.info(f"[Task {task_id}] 开始处理 {len(files)} 份简历")

    async def _analyze_and_save(item: dict) -> bool:
        """分析单份简历 → 上传 TOS → 查重 → 写入 DB（一次性）"""
        async with analysis_semaphore:
            try:
                file_bytes = Path(item["local_path"]).read_bytes()

                # Phase 2: LLM 分析
                parsed_data = await analyze_resume_only(file_bytes, item["filename"])
                if not parsed_data:
                    logger.warning(f"[Task {task_id}] 简历 {item['filename']} 分析结果为空")
                    return False

                # Phase 3: 上传 TOS + 查重 + 写 DB（同步操作，放线程池避免阻塞事件循环）
                loop = asyncio.get_event_loop()

                def _save():
                    session = SessionLocal()
                    try:
                        # 上传到 TOS（仅有效简历才上传）
                        tos_key = None
                        if parsed_data.get("is_resume", True):
                            fm = get_file_manager()
                            tos_result = fm.upload_file(
                                db=session, user_id=user_id,
                                file_content=file_bytes, filename=item["filename"],
                                file_type="resume"
                            )
                            tos_key = tos_result["tos_key"]
                            if fm.cache:
                                fm.cache.put(tos_key, file_bytes)

                        # 写入 DB（查重 + 创建/更新）
                        resume_id = create_or_update_resume(
                            session, parsed_data, user_id, tos_key, item["filename"]
                        )
                        return resume_id is not None
                    except Exception as e:
                        session.rollback()
                        logger.error(f"[Task {task_id}] 保存失败 [{item['filename']}]: {e}")
                        return False
                    finally:
                        session.close()

                success = await loop.run_in_executor(background_thread_pool, _save)
                if success:
                    logger.info(f"[Task {task_id}] 简历 {item['filename']} 解析完成 → DB 已写入")
                return success
            except Exception as e:
                logger.error(f"[Task {task_id}] 处理失败 [{item['filename']}]: {e}")
                return False

    results = await asyncio.gather(
        *[_analyze_and_save(item) for item in files],
        return_exceptions=True
    )

    successes = sum(1 for r in results if r is True)
    logger.info(f"[Task {task_id}] 完成，{successes}/{len(files)} 份保存成功")

    # ========== 清理本地临时文件 ==========
    for item in files:
        try:
            Path(item["local_path"]).unlink(missing_ok=True)
        except Exception:
            pass

    local_paths = [Path(f["local_path"]) for f in files]
    if local_paths:
        batch_dir = local_paths[0].parent
        try:
            batch_dir.rmdir()
        except OSError:
            pass

    logger.info(f"[Task {task_id}] 批量处理完成")
