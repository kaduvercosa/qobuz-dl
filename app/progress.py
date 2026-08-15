"""
progress.py
-----------
O downloader.py do qobuz-dl usa `tqdm` pra desenhar a barra de progresso NO
TERMINAL (rich/tqdm.write). Isso é ótimo pra CLI, mas não existe um "terminal"
num backend web -- o que a gente quer é publicar esses mesmos números (bytes
baixados / total) num WebSocket, em tempo real, sem editar o downloader.py
do seu fork.

A solução: um `contextvars.ContextVar` guarda o "job" atual da task asyncio
em execução, e uma subclasse de `tqdm` publica o progresso nesse job toda
vez que `bar.update(n)` é chamado dentro de `tqdm_download`/`tqdm_download_segments`.

No startup do app a gente troca `qobuz_dl.downloader.tqdm` por essa subclasse
(monkeypatch de import, não edição de arquivo). Como cada download roda na
sua própria asyncio Task, e Tasks herdam o contexto de quem as criou, cada
job "vê" só o próprio progresso -- sem race condition entre downloads
paralelos.
"""
import asyncio
import contextvars
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from uuid import uuid4

from tqdm import tqdm as _RealTqdm

current_job: contextvars.ContextVar[Optional["Job"]] = contextvars.ContextVar(
    "current_job", default=None
)


@dataclass
class Job:
    id: str
    url: str
    status: str = "queued"          # queued | running | done | error | cancelled
    content_name: str = ""          # nome do álbum/artista/playlist resolvido
    track_name: str = ""            # faixa atual
    track_index: int = 0
    track_total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    error: Optional[str] = None
    queue: "asyncio.Queue" = field(default_factory=asyncio.Queue)
    created_at: float = field(default_factory=time.time)
    # Pasta temporária exclusiva deste job (ver JOBS_ROOT em qobuz_service.py).
    # Fica None depois que os arquivos já foram entregues/removidos pelo
    # endpoint /api/download/{job_id}/file, ou se o job nunca baixou nada.
    job_dir: Optional[str] = None
    # Metadados só pra exibição na fila (capa, artista, nº de faixas do
    # álbum/playlist, ano, hi-res) -- resolvidos uma vez no início do job em
    # qobuz_service.run_download_job, não afetam o download em si.
    cover_url: Optional[str] = None
    artist: Optional[str] = None
    content_type: Optional[str] = None       # album | track | playlist | artist | label
    content_tracks_count: Optional[int] = None
    year: Optional[str] = None
    hires: Optional[bool] = None
    # Fila real (ver JobManager abaixo): posição 1-indexed enquanto "queued",
    # None assim que começa a rodar. task guarda a asyncio.Task pra dar cancel().
    position: Optional[int] = None
    cancel_requested: bool = False
    task: Optional["asyncio.Task"] = field(default=None, repr=False, compare=False)

    def snapshot(self) -> dict:
        pct_track = (
            round(self.bytes_done / self.bytes_total * 100, 1)
            if self.bytes_total else 0.0
        )
        return {
            "job_id": self.id,
            "status": self.status,
            "content_name": self.content_name,
            "track_name": self.track_name,
            "track_index": self.track_index,
            "track_total": self.track_total,
            "track_progress_pct": pct_track,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "error": self.error,
            # true assim que dá pra chamar GET /api/download/{job_id}/file
            "file_ready": self.status == "done" and self.job_dir is not None,
            "cover_url": self.cover_url,
            "artist": self.artist,
            "content_type": self.content_type,
            "content_tracks_count": self.content_tracks_count,
            "year": self.year,
            "hires": self.hires,
            "queue_position": self.position,
            "cancellable": self.status in ("queued", "running"),
        }

    def emit(self):
        # non-blocking: se ninguém tiver conectado no WS ainda, não trava o download
        try:
            self.queue.put_nowait(self.snapshot())
        except asyncio.QueueFull:
            pass

    def set_track(self, name: str, index: int, total: int):
        self.track_name = name
        self.track_index = index
        self.track_total = total
        self.bytes_done = 0
        self.bytes_total = 0
        self.emit()


class JobManager:
    """Fila real: `enqueue()` só registra o job e acorda os workers;
    `start_workers()` sobe N tasks que processam em ordem (FIFO), uma job
    de cada vez por worker -- então com concurrency=2, até 2 downloads
    rodam ao mesmo tempo e o resto espera com `position` visível. Cancelar
    um job na fila só o remove; cancelar um em execução dá `Task.cancel()`
    de verdade nele."""

    def __init__(self, concurrency: int = 2):
        self._jobs: Dict[str, Job] = {}
        self._pending: list[str] = []
        self._cond = asyncio.Condition()
        self._concurrency = concurrency
        self._workers_started = False

    def create(self, url: str) -> Job:
        job = Job(id=uuid4().hex[:12], url=url)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        """Todos os jobs desta sessão do servidor, do mais antigo pro mais
        novo -- usado pra repopular a fila no frontend quando a página é
        recarregada (o backend nunca esquece um job por conta própria)."""
        return sorted(self._jobs.values(), key=lambda j: j.created_at)

    def _reindex_positions(self):
        for i, jid in enumerate(self._pending, start=1):
            j = self._jobs.get(jid)
            if j:
                j.position = i

    async def enqueue(self, job: Job) -> None:
        async with self._cond:
            self._pending.append(job.id)
            self._reindex_positions()
            self._cond.notify_all()
        job.emit()

    async def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status == "queued":
            async with self._cond:
                if job_id in self._pending:
                    self._pending.remove(job_id)
                    self._reindex_positions()
            job.cancel_requested = True
            job.status = "cancelled"
            job.position = None
            job.emit()
            return True
        if job.status == "running" and job.task is not None:
            job.cancel_requested = True
            job.task.cancel()
            return True
        return False

    def start_workers(self, run_fn) -> None:
        """`run_fn` é `session.run_download_job` -- passado de fora (main.py)
        pra não criar import circular entre progress.py e qobuz_service.py."""
        if self._workers_started:
            return
        self._workers_started = True
        for _ in range(self._concurrency):
            asyncio.create_task(self._worker_loop(run_fn))

    async def _worker_loop(self, run_fn) -> None:
        while True:
            async with self._cond:
                while not self._pending:
                    await self._cond.wait()
                job_id = self._pending.pop(0)
                self._reindex_positions()
            job = self._jobs.get(job_id)
            if job is None or job.cancel_requested:
                continue
            job.task = asyncio.current_task()
            try:
                await run_fn(job)
            except asyncio.CancelledError:
                job.status = "cancelled"
                job.emit()
            finally:
                job.task = None


jobs = JobManager()


class ProgressTqdm(_RealTqdm):
    """Drop-in replacement for tqdm usado dentro de downloader.py.
    Mantém o comportamento original (a barra continua funcionando se alguém
    rodar o mesmo core.py via CLI) e, adicionalmente, publica o progresso
    no Job da contextvar atual, se houver um."""

    def update(self, n=1):
        result = super().update(n)
        job = current_job.get()
        if job is not None:
            job.bytes_done = int(self.n)
            job.bytes_total = int(self.total or 0)
            job.emit()
        return result


def install():
    """Chamado uma vez no startup do FastAPI: troca a tqdm usada pelo
    downloader.py do fork pela nossa versão que também emite progresso."""
    import qobuz_dl.downloader as dl_module
    dl_module.tqdm = ProgressTqdm
