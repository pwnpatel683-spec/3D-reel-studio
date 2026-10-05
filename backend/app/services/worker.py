"""
3D Reel Studio — In-Process Bounded Job Worker & Execution Manager
Phase 15: Production Deployment & Background Processing
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Set
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import logger


class JobWorkerManager:
    """
    Lightweight, in-process asynchronous job manager providing:
    - Bounded concurrency via Semaphores (e.g. MAX_CONCURRENT_RENDERS)
    - Non-blocking execution of heavy synchronous/CPU/GPU workloads via ThreadPoolExecutor
    - Unique job tracking, timeout envelopes, and safe cancellation
    - Clean error handling preventing stuck 'processing' states
    """

    def __init__(self, max_concurrent_renders: Optional[int] = None):
        self._max_renders = max_concurrent_renders or settings.MAX_CONCURRENT_RENDERS
        self._render_semaphore = asyncio.Semaphore(self._max_renders)
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="reel-worker")
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._cancelled_jobs: Set[str] = set()

    @property
    def max_concurrent_renders(self) -> int:
        return self._max_renders

    @property
    def active_job_count(self) -> int:
        return len(self._active_tasks)

    def is_job_active(self, job_id: str) -> bool:
        task = self._active_tasks.get(job_id)
        return task is not None and not task.done()

    def cancel_job(self, job_id: str) -> bool:
        """Marks a job as cancelled and cancels the underlying asyncio task if active."""
        self._cancelled_jobs.add(job_id)
        task = self._active_tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()
            logger.info(f"[JobWorkerManager] Cancelled active task for job '{job_id}'")
            return True
        return False

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled_jobs

    async def run_render_task(
        self,
        job_id: str,
        func: Callable[..., Any],
        *args: Any,
        timeout_seconds: Optional[int] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Executes a render task within bounded semaphore concurrency and timeout limit.
        """
        timeout = timeout_seconds or settings.RENDER_TIMEOUT_SECONDS
        loop = asyncio.get_running_loop()

        async with self._render_semaphore:
            if self.is_cancelled(job_id):
                raise asyncio.CancelledError(f"Job '{job_id}' was cancelled before execution.")

            async def _execute():
                return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))

            task = asyncio.create_task(_execute())
            self._active_tasks[job_id] = task

            try:
                result = await asyncio.wait_for(task, timeout=timeout)
                return result
            except asyncio.TimeoutError:
                logger.error(f"[JobWorkerManager] Job '{job_id}' timed out after {timeout}s.")
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail={"code": "JOB_TIMEOUT", "message": f"Processing job timed out after {timeout} seconds."},
                )
            except asyncio.CancelledError:
                logger.warning(f"[JobWorkerManager] Job '{job_id}' execution cancelled.")
                raise
            except Exception as e:
                logger.error(f"[JobWorkerManager] Error executing job '{job_id}': {e}", exc_info=True)
                raise
            finally:
                self._active_tasks.pop(job_id, None)
                self._cancelled_jobs.discard(job_id)

    def shutdown(self) -> None:
        """Gracefully shuts down threadpool and cancels pending tasks."""
        logger.info("[JobWorkerManager] Shutting down job worker executor...")
        for jid, task in list(self._active_tasks.items()):
            if not task.done():
                task.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)


# Global singleton worker manager
worker_manager = JobWorkerManager()
