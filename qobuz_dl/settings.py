from qobuz_dl.constants import DEFAULT_FOLDER, DEFAULT_TRACK, DEFAULT_MULTIPLE_DISC_TRACK

class QobuzDLSettings:
    def __init__(self, **kwargs):
        # basic options
        self.email = kwargs.get('email')
        self.password = kwargs.get('password')
        self.default_folder = kwargs.get('default_folder', 'QobuzDownloads')
        self.default_quality = kwargs.get('default_quality', 6)
        self.default_limit = kwargs.get('default_limit', 20)
        self.no_m3u = kwargs.get('no_m3u', False)
        self.albums_only = kwargs.get('albums_only', False)
        self.no_fallback = kwargs.get('no_fallback', False)
        self.no_database = kwargs.get('no_database', False)
        self.app_id = kwargs.get('app_id')
        self.secrets = kwargs.get('secrets')
        self.folder_format = kwargs.get('folder_format')
        self.fallback_folder_format = kwargs.get('fallback_folder_format', DEFAULT_FOLDER)
        self.track_format = kwargs.get('track_format')
        self.smart_discography = kwargs.get('smart_discography', False)
        self.legacy_charmap = kwargs.get('legacy_charmap', False)
        
        # tag options
        self.no_album_artist_tag = kwargs.get('no_album_artist_tag', False)
        self.no_album_title_tag = kwargs.get('no_album_title_tag', False)
        self.no_track_artist_tag = kwargs.get('no_track_artist_tag', False)
        self.no_track_title_tag = kwargs.get('no_track_title_tag', False)
        self.no_release_date_tag = kwargs.get('no_release_date_tag', False)
        self.no_media_type_tag = kwargs.get('no_media_type_tag', False)
        self.no_genre_tag = kwargs.get('no_genre_tag', False)
        self.no_track_number_tag = kwargs.get('no_track_number_tag', False)
        self.no_track_total_tag = kwargs.get('no_track_total_tag', False)
        self.no_disc_number_tag = kwargs.get('no_disc_number_tag', False)
        self.no_disc_total_tag = kwargs.get('no_disc_total_tag', False)
        self.no_composer_tag = kwargs.get('no_composer_tag', False)
        self.no_explicit_tag = kwargs.get('no_explicit_tag', False)
        self.no_copyright_tag = kwargs.get('no_copyright_tag', False)
        self.no_label_tag = kwargs.get('no_label_tag', False)
        self.no_upc_tag = kwargs.get('no_upc_tag', False)
        self.no_isrc_tag = kwargs.get('no_isrc_tag', False)
        self.lrc_files = kwargs.get('lrc_files', True)

        # cover options
        self.embed_art = kwargs.get('embed_art', False)
        self.cover_og_quality = kwargs.get('og_cover', False)
        self.no_cover = kwargs.get('no_cover', False)
        self.embedded_art_size = kwargs.get('embedded_art_size', '600')
        self.saved_art_size = kwargs.get('saved_art_size', 'org')

        # multiple disc option
        self.multiple_disc_prefix = kwargs.get('multiple_disc_prefix', 'CD')
        self.multiple_disc_one_dir = kwargs.get('multiple_disc_one_dir', False)
        self.multiple_disc_track_format = kwargs.get(
            'multiple_disc_track_format', 
            DEFAULT_MULTIPLE_DISC_TRACK
        )

        # Add parallel download thread count option
        self.max_workers = int(kwargs.get('max_workers', 3))

        # user_auth_token
        self.user_auth_token = kwargs.get('user_auth_token', '')

        # AI options for smart playlists
        self.ai_provider = kwargs.get('ai_provider', 'openai')
        self.openai_api_key = kwargs.get('openai_api_key', '')
        self.gemini_api_key = kwargs.get('gemini_api_key', '')

        # Webhook / Daemon
        self.webhook_url = kwargs.get('webhook_url', '')

        # Telegram Bot
        self.telegram_bot_token = kwargs.get('telegram_bot_token', '')
        self.telegram_chat_id = kwargs.get('telegram_chat_id', '')

    @staticmethod
    def from_arguments_configparser(arguments, config):
        """Creating Configuration Objects from Command Line Parameters and Configuration Files
        
        Args:
            arguments: Parsed command line arguments
            config: ConfigParser object
            
        Returns:
            QobuzDLSettings: Configuration object
        """
        # Determine the correct section to read from config.ini
        section = "qobuz" if config.has_section("qobuz") else "DEFAULT"
        
        # basic options
        kwargs = {
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
            'secrets': [s for s in config.get(section, "secrets", fallback="").split(",") if s],
            'folder_format': getattr(arguments, 'folder_format', None) or config.get(section, "folder_format", fallback=DEFAULT_FOLDER),
            'fallback_folder_format': getattr(arguments, 'fallback_folder_format', None) or config.get(section, "fallback_folder_format", fallback=DEFAULT_FOLDER),
            'track_format': getattr(arguments, 'track_format', None) or config.get(section, "track_format", fallback=DEFAULT_TRACK),
            'smart_discography': getattr(arguments, 'smart_discography', False) or config.getboolean(section, "smart_discography", fallback=False),
            
            # cover options
            'embed_art': getattr(arguments, 'embed_art', False) or config.getboolean(section, "embed_art", fallback=True),
            'og_cover': getattr(arguments, 'og_cover', False) or config.getboolean(section, "og_cover", fallback=False),
            'no_cover': getattr(arguments, 'no_cover', False) or config.getboolean(section, "no_cover", fallback=False),
            'embedded_art_size': getattr(arguments, 'embedded_art_size', None) or config.get(section, "embedded_art_size", fallback="600"),
            'saved_art_size': getattr(arguments, 'saved_art_size', None) or config.get(section, "saved_art_size", fallback="org"),
            
            # multiple disc option
            'multiple_disc_prefix': getattr(arguments, 'multiple_disc_prefix', None) or config.get(section, "multiple_disc_prefix", fallback="CD"),
            'multiple_disc_one_dir': getattr(arguments, 'multiple_disc_one_dir', False) or config.getboolean(section, "multiple_disc_one_dir", fallback=False),
            'multiple_disc_track_format': getattr(arguments, 'multiple_disc_track_format', None) or config.get(section, "multiple_disc_track_format", fallback="{disc_number}.{track_number} - {track_title}"),
                                 
            # tag options
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
            
            # Add parallel download thread count configuration
            'max_workers': getattr(arguments, 'max_workers', None) or config.get(section, "max_workers", fallback="3"),

            # user_auth_token
            'user_auth_token': config.get(section, "user_auth_token", fallback=""),
        
            'lrc_files': getattr(arguments, 'lrc_files', config.getboolean(section, "lrc_files", fallback=True)),

            # AI options
            'ai_provider': getattr(arguments, 'ai_provider', config.get(section, "ai_provider", fallback="openai")),
            'openai_api_key': getattr(arguments, 'openai_api_key', config.get(section, "openai_api_key", fallback="")),
            'gemini_api_key': getattr(arguments, 'gemini_api_key', config.get(section, "gemini_api_key", fallback="")),

            # Webhook
            'webhook_url': getattr(arguments, 'webhook_url', config.get(section, "webhook_url", fallback="")),

            # Telegram
            'telegram_bot_token': getattr(arguments, 'telegram_bot_token', config.get(section, "telegram_bot_token", fallback="")),
            'telegram_chat_id': getattr(arguments, 'telegram_chat_id', config.get(section, "telegram_chat_id", fallback="")),
        }
        
        return QobuzDLSettings(**kwargs)