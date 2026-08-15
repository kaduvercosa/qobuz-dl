import asyncio
import uuid
import time
from typing import List, Dict, Any, Optional

from app.config_manager import config_manager
from app.progress import progress_manager
from app.qobuz_service import qobuz_service

class QueueTask:
    def __init__(self, url: str, quality_override: Optional[int] = None):
        self.id = str(uuid.uuid4())[:8]
        self.url = url.strip()
        self.quality_override = quality_override
        self.status = "queued"  # queued, downloading, completed, failed, paused
        self.created_at = time.time()

class QueueManager:
    def __init__(self):
        self.queue: List[QueueTask] = []
        self.is_running = False
        self.is_paused = False
        self._worker_tasks: List[asyncio.Task] = []
        self._lock = asyncio.Lock()

    def add_to_queue(self, urls: List[str], quality_override: Optional[int] = None) -> List[Dict[str, Any]]:
        added = []
        for raw_url in urls:
            url = raw_url.strip()
            if not url or url.startswith("#"):
                continue
            task = QueueTask(url=url, quality_override=quality_override)
            self.queue.append(task)
            progress_manager.create_or_update_item(
                item_id=task.id,
                url=task.url,
                title="Na fila de espera...",
                status="queued",
                status_label="NA FILA",
                stage="QUEUED"
            )
            progress_manager.log("INFO", f"Adicionado à fila [{task.id}]: {task.url}", "QUEUE")
            added.append({"id": task.id, "url": task.url, "status": "queued"})
            
        self.ensure_workers()
        return added

    def ensure_workers(self):
        if not self.is_running:
            self.is_running = True
            max_workers = config_manager.config.engine.max_workers
            for i in range(max_workers):
                task = asyncio.create_task(self._worker_loop(i + 1))
                self._worker_tasks.append(task)

    async def _worker_loop(self, worker_id: int):
        while self.is_running:
            if self.is_paused:
                await asyncio.sleep(0.5)
                continue

            task_to_process: Optional[QueueTask] = None
            async with self._lock:
                for t in self.queue:
                    if t.status == "queued":
                        t.status = "downloading"
                        task_to_process = t
                        break

            if task_to_process:
                try:
                    await qobuz_service.process_download(
                        item_id=task_to_process.id,
                        url=task_to_process.url,
                        quality_override=task_to_process.quality_override
                    )
                    task_to_process.status = "completed"
                except Exception as e:
                    task_to_process.status = "failed"
                    progress_manager.mark_failed(task_to_process.id, str(e))
            else:
                await asyncio.sleep(0.5)

    def pause_queue(self):
        self.is_paused = True
        progress_manager.log("WARN", "Fila de downloads pausada pelo usuário.", "QUEUE")

    def resume_queue(self):
        self.is_paused = False
        progress_manager.log("INFO", "Fila de downloads retomada.", "QUEUE")
        self.ensure_workers()

    def clear_completed(self):
        progress_manager.completed_items.clear()
        progress_manager.failed_items.clear()
        self.queue = [t for t in self.queue if t.status not in ("completed", "failed")]
        progress_manager.log("INFO", "Histórico recente limpo.", "QUEUE")

    def cancel_task(self, task_id: str) -> bool:
        for t in self.queue:
            if t.id == task_id:
                t.status = "cancelled"
                progress_manager.mark_failed(task_id, "Cancelado pelo usuário.")
                return True
        return False

queue_manager = QueueManager()
