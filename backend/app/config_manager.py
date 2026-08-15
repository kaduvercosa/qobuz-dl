import json
import os
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

def dump_model(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()

def dump_model_json(model: BaseModel, indent: int = 2) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json(indent=indent)
    return model.json(indent=indent)

class AuthConfig(BaseModel):
    email: str = ""
    password: str = ""
    user_id: str = ""
    user_auth_token: str = ""
    app_id: str = "712108709"
    app_secret: str = ""
    auto_login: bool = True

class QualityConfig(BaseModel):
    format_id: int = 27  # 27 = 24/192 FLAC, 7 = 24/96 FLAC, 6 = 16/44.1 FLAC, 5 = MP3 320
    fallback_quality: bool = True
    max_sample_rate: int = 192000
    max_bit_depth: int = 24
    embed_art: bool = True
    art_resolution: str = "max"  # 600, 1200, 1400, max
    save_cover_file: bool = True
    cover_filename: str = "cover.jpg"
    embed_lyrics: bool = True
    save_lrc_file: bool = True
    calculate_replaygain: bool = False

class PathsConfig(BaseModel):
    download_dir: str = "./downloads"
    folder_format: str = "{artist}/{year} - {album} [{quality}]"
    track_format: str = "{track_number:02d} - {title}"
    multi_disc_folder: bool = True
    sanitize_fat32: bool = True
    overwrite_policy: str = "skip"  # skip, overwrite, rename

class EngineConfig(BaseModel):
    max_workers: int = 4
    chunk_size_kb: int = 1024
    max_retries: int = 3
    retry_delay_sec: int = 2
    bandwidth_limit_mbps: int = 0
    keep_cache: bool = False

class IntegrationsConfig(BaseModel):
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_caption_format: str = "🎧 <b>{title}</b> - {artist}\n💽 {album} ({year})\n✨ <i>{quality}</i>"
    discord_webhook_url: str = ""
    lastfm_api_key: str = ""
    lastfm_username: str = ""
    desktop_notifications: bool = True
    sound_alerts: bool = True

class UIConfig(BaseModel):
    theme: str = "nothing_dark"
    glyph_effects: bool = True
    dot_matrix_font: bool = True
    live_visualizer: bool = True
    visualizer_mode: str = "dot_matrix"  # dot_matrix, spectrum, waveform
    red_accent: str = "#D71921"
    refresh_rate_ms: int = 100

class AppSettings(BaseModel):
    auth: AuthConfig = Field(default_factory=AuthConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

class ConfigManager:
    def __init__(self, config_path: str = "./config.json"):
        self.config_path = os.path.abspath(config_path)
        self.config = self.load_config()

    def load_config(self) -> AppSettings:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return AppSettings(**data)
            except Exception as e:
                print(f"[CONFIG] Error loading config from {self.config_path}: {e}. Using defaults.")
        
        default_cfg = AppSettings()
        self.save_config(default_cfg)
        return default_cfg

    def save_config(self, new_config: Optional[AppSettings] = None) -> bool:
        if new_config:
            self.config = new_config
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(dump_model_json(self.config, indent=2))
            return True
        except Exception as e:
            print(f"[CONFIG] Failed to save config: {e}")
            return False

    def update_dict(self, data: Dict[str, Any]) -> AppSettings:
        current_data = dump_model(self.config)
        for section, values in data.items():
            if section in current_data and isinstance(values, dict):
                current_data[section].update(values)
            else:
                current_data[section] = values
        self.config = AppSettings(**current_data)
        self.save_config()
        return self.config

    def reset_to_defaults(self) -> AppSettings:
        self.config = AppSettings()
        self.save_config()
        return self.config

    def preview_path(self, artist: str = "The Weeknd", album: str = "After Hours", 
                     year: str = "2020", quality: str = "24B-192kHz", 
                     track_num: int = 1, title: str = "Blinding Lights") -> Dict[str, str]:
        """Generates dynamic preview of folder and file path based on current format templates."""
        from qobuz_dl.utils import sanitize_filename
        
        try:
            folder_vars = {
                "artist": sanitize_filename(artist),
                "album": sanitize_filename(album),
                "year": year,
                "quality": quality,
                "bit_depth": "24",
                "sample_rate": "192"
            }
            track_vars = {
                "track_number": track_num,
                "title": sanitize_filename(title),
                "artist": sanitize_filename(artist),
                "album": sanitize_filename(album),
                "year": year,
                "quality": quality
            }
            
            folder_rel = self.config.paths.folder_format.format(**folder_vars)
            track_file = self.config.paths.track_format.format(**track_vars) + ".flac"
            full_path = os.path.join(self.config.paths.download_dir, folder_rel, track_file)
            
            return {
                "folder_preview": folder_rel,
                "file_preview": track_file,
                "full_path_preview": full_path
            }
        except Exception as e:
            return {
                "folder_preview": f"Error in template: {e}",
                "file_preview": f"Error in template: {e}",
                "full_path_preview": f"Error: {e}"
            }

config_manager = ConfigManager()
