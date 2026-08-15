import asyncio
from typing import Dict, Any, List, Optional
from core.qobuz_provider import QobuzProvider

class Maestro:
    """Download orchestrator managing queues, concurrency, and tagging."""
    def __init__(self):
        self.provider = QobuzProvider()
        self.is_active = False

    def get_provider(self) -> QobuzProvider:
        return self.provider

maestro = Maestro()
