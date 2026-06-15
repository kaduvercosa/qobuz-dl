import base64
import hashlib
import logging
import time
import unicodedata
import asyncio
import difflib

from typing import Any, Tuple, Dict, Optional, List, AsyncGenerator
import aiohttp

try:
    from Cryptodome.Protocol.KDF import HKDF
    from Cryptodome.Hash import SHA256
    from Cryptodome.Cipher import AES
    from Cryptodome.Util.Padding import unpad
except ImportError:
    from Crypto.Protocol.KDF import HKDF
    from Crypto.Hash import SHA256
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad

from qobuz_dl.exceptions import (
    AuthenticationError,
    InvalidAppIdError,
    InvalidAppSecretError,
    InvalidQuality,
)
from qobuz_dl.color import GREEN, YELLOW, RED, OFF, CYAN, RESET

try:
    from qobuz_dl.bundle import Bundle
except ImportError:
    Bundle = None

logger = logging.getLogger(__name__)


class Client:
    """
    Cliente assíncrono para a API do Qobuz.
    Lida com autenticação, pesquisa, metadados e obtenção de URLs de streaming/download.
    """
    def __init__(self, email: str, pwd: str, app_id: str, secrets: list, user_auth_token: str = None, force_english: bool = True):
        logger.info(f"{YELLOW}LOGANDO...{OFF}")
        self.secrets = secrets
        self.id = str(app_id)
        self.force_english = force_english
        
        if Bundle:
            try:
                b = Bundle()
                fresh_id = str(b.get_app_id())
                if fresh_id:
                    self.id = fresh_id
                    self.secrets = list(b.get_secrets().values())
                    logger.info(f"{GREEN}[+] App ID atualizado: {self.id}{OFF}")
            except Exception as e:
                logger.warning(f"Não foi possível atualizar app_id/secrets dinamicamente: {e}")

        self.headers = self._build_initial_headers()
        
        self.session = None
        self.base = "https://www.qobuz.com/api.json/0.2/"
        self.sec = None
        self.session_id = None
        self.session_infos = None
        self.session_key = None
        self.uat = None
        
        # Trava de segurança para geração de sessão em paralelo
        self._session_lock = asyncio.Lock()
        
        self._initial_email = email
        self._initial_pwd = pwd
        self._initial_uat = user_auth_token


    def _build_initial_headers(self) -> Dict[str, str]:
        headers = {"X-App-Id": self.id}
        if self.force_english:
            headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Sec-Ch-Ua": "\"Chromium\";v=\"124\", \"Google Chrome\";v=\"124\", \"Not-A.Brand\";v=\"99\"",
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": "\"Windows\"",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            })
        else:
            headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
        return headers

    async def start(self) -> None:
        if self.session is None:
            self.session = aiohttp.ClientSession()
        await self.auth(self._initial_email, self._initial_pwd, self._initial_uat)
        await self.cfg_setup()

    async def close(self) -> None:
        if self.session:
            await self.session.close()

    def _generate_signature(self, base_string: str) -> str:
        return hashlib.md5(base_string.encode("utf-8")).hexdigest()

    def _normalize_json_strings(self, obj: Any) -> Any:
        if isinstance(obj, str):
            if "..." in obj and "://" not in obj:
                obj = obj.replace("...", "…")
            return unicodedata.normalize('NFC', obj)
        elif isinstance(obj, dict):
            return {k: self._normalize_json_strings(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._normalize_json_strings(item) for item in obj]
        return obj

    async def auth(self, email: str, pwd: str, user_auth_token: str = None) -> None:
        if user_auth_token:
            self.uat = user_auth_token
        elif pwd and len(pwd) > 60:
            self.uat = pwd
        else:
            usr_info = await self.api_call("user/login", email=email, pwd=pwd)
            if not usr_info.get("user", {}).get("credential", {}).get("parameters"):
                logger.info(f"{YELLOW}[!] Free account detected or validation bypassed.{OFF}")
            self.uat = usr_info.get("user_auth_token")
        
        if self.uat:
            self.headers.update({"X-User-Auth-Token": self.uat})
        
        try:
            user_info = await self.api_call("user/get")
            cred = user_info.get("credential") or user_info.get("user", {}).get("credential", {})
            self.label = cred.get("parameters", {}).get("short_label", "Studio")
            self.user_id = user_info.get("id") or user_info.get("user", {}).get("id")
            logger.info(f"{GREEN}[*] Status do Login: OK (Plano: {self.label}){OFF}")
        except Exception:
            logger.info(f"{YELLOW}[!] Assinatura Não Encontrada: FREE.{OFF}")
            self.label = "Studio"
            self.user_id = None

    def _modern_sig(self, epoint: str, params: dict, sec: str) -> str:
        object_, method = epoint.split("/")
        r_sig = [object_, method]
        for key in sorted(params):
            value = params[key]
            if key not in ("request_ts", "request_sig") and isinstance(value, (str, int, float)):
                r_sig.extend((key, str(value)))
        r_sig.extend((str(params["request_ts"]), str(sec) if sec is not None else ""))
        return self._generate_signature("".join(r_sig))

    @staticmethod
    def _b64url_decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def _derive_session_key(self) -> bytes:
        salt, info = self.session_infos.split(".")
        return HKDF(
            master=bytes.fromhex(self.sec),
            key_len=16,
            salt=self._b64url_decode(salt),
            hashmod=SHA256,
            context=self._b64url_decode(info)
        )

    def _unwrap_track_key(self, key_token: str) -> bytes:
        _, wrapped, iv = key_token.split(".")
        cipher = AES.new(self.session_key, AES.MODE_CBC, self._b64url_decode(iv))
        padded = cipher.decrypt(self._b64url_decode(wrapped))
        return unpad(padded, AES.block_size)

    async def _do_request(self, method: str, url: str, kwargs_req: dict, epoint: str) -> Tuple[int, str, Any]:
        max_retries = 4
        backoff_factor = 1

        for attempt in range(max_retries):
            try:
                if method == "POST":
                    async with self.session.post(url, **kwargs_req) as r:
                        status = r.status
                        text = await r.text()
                        json_resp = await r.json() if "application/json" in r.headers.get("Content-Type", "") else None
                else:
                    async with self.session.get(url, **kwargs_req) as r:
                        status = r.status
                        text = await r.text()
                        json_resp = await r.json() if "application/json" in r.headers.get("Content-Type", "") else None

                if status in [429, 500, 502, 503, 504]:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(backoff_factor * (2 ** attempt))
                        continue
                    r.raise_for_status()

                return status, text, json_resp

            except (aiohttp.ClientResponseError, aiohttp.ClientError) as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                    continue
                raise

    async def api_call(self, epoint: str, **kwargs) -> Dict:
        params = {}
        
        if epoint == "user/login":
            if kwargs.get("user_auth_token"):
                params = {"user_auth_token": kwargs["user_auth_token"], "app_id": self.id}
            else:
                params = {"email": kwargs.get("email"), "password": kwargs.get("pwd"), "app_id": self.id}
                
        elif epoint in ["track/getFileUrl", "file/url"]:
            fmt_id = kwargs["fmt_id"]
            if epoint == "track/getFileUrl" and int(fmt_id) not in (5, 6, 7, 27):
                raise InvalidQuality("Invalid quality id: choose between 5, 6, 7 or 27")
            if epoint == "file/url" and int(fmt_id) not in (6, 7, 27):
                raise InvalidQuality("Invalid quality id: choose between 6, 7 or 27")
                
            intent = "stream" if epoint == "track/getFileUrl" else "import"
            params = {"track_id": kwargs["id"], "format_id": fmt_id, "intent": intent}
            params["request_ts"] = int(time.time())
            
            if epoint == "track/getFileUrl":
                r_sig = f"trackgetFileUrlformat_id{fmt_id}intentstreamtrack_id{kwargs['id']}{params['request_ts']}{kwargs.get('sec', self.sec)}"
                params["request_sig"] = self._generate_signature(r_sig)
            else:
                params["request_sig"] = self._modern_sig(epoint, params, kwargs.get("sec", self.sec))

        elif epoint == "session/start":
            params = {"profile": "qbz-1", "app_id": self.id}
            params["request_ts"] = int(time.time())
            params["request_sig"] = self._modern_sig(epoint, params, kwargs.get("sec", self.sec))
            
        elif epoint == "favorite/getUserFavorites":
            params = {
                "app_id": self.id, "user_auth_token": self.uat, "user_id": self.user_id,
                "type": kwargs.get("fav_type", "albums"), "limit": kwargs.get("limit", 100),
                "offset": kwargs.get("offset", 0), "request_ts": int(time.time())
            }
            r_sig = f"favoritegetUserFavorites{params['request_ts']}{kwargs.get('sec', self.sec)}"
            params["request_sig"] = self._generate_signature(r_sig)
            
        elif epoint == "playlist/getUserPlaylists":
            params = {
                "app_id": self.id, "user_auth_token": self.uat, "user_id": self.user_id,
                "limit": kwargs.get("limit", 100), "offset": kwargs.get("offset", 0),
            }
        else:
            params = {'app_id': self.id}
            if self.force_english:
                params.update({'lang': 'en', 'locale': 'en_US'})
            
            val_id = kwargs.get('id')
            for k, v in kwargs.items():
                if k not in ['id', 'sec', 'fmt_id']:
                    params[k] = v

            if epoint == "album/get": params["album_id"] = val_id
            elif epoint == "track/get": params["track_id"] = val_id
            elif epoint == "playlist/get": params["playlist_id"] = val_id; params["extra"] = "tracks"
            elif epoint == "artist/get": params["artist_id"] = val_id; params["extra"] = "albums"
            elif epoint == "label/get": params["label_id"] = val_id; params["extra"] = "albums"

        params = {k: v for k, v in params.items() if v is not None}

        url = self.base + epoint
        req_kwargs = {"headers": self.headers.copy()}
        
        if epoint in ["user/login", "favorite/create", "playlist/addTracks", "playlist/create"]:
            method = "POST"
            if self.uat and epoint != "user/login":
                params["user_auth_token"] = self.uat
            req_kwargs["data"] = params
        elif epoint == "session/start":
            method = "POST"
            req_kwargs["data"] = params
            req_kwargs["headers"]["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            method = "GET"
            req_kwargs["params"] = params

        status, text, json_resp = await self._do_request(method, url, req_kwargs, epoint)

        if status >= 400 and epoint not in ["user/get"]:
            error_details = json_resp if json_resp else text
            raise Exception(f"HTTP {status} - {error_details}")

        if epoint == "user/get" and status == 400: 
            return {}

        if json_resp is not None:
            return self._normalize_json_strings(json_resp)
            
        return {}

    async def multi_meta(self, epoint: str, key: str, id: str, type: str) -> AsyncGenerator[Dict, None]:
        offset = 0
        limit = 50
        while True:
            j = await self.api_call(epoint, id=id, offset=offset, limit=limit, type=type)
            res = j[type] if type and type in j else j
            items_key = "tracks" if "playlist" in epoint else "albums"
            items = res.get(items_key, {}).get("items", [])
            if not items: break
            yield res
            offset += len(items)
            total_available = res.get(items_key, {}).get("total", res.get(key, 0))
            if offset >= total_available: break

    async def get_track_meta(self, id: str) -> Dict: 
        return await self.api_call("track/get", id=id)

    async def get_track_ids_from_list(self, tracks_list: list) -> list:
        print(f"{CYAN}[*] Matching Last.fm tracks with Qobuz database...{OFF}")
        valid_track_ids = []
        AUTO_ACCEPT_THRESHOLD = 0.75 
        PROMPT_THRESHOLD = 0.60      
        
        for item in tracks_list:
            target_artist = item['artist'].lower()
            target_title = item['title'].lower()
            query = f"{item['artist']} {item['title']}"
            
            try:
                search_results = await self.search_tracks(query, limit=5)
                best_match_id = None
                best_match_name = ""
                highest_ratio = 0.0
                
                if search_results and "tracks" in search_results and search_results["tracks"]["items"]:
                    for q_track in search_results["tracks"]["items"]:
                        q_artist_raw = q_track.get("performer", {}).get("name", "Unknown")
                        q_title_raw = q_track.get("title", "Unknown")
                        ratio = difflib.SequenceMatcher(None, f"{target_artist} {target_title}", f"{q_artist_raw.lower()} {q_title_raw.lower()}").ratio()
                        
                        if ratio > highest_ratio:
                            highest_ratio = ratio
                            best_match_id = q_track["id"]
                            best_match_name = f"{q_artist_raw} - {q_title_raw}"
                    
                    if highest_ratio >= AUTO_ACCEPT_THRESHOLD and best_match_id:
                        valid_track_ids.append(best_match_id)
                    elif highest_ratio >= PROMPT_THRESHOLD and best_match_id:
                        print(f"\n{YELLOW}[?] Borderline match detected ({highest_ratio*100:.0f}% similarity){OFF}")
                        # Jogado para fora do event loop para não congelar outros downloads assíncronos
                        choice = await asyncio.to_thread(input, f"{CYAN}    Do you want to download this track anyway? [y/n]: {OFF}")
                        if choice.strip().lower() == 'y':
                            valid_track_ids.append(best_match_id)
                    else:
                        print(f"{YELLOW}[!] Skipping: '{query}' (Best match: {highest_ratio*100:.0f}%){OFF}")
                else:
                    print(f"{YELLOW}[!] Skipping (No results): '{query}'{OFF}")
            except Exception as e:
                print(f"{RED}[!] Error searching for '{query}': {e}{OFF}")
                
        print(f"\n{GREEN}[+] Successfully matched {len(valid_track_ids)} out of {len(tracks_list)} tracks!{OFF}")
        return valid_track_ids

    async def search_albums(self, query: str, limit: int = 20) -> Dict:
        try: return await self.api_call("catalog/search", query=query, type="albums", limit=limit)
        except Exception: return {}

    async def search_tracks(self, query: str, limit: int = 20) -> Dict:
        try: return await self.api_call("catalog/search", query=query, type="tracks", limit=limit)
        except Exception: return {}

    async def search_playlists(self, query: str, limit: int = 20) -> Dict:
        try: return await self.api_call("catalog/search", query=query, type="playlists", limit=limit)
        except Exception: return {}

    async def search_artists(self, query: str, limit: int = 20) -> Dict:
        try: return await self.api_call("catalog/search", query=query, type="artists", limit=limit)
        except Exception: return {}

    async def get_favorites(self, fav_type: str = "albums", limit: int = 100, offset: int = 0) -> Dict:
        try: 
            if fav_type in ["playlists", "playlist"]:
                res = await self.api_call("playlist/getUserPlaylists", limit=limit, offset=offset)
                items = res.get("playlists", {}).get("items", res.get("items", []))
                total = res.get("playlists", {}).get("total", res.get("total", len(items)))
                return {"favorites": {"playlists": {"items": items, "total": total}}, "playlists": {"items": items, "total": total}}
                
            res = await self.api_call("favorite/getUserFavorites", fav_type=fav_type, limit=limit, offset=offset)
            items = []
            total = 0
            if "favorites" in res and fav_type in res["favorites"]:
                items = res["favorites"][fav_type].get("items", [])
                total = res["favorites"][fav_type].get("total", len(items))
            elif fav_type in res:
                items = res[fav_type].get("items", [])
                total = res[fav_type].get("total", len(items))
            return {"favorites": {fav_type: {"items": items, "total": total}}, fav_type: {"items": items, "total": total}}
        except Exception: 
            return {}

    async def get_user_playlists(self, limit: int = 100, offset: int = 0) -> Dict:
        try: return await self.api_call("playlist/getUserPlaylists", limit=limit, offset=offset)
        except Exception: return {}
            
    async def add_favorite_album(self, album_id: str) -> Dict:
        return await self.api_call("favorite/create", album_ids=str(album_id), artist_ids="", track_ids="")

    async def add_favorite_artist(self, artist_id: str) -> Dict:
        return await self.api_call("favorite/create", album_ids="", artist_ids=str(artist_id), track_ids="")

    async def add_favorite_track(self, track_id: str) -> Dict:
        return await self.api_call("favorite/create", album_ids="", artist_ids="", track_ids=str(track_id))

    async def add_playlist_tracks(self, playlist_id: str, track_ids: str) -> Dict:
        return await self.api_call("playlist/addTracks", playlist_id=str(playlist_id), track_ids=str(track_ids))
        
    async def create_playlist(self, name: str) -> Dict:
        return await self.api_call("playlist/create", name=name)

    async def get_track_url(self, id: str, fmt_id: int, force_segments: bool = False) -> Dict:
        if int(fmt_id) == 5:
            return await self.api_call("track/getFileUrl", id=id, fmt_id=fmt_id)

        if not force_segments:
            try:
                track = await self.api_call("track/getFileUrl", id=id, fmt_id=fmt_id)
                if "url" in track: return track
            except Exception: pass

        # Implementação do Lock para evitar race conditions na geração de sessões
        if self.session_id is None:
            async with self._session_lock:
                if self.session_id is None:  # Verificação dupla de segurança
                    session = await self.api_call("session/start")
                    self.session_id = session["session_id"]
                    self.session_infos = session["infos"]
                    self.session_key = self._derive_session_key()
                    self.headers.update({"X-Session-Id": self.session_id})

        track = await self.api_call("file/url", id=id, fmt_id=fmt_id)
        if "bits_depth" in track and "bit_depth" not in track: track["bit_depth"] = track["bits_depth"]
        if track.get("sampling_rate", 0) > 1000: track["sampling_rate"] = track["sampling_rate"] / 1000
        if "key" in track: track["raw_key"] = self._unwrap_track_key(track["key"])
        return track

    def get_artist_meta(self, id: str): return self.multi_meta("artist/get", "albums_count", id, None)
    def get_plist_meta(self, id: str): return self.multi_meta("playlist/get", "tracks_count", id, None)
    def get_label_meta(self, id: str): return self.multi_meta("label/get", "albums_count", id, None)
    async def get_album_meta(self, id: str): return await self.api_call("album/get", id=id)
    
    async def cfg_setup(self) -> None:
        for secret in self.secrets:
            try:
                await self.api_call("track/getFileUrl", id=5966783, fmt_id=5, sec=secret)
                self.sec = secret
                break
            except Exception:
                continue
        if not self.sec:
            raise InvalidAppSecretError("No secret found. All secrets failed validation")