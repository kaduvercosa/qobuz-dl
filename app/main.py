import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import progress
from .progress import jobs
from .qobuz_service import session, cleanup_stale_job_dirs
from .utils_delivery import collect_files, build_zip, cleanup_job

app = FastAPI(title="QBDL backend")

# em produção, troque "*" pela origem real do frontend (ex.: https://qbdl.seudominio.com)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    progress.install()  # ativa a ponte de progresso tqdm -> WebSocket (ver progress.py)
    cleanup_stale_job_dirs()  # limpa pastas de jobs de uma execução anterior do server


# --------------------------------------------------------------------- auth
class LoginBody(BaseModel):
    user_auth_token: str | None = None   # preferido -- cole o token extraído do DevTools (F12) do play.qobuz.com
    email: str | None = None             # fallback, só se não quiser usar token
    password: str | None = None
    quality: int = 7          # 5=MP3 320 · 6=CD 16/44.1 · 7=Hi-Res 24/96 · 27=Hi-Res 24/192
    download_dir: str = "FLAC"


@app.post("/api/login")
async def login(body: LoginBody):
    try:
        await session.login(
            download_dir=body.download_dir, quality=body.quality,
            user_auth_token=body.user_auth_token, email=body.email, password=body.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Falha no login: {exc}") from exc
    return {"ok": True}


@app.get("/api/session")
async def get_session():
    return {"logged_in": session.logged_in}


# ------------------------------------------------------------------- busca
@app.get("/api/search")
async def search(q: str, type: str = "album", limit: int = 20):
    try:
        return {"items": await session.search_json(q, type, limit)}
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/api/album/{album_id}/tracks")
async def album_tracks(album_id: str):
    try:
        return {"tracks": await session.get_album_tracks(album_id)}
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# ---------------------------------------------------------------- download
class DownloadBody(BaseModel):
    url: str   # link de álbum, faixa, playlist ou artista do Qobuz


@app.post("/api/download")
async def start_download(body: DownloadBody):
    if not session.logged_in:
        raise HTTPException(status_code=401, detail="Faça login antes de baixar.")
    job = jobs.create(body.url)
    asyncio.create_task(session.run_download_job(job))
    return {"job_id": job.id}


@app.get("/api/download/{job_id}/file")
async def download_file(job_id: str, as_zip: bool | None = None):
    """Entrega o resultado do job pro navegador e apaga do servidor em seguida.

    - as_zip=None (padrão): 1 arquivo só -> entrega direto; 2+ arquivos -> zip.
    - as_zip=true: força zip mesmo com 1 arquivo só.
    - as_zip=false: só funciona se o job baixou exatamente 1 arquivo
      (pra playlist/álbum/artista isso normalmente não faz sentido).
    """
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job não encontrado")
    if job.status != "done":
        raise HTTPException(status_code=409, detail=f"job ainda não terminou (status={job.status})")
    if not job.job_dir:
        raise HTTPException(status_code=410, detail="arquivos já foram entregues e removidos do servidor")

    job_dir = Path(job.job_dir)
    files = collect_files(job_dir)
    if not files:
        raise HTTPException(status_code=404, detail="nenhum arquivo encontrado pra esse job")

    zip_stem = job.content_name or job_id
    want_zip = as_zip if as_zip is not None else (len(files) > 1)

    if want_zip:
        zip_path = build_zip(job_dir, zip_stem, files)
        return FileResponse(
            path=str(zip_path),
            filename=f"{zip_path.stem}.zip",
            media_type="application/zip",
            background=BackgroundTask(cleanup_job, job, zip_path),
        )

    if len(files) != 1:
        raise HTTPException(status_code=400, detail="as_zip=false só é válido quando o job tem 1 único arquivo")

    only_file = files[0]
    return FileResponse(
        path=str(only_file),
        filename=only_file.name,
        background=BackgroundTask(cleanup_job, job, None),
    )


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return job.snapshot()


@app.websocket("/ws/jobs/{job_id}")
async def job_ws(websocket: WebSocket, job_id: str):
    job = jobs.get(job_id)
    if not job:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    await websocket.send_json(job.snapshot())  # estado atual assim que conecta
    try:
        while True:
            update = await job.queue.get()
            await websocket.send_json(update)
            if update["status"] in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
