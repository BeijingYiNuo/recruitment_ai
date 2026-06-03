import os
import time
import json
import hashlib
import threading
import shutil
from pathlib import Path
from typing import Optional

from assistant.utils.logger import logger


class LocalFileCache:
    """本地磁盘缓存 —— 用于缓存 TOS 文件，避免反复公网拉取

    设计要点：
    - 线程安全（threading.Lock）
    - SHA256(tos_key) 作为缓存键，两级目录散列避免单目录文件过多
    - JSON 索引文件记录元数据（大小、创建时间、访问时间）
    - LRU 淘汰：缓存超限时删除最久未访问的文件
    - TTL 过期：超过 TTL 的文件自动失效
    - 后台定时清理线程
    - 写穿透（write-through）：流式下载时边读 TOS 边写缓存，首次请求不额外等待
    """

    def __init__(self, cache_dir: str = "/app/file_cache",
                 max_size_gb: int = 1,
                 ttl_hours: int = 24,
                 cleanup_interval_minutes: int = 5):
        self.cache_dir = Path(cache_dir)
        self.tmp_dir = self.cache_dir / "_tmp"
        self.max_size_bytes = max_size_gb * 1024 ** 3
        self.ttl_seconds = ttl_hours * 3600

        self._lock = threading.Lock()
        self._index_path = self.cache_dir / "_index.json"
        self._index: dict[str, dict] = {}

        # 初始化目录
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        # 加载持久化索引
        self._load_index()

        logger.info(
            f"LocalFileCache initialized: dir={cache_dir}, "
            f"max_size={max_size_gb}GB, ttl={ttl_hours}h"
        )

        # 启动后台清理线程
        self._start_cleanup(cleanup_interval_minutes)

    # ==================== 公开方法 ====================

    def get(self, tos_key: str) -> Optional[bytes]:
        """获取缓存文件内容（整个读入内存，适合小文件）"""
        path = self._get_valid_path(tos_key)
        if path is None:
            return None
        try:
            return path.read_bytes()
        except Exception as e:
            logger.warning(f"Cache read error ({tos_key}): {e}")
            return None

    def get_path(self, tos_key: str) -> Optional[Path]:
        """获取缓存文件路径（适合大文件流式读取）

        返回 None 表示未命中或已过期，调用方应回源到 TOS。
        """
        return self._get_valid_path(tos_key)

    def put(self, tos_key: str, content: bytes):
        """将内容写入缓存"""
        path = self._get_file_path(tos_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self._record(tos_key, path, len(content))

    # ==================== 写穿透流式下载支持 ====================

    def get_tmp_path(self, tos_key: str) -> Path:
        """获取临时文件路径（用于写穿透流式下载）"""
        h = self._calc_key(tos_key)
        return self.tmp_dir / h

    def commit_tmp(self, tos_key: str):
        """将临时文件正式提交为缓存文件"""
        tmp_path = self.get_tmp_path(tos_key)
        if not tmp_path.exists():
            logger.warning(f"Tmp file not found, skip commit: {tmp_path}")
            return

        final_path = self._get_file_path(tos_key)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(tmp_path), str(final_path))
        size = final_path.stat().st_size
        self._record(tos_key, final_path, size)

    def discard_tmp(self, tos_key: str):
        """丢弃临时文件（流式下载失败时清理）"""
        tmp_path = self.get_tmp_path(tos_key)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ==================== 内部方法 ====================

    @staticmethod
    def _calc_key(tos_key: str) -> str:
        return hashlib.sha256(tos_key.encode()).hexdigest()

    def _get_file_path(self, tos_key: str) -> Path:
        h = self._calc_key(tos_key)
        return self.cache_dir / h[:2] / h[2:4] / h

    def _get_valid_path(self, tos_key: str) -> Optional[Path]:
        """返回缓存路径，如果不存在或已过期则返回 None"""
        h = self._calc_key(tos_key)
        path = self._get_file_path(tos_key)

        # 检查索引是否存在
        with self._lock:
            info = self._index.get(h)
        if info is None:
            return None

        # 检查文件是否真的存在（应对手动删除等异常）
        if not path.exists():
            self._remove_index(h)
            return None

        # 检查 TTL
        if time.time() - info.get("created_at", 0) > self.ttl_seconds:
            logger.debug(f"Cache expired: {tos_key}")
            self._remove(h)
            return None

        # 更新访问时间
        self._touch(h)
        return path

    def _record(self, tos_key: str, path: Path, size: int):
        h = self._calc_key(tos_key)
        now = time.time()
        with self._lock:
            self._index[h] = {
                "tos_key": tos_key,
                "size": size,
                "created_at": now,
                "accessed_at": now,
            }
            self._save_index()
        self._evict_if_needed()

    def _touch(self, key_hash: str):
        with self._lock:
            info = self._index.get(key_hash)
            if info:
                info["accessed_at"] = time.time()

    def _remove(self, key_hash: str):
        with self._lock:
            info = self._index.pop(key_hash, None)
            self._save_index()
        if info:
            path = self._get_file_path(info["tos_key"])
            try:
                path.unlink(missing_ok=True)
                # 尝试清理空目录
                path.parent.rmdir()
                path.parent.parent.rmdir()
            except OSError:
                pass

    def _remove_index(self, key_hash: str):
        with self._lock:
            self._index.pop(key_hash, None)

    def _load_index(self):
        if self._index_path.exists():
            try:
                with open(self._index_path) as f:
                    self._index = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load cache index: {e}")
                self._index = {}
        # 清理索引中文件已实际不存在的条目
        stale = []
        with self._lock:
            for h, info in self._index.items():
                path = self._get_file_path(info["tos_key"])
                if not path.exists():
                    stale.append(h)
            for h in stale:
                del self._index[h]
            if stale:
                self._save_index()

    def _save_index(self):
        try:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._index_path, 'w') as f:
                json.dump(self._index, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save cache index: {e}")

    def _evict_if_needed(self):
        """LRU 淘汰：缓存总量超限时，删除最久未访问的文件直到低于上限"""
        with self._lock:
            total = sum(v["size"] for v in self._index.values())
            if total <= self.max_size_bytes:
                return

            sorted_items = sorted(
                self._index.items(),
                key=lambda x: x[1]["accessed_at"]
            )
            for h, _ in sorted_items:
                if total <= self.max_size_bytes:
                    break
                info = self._index.pop(h)
                total -= info["size"]
                path = self._get_file_path(info["tos_key"])
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._save_index()
        logger.info(f"Cache eviction done, current index size: {len(self._index)}")

    def cleanup(self):
        """清理过期的缓存条目"""
        now = time.time()
        removed = 0
        with self._lock:
            expired = [
                h for h, v in self._index.items()
                if now - v["created_at"] > self.ttl_seconds
            ]
            for h in expired:
                info = self._index.pop(h)
                path = self._get_file_path(info["tos_key"])
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                removed += 1
            if expired:
                self._save_index()

        # 清理临时目录中残留的文件
        try:
            for f in self.tmp_dir.iterdir():
                if f.is_file():
                    # 超过 1 小时的临时文件视为残留
                    if time.time() - f.stat().st_mtime > 3600:
                        f.unlink(missing_ok=True)
        except OSError:
            pass

        if removed > 0:
            logger.info(f"Cache cleanup: removed {removed} expired entries")

    def _start_cleanup(self, interval_minutes: int):
        def _loop():
            while True:
                time.sleep(interval_minutes * 60)
                try:
                    self.cleanup()
                except Exception as e:
                    logger.error(f"Cache cleanup error: {e}")

        t = threading.Thread(target=_loop, daemon=True, name="cache-cleanup")
        t.start()

    @property
    def size_bytes(self) -> int:
        with self._lock:
            return sum(v["size"] for v in self._index.values())

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._index)
