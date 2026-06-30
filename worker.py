"""
独立工作进程：轮询 task_queue 表，处理后台长任务。
与 FastAPI 进程隔离运行，互不抢占 CPU 和事件循环。

启动方式：
    python worker.py                     # 前台运行
    nohup python worker.py > worker.log 2>&1 &   # 后台运行
"""
import asyncio
import os
import sys
from datetime import datetime

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from assistant.config.database import DATABASE_URL, Base
from assistant.entity.task_queue import TaskQueue
from assistant.tasks.resume_batch_processor import process_batch_resumes
from assistant.utils.logger import logger

# ========== 配置 ==========
POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "2"))  # 轮询间隔（秒）

# 独立的数据库引擎和会话工厂（不与 API 进程共享连接池）
_engine = create_engine(DATABASE_URL, pool_recycle=28500, pool_pre_ping=True)
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _ensure_task_table():
    """确保 task_queue 表存在"""
    Base.metadata.create_all(bind=_engine)
    logger.info("task_queue 表已就绪")


def _fetch_pending_task(session) -> TaskQueue:
    """获取一个 PENDING 状态的任务（带行级锁，防止重复消费）"""
    return session.query(TaskQueue).filter(
        TaskQueue.status == "PENDING"
    ).order_by(TaskQueue.id.asc()).with_for_update(skip_locked=True).first()


def _update_task_status(session, task_id: int, status: str, error_message: str = None):
    """更新任务状态"""
    session.query(TaskQueue).filter(TaskQueue.id == task_id).update({
        "status": status,
        "error_message": error_message,
        "updated_at": datetime.now(),
    })
    session.commit()


async def process_task(task_id: int, task_type: str, payload: dict) -> None:
    """根据任务类型分发处理"""
    logger.info(f"[Worker] 开始处理任务 #{task_id}  type={task_type}")

    if task_type == "batch_resume_import":
        await process_batch_resumes(task_id, payload)
    else:
        raise ValueError(f"未知任务类型: {task_type}")

    logger.info(f"[Worker] 任务 #{task_id} 处理完成")


async def _main_loop():
    """主轮询循环"""
    logger.info("=" * 60)
    logger.info("Worker 进程启动 (poll_interval=%ss)", POLL_INTERVAL)
    logger.info("=" * 60)

    while True:
        session = _SessionLocal()
        try:
            task = _fetch_pending_task(session)
            if task is None:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # 设为 PROCESSING
            _update_task_status(session, task.id, "PROCESSING")
            task_id = task.id
            logger.info(f"[Worker] 领取任务 #{task_id}: {task.task_type}")

            # 在独立的 session 中处理（释放当前 session）
            session.close()

            try:
                await process_task(task_id, task.task_type, task.payload)

                # 更新为 COMPLETED
                s = _SessionLocal()
                try:
                    _update_task_status(s, task_id, "COMPLETED")
                finally:
                    s.close()
            except Exception as e:
                logger.error(f"[Worker] 任务 #{task_id} 处理失败: {e}")
                s = _SessionLocal()
                try:
                    _update_task_status(s, task_id, "FAILED", str(e))
                finally:
                    s.close()
        except Exception as e:
            logger.error(f"[Worker] 轮询异常: {e}")
            await asyncio.sleep(1)
        finally:
            try:
                session.close()
            except Exception:
                pass

        await asyncio.sleep(POLL_INTERVAL)


def main():
    """启动 worker 进程"""
    _ensure_task_table()
    try:
        asyncio.run(_main_loop())
    except KeyboardInterrupt:
        logger.info("Worker 进程已停止")


if __name__ == "__main__":
    main()
