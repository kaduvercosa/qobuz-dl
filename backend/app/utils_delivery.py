import urllib.request
import urllib.parse
import json
import asyncio
from app.config_manager import config_manager
from app.progress import progress_manager

async def send_telegram_notification(message: str) -> bool:
    """Send formatted telegram notification when enabled."""
    cfg = config_manager.config.integrations
    if not cfg.telegram_enabled or not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        return False
        
    try:
        url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": cfg.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        
        loop = asyncio.get_event_loop()
        def _send():
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        
        success = await loop.run_in_executor(None, _send)
        if success:
            progress_manager.log("SUCCESS", "Notificação enviada ao Telegram com sucesso.", "TELEGRAM")
        return success
    except Exception as e:
        progress_manager.log("WARN", f"Falha ao enviar Telegram: {e}", "TELEGRAM")
        return False

async def send_discord_webhook(title: str, description: str, fields: list = None) -> bool:
    """Send Discord embed webhook notification."""
    cfg = config_manager.config.integrations
    if not cfg.discord_webhook_url:
        return False
        
    try:
        embed = {
            "title": f"🎧 {title}",
            "description": description,
            "color": 0xD71921,  # Nothing Red
            "footer": {"text": "Qobuz-DL Nothing OS Edition • Hi-Res FLAC"}
        }
        if fields:
            embed["fields"] = fields
            
        payload = {"embeds": [embed]}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(cfg.discord_webhook_url, data=data, headers={"Content-Type": "application/json"})
        
        loop = asyncio.get_event_loop()
        def _send():
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status in (200, 204)
                
        return await loop.run_in_executor(None, _send)
    except Exception as e:
        progress_manager.log("WARN", f"Falha ao enviar Discord Webhook: {e}", "WEBHOOK")
        return False
