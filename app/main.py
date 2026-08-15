import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import progress
from .progress import jobs
from .qobuz_service import session

app = FastAPI(title="QBDL backend")

# em produção, troque "*" pela origem real do frontend (ex.: https://qbdl.seudominio.com)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    progress.install()  # ativa a ponte de progresso tqdm -> WebSocket (ver progress.py)


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
