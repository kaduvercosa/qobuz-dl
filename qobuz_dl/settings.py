from dataclasses import dataclass, field
from typing import List, Optional, Any
from qobuz_dl.constants import DEFAULT_FOLDER, DEFAULT_TRACK, DEFAULT_MULTIPLE_DISC_TRACK

@dataclass
class QobuzDLSettings:
    """
    Guarda todas as preferências de configuração do Qobuz-DL.
    Graças ao @dataclass, o Python cria o método __init__ automaticamente!
    """
    # Opções Básicas
    email: str = ""
    password: str = ""
    default_folder: str = "QobuzDownloads"
    default_quality: str = "6"
    default_limit: str = "20"
    no_m3u: bool = False
    albums_only: bool = False
    no_fallback: bool = False
    no_database: bool = False
    app_id: str = ""
    secrets: List[str] = field(default_factory=list)
    folder_format: str = DEFAULT_FOLDER
    fallback_folder_format: str = DEFAULT_FOLDER
    track_format: str = DEFAULT_TRACK
    smart_discography: bool = False
    legacy_charmap: bool = False
    
    # Opções de Tags
    no_album_artist_tag: bool = False
    no_album_title_tag: bool = False
    no_track_artist_tag: bool = False
    no_track_title_tag: bool = False
    no_release_date_tag: bool = False
    no_media_type_tag: bool = False
    no_genre_tag: bool = False
    no_track_number_tag: bool = False
    no_track_total_tag: bool = False
    no_disc_number_tag: bool = False
    no_disc_total_tag: bool = False
    no_composer_tag: bool = False
    no_explicit_tag: bool = False
    no_copyright_tag: bool = False
    no_label_tag: bool = False
    no_upc_tag: bool = False
    no_isrc_tag: bool = False
    lrc_files: bool = True

    # Opções de Capa
    embed_art: bool = False
    og_cover: bool = False
    no_cover: bool = False
    embedded_art_size: str = "org"
    saved_art_size: str = "org"

    # Opções de Multidisco
    multiple_disc_prefix: str = "CD"
    multiple_disc_one_dir: bool = False
    multiple_disc_track_format: str = DEFAULT_MULTIPLE_DISC_TRACK

    # Concorrência e API
    max_workers: str = "3"
    delay: int = 0
    user_auth_token: str = ""

    # Opções de IA e Webhooks
    ai_provider: str = "openai"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Espelho Telegram (Pyrogram) ──────────────────────────────────────────
    # Lidos da seção [telegram] e [channels] do config.ini.
    # O telegram_uploader.py usa os.environ["QOBUZ_DL_CONFIG"] para encontrar
    # o config.ini correto; estes campos são apenas para inspeção/debug.
    telegram_mirror_enabled: bool  = False
    telegram_api_id:         str   = ""
    telegram_api_hash:       str   = ""
    telegram_session:        str   = "qobuz_session"
    telegram_ch_musicas:     str   = ""
    telegram_ch_albuns:      str   = ""
    telegram_ch_artistas:    str   = ""
    telegram_ch_geral:       str   = ""

    @classmethod
    def from_arguments_configparser(cls, arguments: Any, config: Any) -> 'QobuzDLSettings':
        """
        Cria o objeto de configuração lendo primeiro dos argumentos do terminal
        e, se não existirem, recorre ao ficheiro config.ini.
        """
        section = "qobuz" if config.has_section("qobuz") else "DEFAULT"
        
        # O dicionário kwargs agrupa todos os valores. 
        # O desempacotamento (**kwargs) vai alimentar o Dataclass automaticamente.
        kwargs = {
            # Opções Básicas
            'email': config.get(section, "email", fallback=""),
            'password': config.get(section, "password", fallback=""),
            'default_folder': getattr(arguments, 'directory', None) or config.get(section, "default_folder", fallback="QobuzDownloads"),
            'default_quality': getattr(arguments, 'quality', None) or config.get(section, "default_quality", fallback="6"),
            'default_limit': config.get(section, "default_limit", fallback="20"),
            'no_m3u': getattr(arguments, 'no_m3u', False) or config.getboolean(section, "no_m3u", fallback=False),
            'albums_only': getattr(arguments, 'albums_only', False) or config.getboolean(section, "albums_only", fallback=False),
            'no_fallback': getattr(arguments, 'no_fallback', False) or config.getboolean(section, "no_fallback", fallback=False),
            'no_database': getattr(arguments, 'no_db', False) or config.getboolean(section, "no_database", fallback=False),
            'app_id': config.get(section, "app_id", fallback=""),
            'secrets': [s.strip() for s in config.get(section, "secrets", fallback="").split(",") if s.strip()],
            'folder_format': getattr(arguments, 'folder_format', None) or config.get(section, "folder_format", fallback=DEFAULT_FOLDER),
            'fallback_folder_format': getattr(arguments, 'fallback_folder_format', None) or config.get(section, "fallback_folder_format", fallback=DEFAULT_FOLDER),
            'track_format': getattr(arguments, 'track_format', None) or config.get(section, "track_format", fallback=DEFAULT_TRACK),
            'smart_discography': getattr(arguments, 'smart_discography', False) or config.getboolean(section, "smart_discography", fallback=False),
            'legacy_charmap': getattr(arguments, 'legacy_charmap', False) or config.getboolean(section, "legacy_charmap", fallback=False),
            
            # Opções de Capa
            'embed_art': getattr(arguments, 'embed_art', False) or config.getboolean(section, "embed_art", fallback=True),
            'og_cover': getattr(arguments, 'og_cover', False) or config.getboolean(section, "og_cover", fallback=True),
            'no_cover': getattr(arguments, 'no_cover', False) or config.getboolean(section, "no_cover", fallback=False),
            'embedded_art_size': getattr(arguments, 'embedded_art_size', None) or config.get(section, "embedded_art_size", fallback="org"),
            'saved_art_size': getattr(arguments, 'saved_art_size', None) or config.get(section, "saved_art_size", fallback="org"),
            
            # Opções Multidisco
            'multiple_disc_prefix': getattr(arguments, 'multiple_disc_prefix', None) or config.get(section, "multiple_disc_prefix", fallback="CD"),
            'multiple_disc_one_dir': getattr(arguments, 'multiple_disc_one_dir', False) or config.getboolean(section, "multiple_disc_one_dir", fallback=False),
            'multiple_disc_track_format': getattr(arguments, 'multiple_disc_track_format', None) or config.get(section, "multiple_disc_track_format", fallback="{disc_number}.{track_number} - {track_title}"),
                                 
            # Opções de Tags
            'no_album_artist_tag': getattr(arguments, 'no_album_artist_tag', False) or config.getboolean(section, "no_album_artist_tag", fallback=False),
            'no_album_title_tag': getattr(arguments, 'no_album_title_tag', False) or config.getboolean(section, "no_album_title_tag", fallback=False),
            'no_track_artist_tag': getattr(arguments, 'no_track_artist_tag', False) or config.getboolean(section, "no_track_artist_tag", fallback=False),
            'no_track_title_tag': getattr(arguments, 'no_track_title_tag', False) or config.getboolean(section, "no_track_title_tag", fallback=False),
            'no_release_date_tag': getattr(arguments, 'no_release_date_tag', False) or config.getboolean(section, "no_release_date_tag", fallback=False),
            'no_media_type_tag': getattr(arguments, 'no_media_type_tag', False) or config.getboolean(section, "no_media_type_tag", fallback=False),
            'no_genre_tag': getattr(arguments, 'no_genre_tag', False) or config.getboolean(section, "no_genre_tag", fallback=False),
            'no_track_number_tag': getattr(arguments, 'no_track_number_tag', False) or config.getboolean(section, "no_track_number_tag", fallback=False),
            'no_track_total_tag': getattr(arguments, 'no_track_total_tag', False) or config.getboolean(section, "no_track_total_tag", fallback=False),
            'no_disc_number_tag': getattr(arguments, 'no_disc_number_tag', False) or config.getboolean(section, "no_disc_number_tag", fallback=False),
            'no_disc_total_tag': getattr(arguments, 'no_disc_total_tag', False) or config.getboolean(section, "no_disc_total_tag", fallback=False),
            'no_composer_tag': getattr(arguments, 'no_composer_tag', False) or config.getboolean(section, "no_composer_tag", fallback=False),
            'no_explicit_tag': getattr(arguments, 'no_explicit_tag', False) or config.getboolean(section, "no_explicit_tag", fallback=False),
            'no_copyright_tag': getattr(arguments, 'no_copyright_tag', False) or config.getboolean(section, "no_copyright_tag", fallback=False),
            'no_label_tag': getattr(arguments, 'no_label_tag', False) or config.getboolean(section, "no_label_tag", fallback=False),
            'no_upc_tag': getattr(arguments, 'no_upc_tag', False) or config.getboolean(section, "no_upc_tag", fallback=False),
            'no_isrc_tag': getattr(arguments, 'no_isrc_tag', False) or config.getboolean(section, "no_isrc_tag", fallback=False),
            'lrc_files': getattr(arguments, 'lrc_files', config.getboolean(section, "lrc_files", fallback=True)),
            
            # Concorrência e APIs Extras
            'max_workers': getattr(arguments, 'max_workers', None) or config.get(section, "max_workers", fallback="3"),
            'delay': getattr(arguments, 'delay', 0) or config.getint(section, "delay", fallback=0),
            'user_auth_token': config.get(section, "user_auth_token", fallback=""),
            'ai_provider': getattr(arguments, 'ai_provider', config.get(section, "ai_provider", fallback="openai")),
            'openai_api_key': getattr(arguments, 'openai_api_key', config.get(section, "openai_api_key", fallback="")),
            'gemini_api_key': getattr(arguments, 'gemini_api_key', config.get(section, "gemini_api_key", fallback="")),
            'webhook_url': getattr(arguments, 'webhook_url', config.get(section, "webhook_url", fallback="")),
            'telegram_bot_token': getattr(arguments, 'telegram_bot_token', config.get(section, "telegram_bot_token", fallback="")),
            'telegram_chat_id': getattr(arguments, 'telegram_chat_id', config.get(section, "telegram_chat_id", fallback="")),

            # ── Espelho Telegram (Pyrogram) ──────────────────────────────────
            'telegram_mirror_enabled': config.getboolean("telegram", "enabled",  fallback=False),
            'telegram_api_id':         config.get("telegram",  "api_id",   fallback=""),
            'telegram_api_hash':        config.get("telegram",  "api_hash",  fallback=""),
            'telegram_session':         config.get("telegram",  "session",   fallback="qobuz_session"),
            'telegram_ch_musicas':      config.get("channels",  "musicas",   fallback=""),
            'telegram_ch_albuns':       config.get("channels",  "albuns",    fallback=""),
            'telegram_ch_artistas':     config.get("channels",  "artistas",  fallback=""),
            'telegram_ch_geral':        config.get("channels",  "geral",     fallback=""),
        }
        
        # Desempacota o dicionário para dentro da Dataclass
        return cls(**kwargs)