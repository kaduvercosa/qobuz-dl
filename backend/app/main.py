import os
import json
import asyncio
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Body, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config_manager import config_manager, AppSettings, dump_model
from app.progress import progress_manager
from app.queue_manager import queue_manager
from app.qobuz_service import qobuz_service
from qobuz_dl.constants import COUNTRY_NAMES, FORMAT_IDS

app = FastAPI(
    title="Qobuz-DL Web Client",
    description="Full-Featured High-Res Lossless Audio Downloader & Organizer for Qobuz",
    version="3.0.0-ultimate"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.on_event("startup")
async def startup_event():
    progress_manager.log("SYSTEM", "Qobuz-DL Web Client Inicializado", "BOOT")
    queue_manager.ensure_workers()
    if config_manager.config.auth.auto_login:
        asyncio.create_task(qobuz_service.authenticate())

# Models
class LoginRequest(BaseModel):
    email: Optional[str] = ""
    password: Optional[str] = ""
    token: Optional[str] = ""
    app_id: Optional[str] = ""

class AddToQueueRequest(BaseModel):
    urls: List[str]
    quality_override: Optional[int] = None

class PreviewPathRequest(BaseModel):
    artist: Optional[str] = "Daft Punk"
    album: Optional[str] = "Discovery"
    year: Optional[str] = "2001"
    quality: Optional[str] = "24B-96kHz"
    track_number: Optional[int] = 1
    title: Optional[str] = "One More Time"

# HTML Root
@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Qobuz-DL Web: index.html not found</h1>"

# Catalog & Discovery Endpoints
@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1), limit: int = 15):
    res = await qobuz_service.search(query=q, limit=limit)
    return res

@app.get("/api/get-releases")
async def api_get_releases(limit: int = 24):
    res = await qobuz_service.get_releases(limit=limit)
    return res

@app.get("/api/get-album")
async def api_get_album(id: str = Query(...)):
    res = await qobuz_service.get_album(album_id=id)
    return res

@app.get("/api/get-artist")
async def api_get_artist(id: str = Query(...)):
    res = await qobuz_service.get_artist(artist_id=id)
    return res

@app.get("/api/get-countries")
async def api_get_countries():
    return [{"code": code, "name": name} for code, name in COUNTRY_NAMES.items()]

# Auth Endpoints
@app.get("/api/auth/me")
async def get_auth_me():
    return {
        "authenticated": qobuz_service.session_valid,
        "tier": qobuz_service.user_tier,
        "user_data": qobuz_service.user_data,
        "email": config_manager.config.auth.email or "Nenhuma conta conectada",
        "app_id": config_manager.config.auth.app_id
    }

@app.post("/api/auth/login")
async def api_login(req: LoginRequest):
    return await qobuz_service.authenticate(email=req.email, password=req.password, token=req.token, app_id=req.app_id)

@app.post("/api/auth/logout")
async def api_logout():
    return await qobuz_service.logout()

@app.post("/api/auth/fetch-tokens")
async def api_fetch_tokens():
    return await qobuz_service.fetch_dynamic_tokens()

# Queue & Downloads
@app.get("/api/queue")
async def get_queue():
    return {
        "active": [dump_model(item) for item in progress_manager.active_items.values()],
        "completed": [dump_model(item) for item in progress_manager.completed_items],
        "failed": [dump_model(item) for item in progress_manager.failed_items],
        "is_paused": queue_manager.is_paused
    }

@app.post("/api/queue/add")
async def add_queue(req: AddToQueueRequest):
    if not req.urls:
        raise HTTPException(status_code=400, detail="Nenhuma URL fornecida")
    added = queue_manager.add_to_queue(req.urls, req.quality_override)
    return {"success": True, "added": added}

@app.post("/api/queue/pause")
async def pause_queue():
    queue_manager.pause_queue()
    return {"success": True, "is_paused": True}

@app.post("/api/queue/resume")
async def resume_queue():
    queue_manager.resume_queue()
    return {"success": True, "is_paused": False}

@app.post("/api/queue/clear")
async def clear_queue():
    queue_manager.clear_completed()
    return {"success": True}

@app.post("/api/queue/cancel/{task_id}")
async def cancel_task(task_id: str):
    success = queue_manager.cancel_task(task_id)
    return {"success": success}

# Config & Settings
@app.get("/api/config")
async def get_config():
    return dump_model(config_manager.config)

@app.post("/api/config")
async def update_config(data: Dict[str, Any] = Body(...)):
    updated = config_manager.update_dict(data)
    progress_manager.log("SUCCESS", "Configurações atualizadas.", "CONFIG")
    return {"success": True, "config": dump_model(updated)}

@app.post("/api/config/preview-path")
async def preview_path(req: PreviewPathRequest):
    return config_manager.preview_path(
        artist=req.artist or "Daft Punk",
        album=req.album or "Discovery",
        year=req.year or "2001",
        quality=req.quality or "24B-96kHz",
        track_num=req.track_number or 1,
        title=req.title or "One More Time"
    )

@app.post("/api/config/reset")
async def reset_config():
    defaults = config_manager.reset_to_defaults()
    return {"success": True, "config": dump_model(defaults)}

@app.get("/api/history")
async def get_history():
    return qobuz_service.db.get_download_history(limit=100)

@app.get("/api/status")
async def get_status():
    stats = progress_manager.get_system_stats()
    return {
        "status": "online",
        "version": "3.0.0-ultimate",
        "auth": {
            "authenticated": qobuz_service.session_valid,
            "tier": qobuz_service.user_tier,
            "email": config_manager.config.auth.email or "Nenhuma conta vinculada"
        },
        "stats": dump_model(stats),
        "active_items": [dump_model(item) for item in progress_manager.active_items.values()],
        "queue_is_paused": queue_manager.is_paused
    }

# WebSockets
@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    q = progress_manager.subscribe()
    stats = progress_manager.get_system_stats()
    init_msg = {
        "type": "init",
        "data": {
            "auth": {
                "authenticated": qobuz_service.session_valid,
                "tier": qobuz_service.user_tier,
                "email": config_manager.config.auth.email or "Nenhuma conta vinculada"
            },
            "stats": dump_model(stats),
            "active_items": [dump_model(item) for item in progress_manager.active_items.values()],
            "logs": [dump_model(log) for log in progress_manager.logs[-30:]]
        }
    }
    await websocket.send_text(json.dumps(init_msg))

    async def periodic_pulse():
        try:
            while True:
                await asyncio.sleep(0.1)
                sys_stats = progress_manager.get_system_stats()
                msg = {
                    "type": "tick",
                    "data": {
                        "stats": dump_model(sys_stats),
                        "active_items": [dump_model(item) for item in progress_manager.active_items.values()]
                    }
                }
                await websocket.send_text(json.dumps(msg))
        except Exception:
            pass

    pulse_task = asyncio.create_task(periodic_pulse())
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=0.1)
                await websocket.send_text(json.dumps(event))
            except asyncio.TimeoutError:
                pass
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                cmd = json.loads(data)
                if cmd.get("action") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except (asyncio.TimeoutError, json.JSONDecodeError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        pulse_task.cancel()
        progress_manager.unsubscribe(q)
