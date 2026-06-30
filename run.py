import subprocess
import sys
import os
import atexit
import signal

from assistant.app import app
import uvicorn
import argparse

worker_process = None


def start_worker():
    """启动后台 worker 子进程处理任务队列"""
    global worker_process
    script = os.path.join(os.path.dirname(__file__), "worker.py")
    worker_process = subprocess.Popen(
        [sys.executable, script],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    print(f"[run.py] Worker 进程已启动 (PID={worker_process.pid})")


def stop_worker(*args):
    """退出时停止 worker 进程"""
    global worker_process
    if worker_process and worker_process.poll() is None:
        worker_process.terminate()
        worker_process.wait(timeout=5)
        print(f"[run.py] Worker 进程已停止")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8001, help='服务端口')
    parser.add_argument('--no-worker', action='store_true', help='不启动后台 worker')
    args = parser.parse_args()

    if not args.no_worker:
        start_worker()
        atexit.register(stop_worker)
        signal.signal(signal.SIGTERM, stop_worker)
        signal.signal(signal.SIGINT, stop_worker)

    uvicorn.run("assistant.app:app", host="0.0.0.0", port=args.port, reload=False)
