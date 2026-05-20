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
        self.embedded_art_size = kwargs.get('embedded_art_size', 'org')
        self.saved_art_size = kwargs.get('saved_art_size', 'org')

        # multiple disc option
        self.multiple_disc_prefix = kwargs.get('multiple_disc_prefix', 'CD')
        self.multiple_disc_one_dir = kwargs.get('multiple_disc_one_dir', False)
        self.multiple_disc_track_format = kwargs.get(
            'multiple_disc_track_format', 
            DEFAULT_MULTIPLE_DISC_TRACK
        )

        # Parallel download options (sempre convertidos para int)
        self.max_workers = int(kwargs.get('max_workers', 3))
        self.delay = int(kwargs.get('delay', 0))

        # user_auth_token
        self.user_auth_token = kwargs.get('user_auth_token', '')

        # AI / notification options
        self.ai_provider = kwargs.get('ai_provider', 'openai')
        self.openai_api_key = kwargs.get('openai_api_key', '')
        self.gemini_api_key = kwargs.get('gemini_api_key', '')
        self.webhook_url = kwargs.get('webhook_url', '')

    @staticmethod
    def from_arguments_configparser(arguments, config):
        #"""
        #Cria QobuzDLSettings a partir de argumentos da CLI + config.ini.
        #Prioriza explicitamente valores passados na linha de comando.
        #Corrige o bug anterior com 'or' que ignorava valores falsy (0, False, "").
        #"""
        section = "qobuz" if config.has_section("qobuz") else "DEFAULT"

        def _get(key, fallback, is_bool=False, is_int=False):
            #"""
            #Retorna valor da CLI se foi explicitamente passado (não None).
            #Caso contrário, usa o valor do config.ini.
            #"""
            cli_val = getattr(arguments, key, None)
            if cli_val is not None:
                if is_bool:
                    return bool(cli_val)
                if is_int:
                    try:
                        return int(cli_val)
                    except (ValueError, TypeError):
                        pass
                return cli_val
            # Fallback para config
            if is_bool:
                return config.getboolean(section, key, fallback=fallback)
            if is_int:
                return config.getint(section, key, fallback=fallback)
            return config.get(section, key, fallback=fallback)

        kwargs = {
            # Básicos
            'email': config.get(section, "email", fallback=""),
            'password': config.get(section, "password", fallback=""),
            'default_folder': _get('directory', "QobuzDownloads"),
            'default_quality': _get('quality', 6, is_int=True),
            'default_limit': _get('limit', 20, is_int=True),
            'no_m3u': _get('no_m3u', False, is_bool=True),
            'albums_only': _get('albums_only', False, is_bool=True),
            'no_fallback': _get('no_fallback', False, is_bool=True),
            'no_database': _get('no_db', False, is_bool=True),
            'app_id': config.get(section, "app_id", fallback=""),
            'secrets': [s for s in config.get(section, "secrets", fallback="").split(",") if s],
            'folder_format': _get('folder_format', DEFAULT_FOLDER),
            'fallback_folder_format': _get('fallback_folder_format', DEFAULT_FOLDER),
            'track_format': _get('track_format', DEFAULT_TRACK),
            'smart_discography': _get('smart_discography', False, is_bool=True),

            # Capas
            'embed_art': _get('embed_art', True, is_bool=True),
            'og_cover': _get('og_cover', False, is_bool=True),
            'no_cover': _get('no_cover', False, is_bool=True),
            'embedded_art_size': _get('embedded_art_size', "org"),
            'saved_art_size': _get('saved_art_size', "org"),

            # Múltiplos discos
            'multiple_disc_prefix': _get('multiple_disc_prefix', "CD"),
            'multiple_disc_one_dir': _get('multiple_disc_one_dir', False, is_bool=True),
            'multiple_disc_track_format': _get('multiple_disc_track_format', DEFAULT_MULTIPLE_DISC_TRACK),

            # Opções de tags (booleanos)
            'no_album_artist_tag': _get('no_album_artist_tag', False, is_bool=True),
            'no_album_title_tag': _get('no_album_title_tag', False, is_bool=True),
            'no_track_artist_tag': _get('no_track_artist_tag', False, is_bool=True),
            'no_track_title_tag': _get('no_track_title_tag', False, is_bool=True),
            'no_release_date_tag': _get('no_release_date_tag', False, is_bool=True),
            'no_media_type_tag': _get('no_media_type_tag', False, is_bool=True),
            'no_genre_tag': _get('no_genre_tag', False, is_bool=True),
            'no_track_number_tag': _get('no_track_number_tag', False, is_bool=True),
            'no_track_total_tag': _get('no_track_total_tag', False, is_bool=True),
            'no_disc_number_tag': _get('no_disc_number_tag', False, is_bool=True),
            'no_disc_total_tag': _get('no_disc_total_tag', False, is_bool=True),
            'no_composer_tag': _get('no_composer_tag', False, is_bool=True),
            'no_explicit_tag': _get('no_explicit_tag', False, is_bool=True),
            'no_copyright_tag': _get('no_copyright_tag', False, is_bool=True),
            'no_label_tag': _get('no_label_tag', False, is_bool=True),
            'no_upc_tag': _get('no_upc_tag', False, is_bool=True),
            'no_isrc_tag': _get('no_isrc_tag', False, is_bool=True),

            # Paralelismo (os mais críticos!)
            'max_workers': _get('max_workers', 3, is_int=True),
            'delay': _get('delay', 0, is_int=True),

            # Auth
            'user_auth_token': config.get(section, "user_auth_token", fallback=""),
            'lrc_files': _get('lrc_files', True, is_bool=True),

            # AI / Notificações
            'ai_provider': _get('ai_provider', "openai"),
            'openai_api_key': _get('openai_api_key', ""),
            'gemini_api_key': _get('gemini_api_key', ""),
            'webhook_url': _get('webhook_url', ""),
            'telegram_bot_token': _get('telegram_bot_token', ""),
            'telegram_chat_id': _get('telegram_chat_id', ""),
        }

        return QobuzDLSettings(**kwargs)