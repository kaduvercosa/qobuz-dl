import asyncio
import time
import math
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

def dump_model(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()

class ProgressItem(BaseModel):
    item_id: str
    url: str
    type: str = "track"  # track, album, playlist, artist
    title: str = "Aguardando item..."
    artist: str = "Qobuz-DL"
    album: str = "Lossless Audio"
    cover_url: str = "https://static.qobuz.com/images/covers/44/91/0060250889144_600.jpg"
    bit_depth: int = 24
    sample_rate: float = 192000
    quality_str: str = "FLAC 24-Bit / 192 kHz"
    duration_sec: float = 0.0
    
    # Progress metrics
    status: str = "queued"  # queued, fetching, downloading, processing, tagging, completed, failed, paused
    status_label: str = "NA FILA"
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed_bps: float = 0.0
    speed_str: str = "0.0 MB/s"
    eta_sec: int = 0
    eta_str: str = "--:--"
    stage: str = "INITIALIZING"
    
    # Album/Batch specific
    current_track: int = 0
    total_tracks: int = 1
    
    # Error info
    error_message: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

class SystemStats(BaseModel):
    is_active: bool = False
    active_downloads: int = 0
    total_speed_bps: float = 0.0
    total_speed_str: str = "0.0 MB/s"
    completed_today: int = 0
    failed_today: int = 0
    queue_count: int = 0
    visualizer_spectrum: List[float] = Field(default_factory=lambda: [0.0] * 32)

class LogEntry(BaseModel):
    timestamp: str
    level: str  # INFO, SUCCESS, WARN, ERROR, NOTHING
    message: str
    source: str = "ENGINE"

class ProgressManager:
    def __init__(self):
        self.active_items: Dict[str, ProgressItem] = {}
        self.completed_items: List[ProgressItem] = []
        self.failed_items: List[ProgressItem] = []
        self.subscribers: List[asyncio.Queue] = []
        self.logs: List[LogEntry] = []
        self._max_logs = 300
        self._last_speed_measurements: Dict[str, List[tuple]] = {}

    def log(self, level: str, message: str, source: str = "CORE"):
        """Add system log entry and broadcast to clients."""
        now_str = time.strftime("%H:%M:%S")
        entry = LogEntry(timestamp=now_str, level=level.upper(), message=message, source=source.upper())
        self.logs.append(entry)
        if len(self.logs) > self._max_logs:
            self.logs.pop(0)
        self.broadcast_sync({"type": "log", "data": dump_model(entry)})

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.subscribers:
            self.subscribers.remove(q)

    def broadcast_sync(self, message: Dict[str, Any]):
        for q in self.subscribers:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass

    async def broadcast(self, message: Dict[str, Any]):
        for q in list(self.subscribers):
            try:
                await q.put(message)
            except Exception:
                pass

    def create_or_update_item(self, item_id: str, **kwargs) -> ProgressItem:
        if item_id in self.active_items:
            item = self.active_items[item_id]
            for k, v in kwargs.items():
                if hasattr(item, k):
                    setattr(item, k, v)
            item.updated_at = time.time()
        else:
            item = ProgressItem(item_id=item_id, **kwargs)
            self.active_items[item_id] = item
            self._last_speed_measurements[item_id] = []
        
        self._recalculate_item(item)
        self.broadcast_sync({"type": "item_update", "data": dump_model(item)})
        return item

    def _recalculate_item(self, item: ProgressItem):
        now = time.time()
        measurements = self._last_speed_measurements.setdefault(item.item_id, [])
        measurements.append((now, item.downloaded_bytes))
        measurements = [m for m in measurements if now - m[0] <= 2.0]
        self._last_speed_measurements[item.item_id] = measurements
        
        if len(measurements) >= 2:
            dt = measurements[-1][0] - measurements[0][0]
            db = measurements[-1][1] - measurements[0][1]
            if dt > 0.1:
                item.speed_bps = max(0.0, db / dt)
        
        from qobuz_dl.utils import format_speed, format_duration
        item.speed_str = format_speed(item.speed_bps)
        
        if item.total_bytes > 0:
            item.percent = min(100.0, max(0.0, (item.downloaded_bytes / item.total_bytes) * 100.0))
            if item.speed_bps > 1024:
                remaining_bytes = max(0, item.total_bytes - item.downloaded_bytes)
                item.eta_sec = int(remaining_bytes / item.speed_bps)
                item.eta_str = format_duration(item.eta_sec)
            else:
                item.eta_str = "--:--"
        else:
            item.percent = 0.0
            item.eta_str = "--:--"

    def mark_completed(self, item_id: str):
        if item_id in self.active_items:
            item = self.active_items.pop(item_id)
            item.status = "completed"
            item.status_label = "CONCLUÍDO"
            item.percent = 100.0
            item.stage = "FINISHED"
            item.updated_at = time.time()
            self.completed_items.insert(0, item)
            self.broadcast_sync({"type": "item_completed", "data": dump_model(item)})
            self.log("SUCCESS", f"Download concluído: {item.artist} - {item.title} [{item.quality_str}]", "COMPLETER")

    def mark_failed(self, item_id: str, error: str):
        if item_id in self.active_items:
            item = self.active_items.pop(item_id)
            item.status = "failed"
            item.status_label = "FALHOU"
            item.error_message = error
            item.stage = "ERROR"
            item.updated_at = time.time()
            self.failed_items.insert(0, item)
            self.broadcast_sync({"type": "item_failed", "data": dump_model(item)})
            self.log("ERROR", f"Falha no download ({item.title}): {error}", "ENGINE")

    def get_system_stats(self) -> SystemStats:
        from qobuz_dl.utils import format_speed
        
        total_speed = sum(item.speed_bps for item in self.active_items.values() if item.status == "downloading")
        active_count = len([item for item in self.active_items.values() if item.status in ("downloading", "processing")])
        
        now = time.time()
        spectrum = []
        is_active = active_count > 0
        for i in range(32):
            if is_active:
                freq = math.sin(now * 8.0 + i * 0.4) * math.cos(now * 3.5 + i * 0.2)
                base = 0.3 + 0.6 * math.sin(i / 5.0)
                val = max(0.05, min(1.0, base + freq * 0.35))
            else:
                val = max(0.02, 0.05 * math.sin(now * 1.5 + i * 0.2))
            spectrum.append(round(val, 3))

        return SystemStats(
            is_active=is_active,
            active_downloads=active_count,
            total_speed_bps=total_speed,
            total_speed_str=format_speed(total_speed),
            completed_today=len(self.completed_items),
            failed_today=len(self.failed_items),
            queue_count=len(self.active_items),
            visualizer_spectrum=spectrum
        )

progress_manager = ProgressManager()
