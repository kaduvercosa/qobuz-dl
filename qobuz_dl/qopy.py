import base64
import hashlib
import logging
import time
import unicodedata
import json

import aiohttp
import asyncio


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
from qobuz_dl.color import GREEN, YELLOW, RED, OFF, RESET

try:
    from qobuz_dl.bundle import Bundle
except ImportError:
    Bundle = None

logger = logging.getLogger(__name__)

class Client:
    def __init__(self, email, pwd, app_id, secrets, user_auth_token=None, force_english=True):
        logger.info(f"{YELLOW}Logging...{OFF}")
        self.secrets = secrets
        self.id = str(app_id)
        self.secrets = secrets
        self.force_english = force_english
        
        if Bundle:
            try:
                b = Bundle()
                fresh_id = str(b.get_app_id())
                if fresh_id:
                    self.id = fresh_id
                    self.secrets = list(b.get_secrets().values())
                    logger.info(f"{GREEN}[+] App ID dynamically updated: {self.id}{OFF}")
            except Exception:
                pass

        self.headers = {}
        if self.force_english:
            self.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Sec-Ch-Ua": "\"Chromium\";v=\"124\", \"Google Chrome\";v=\"124\", \"Not-A.Brand\";v=\"99\"",
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": "\"Windows\"",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "X-App-Id": self.id,
            })
        else:
            self.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "X-App-Id": self.id,
            })

        self.session = None
        self.base = "https://www.qobuz.com/api.json/0.2/"
        self.sec = None
        self.session_id = None
        self.session_infos = None
        self.session_key = None
        
        self.uat = None
        
        # Auth and cfg_setup must be called via async start()
        self._initial_email = email
        self._initial_pwd = pwd
        self._initial_uat = user_auth_token

    async def start(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        await self.auth(self._initial_email, self._initial_pwd, self._initial_uat)
        await self.cfg_setup()

    async def close(self):
        if self.session:
            await self.session.close()

    def _generate_signature(self, base_string):
        """Helper to hash the old-school request_sig payloads."""
        return hashlib.md5(base_string.encode("utf-8")).hexdigest()

    def _normalize_json_strings(self, obj):
        if isinstance(obj, str):
            if "..." in obj and "://" not in obj:
                obj = obj.replace("...", "…")
            return unicodedata.normalize('NFC', obj)
        elif isinstance(obj, dict):
            return {k: self._normalize_json_strings(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._normalize_json_strings(item) for item in obj]
        else:
            return obj

    async def auth(self, email, pwd, user_auth_token=None):
        if user_auth_token:
            self.uat = user_auth_token
        elif pwd and len(pwd) > 60:
            self.uat = pwd
        else:
            usr_info = await self.api_call("user/login", email=email, pwd=pwd)
            if not usr_info.get("user", {}).get("credential", {}).get("parameters"):
                logger.info(f"{YELLOW}[!] Free account detected or validation bypassed.{OFF}")
            self.uat = usr_info["user_auth_token"]
        
        self.headers.update({"X-User-Auth-Token": self.uat})
        if getattr(self, 'session', None):
            # Aiohttp ClientSession headers are immutable. We must close and recreate, or we just pass the updated headers in the next requests.
            # Easiest way is to just let api_call use self.headers
            pass
        
        try:
            user_info = await self.api_call("user/get")
            cred = user_info.get("credential") or user_info.get("user", {}).get("credential", {})
            self.label = cred.get("parameters", {}).get("short_label", "Studio")
            self.user_id = user_info.get("id") or user_info.get("user", {}).get("id")
            logger.info(f"{GREEN}Logged: OK (Membership: {self.label}){OFF}")
        except Exception:
            logger.info(f"{YELLOW}[!] Profile validation bypassed.{OFF}")
            self.label = "Studio"
            self.user_id = None

    def _modern_sig(self, epoint, params, sec):
        object_, method = epoint.split("/")
        r_sig = [object_, method]
        for key in sorted(params):
            value = params[key]
            if key not in ("request_ts", "request_sig") and isinstance(value, (str, int, float)):
                r_sig.extend((key, str(value)))
        r_sig.extend((str(params["request_ts"]), str(sec) if sec is not None else ""))
        return self._generate_signature("".join(r_sig))

    @staticmethod
    def _b64url_decode(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def _derive_session_key(self):
        salt, info = self.session_infos.split(".")
        return HKDF(
            master=bytes.fromhex(self.sec),
            key_len=16,
            salt=self._b64url_decode(salt),
            hasmod=SHA256,
            context=self._b64url_decode(info)
        )

    def _unwrap_track_key(self, key_token):
        _, wrapped, iv = key_token.split(".")
        cipher = AES.new(
            self.session_key,
            AES.MODE_CBC,
            self._b64url_decode(iv)
        )
        padded = cipher.decrypt(self._b64url_decode(wrapped))
        return unpad(padded, AES.block_size)

    async def api_call(self, epoint, **kwargs):
        if epoint == "user/login":
            if "user_auth_token" in kwargs and kwargs["user_auth_token"]:
                params = {"user_auth_token": kwargs["user_auth_token"], "app_id": self.id}
            else:
                params = {"email": kwargs["email"], "password": kwargs["pwd"], "app_id": self.id}
        elif epoint == "track/getFileUrl":
            track_id = kwargs["id"]
            fmt_id = kwargs["fmt_id"]
            if int(fmt_id) not in (5, 6, 7, 27):
                raise InvalidQuality("Invalid quality id: choose between 5, 6, 7 or 27")
            params = {"track_id": track_id, "format_id": fmt_id, "intent": "stream"}
            unix = int(time.time())
            sec_to_use = kwargs.get('sec', self.sec)
            r_sig = f"trackgetFileUrlformat_id{fmt_id}intentstreamtrack_id{track_id}{unix}{sec_to_use}"
            params["request_ts"] = unix
            params["request_sig"] = self._generate_signature(r_sig)

        elif epoint == "session/start":
            params = {"profile": "qbz-1", "app_id": self.id}
            params["request_ts"] = int(time.time())
            params["request_sig"] = self._modern_sig(epoint, params, kwargs.get("sec", self.sec))
        elif epoint == "file/url":
            track_id = kwargs["id"]
            fmt_id = kwargs["fmt_id"]
            if int(fmt_id) not in (6, 7, 27):
                raise InvalidQuality("Invalid quality id: choose between 6, 7 or 27")
            params = {"track_id": track_id, "format_id": fmt_id, "intent": "import"}
            params["request_ts"] = int(time.time())
            params["request_sig"] = self._modern_sig(epoint, params, kwargs.get("sec", self.sec))
        elif epoint == "favorite/getUserFavorites":
            unix = int(time.time())
            r_sig = f"favoritegetUserFavorites{unix}{kwargs.get('sec', self.sec)}"
            params = {
                "app_id": self.id,
                "user_auth_token": getattr(self, 'uat', None),
                "user_id": getattr(self, 'user_id', None), 
                "type": kwargs.get("fav_type", "albums"),
                "limit": kwargs.get("limit", 100),
                "offset": kwargs.get("offset", 0),
                "request_ts": unix,
                "request_sig": self._generate_signature(r_sig),
            }
        elif epoint == "playlist/getUserPlaylists":
            # Sem assinaturas desnecessárias (conforme descoberto na API via iOS)
            params = {
                "app_id": self.id,
                "user_auth_token": getattr(self, 'uat', None),
                "user_id": getattr(self, 'user_id', None),
                "limit": kwargs.get("limit", 100),
                "offset": kwargs.get("offset", 0),
            }
        else:
            params = {'app_id': self.id}
            if getattr(self, 'force_english', True):
                params['lang'] = 'en'
                params['locale'] = 'en_US'
            
            val_id = kwargs.get('id')
            for k, v in kwargs.items():
                if k not in ['id', 'sec', 'fmt_id']:
                    params[k] = v

            if epoint == "album/get": params["album_id"] = val_id
            elif epoint == "track/get": params["track_id"] = val_id
            elif epoint == "playlist/get": params["playlist_id"] = val_id; params["extra"] = "tracks"
            elif epoint == "artist/get": params["artist_id"] = val_id; params["extra"] = "albums"
            elif epoint == "label/get": params["label_id"] = val_id; params["extra"] = "albums"

        # Async request with custom retry
        max_retries = 4
        backoff_factor = 1
        
        for attempt in range(max_retries):
            try:
                if epoint in ["user/login", "favorite/create"]:
                    async with self.session.post(self.base + epoint, data=params, headers=self.headers) as r:
                        status = r.status
                        text = await r.text()
                        json_resp = await r.json() if "application/json" in r.headers.get("Content-Type", "") else None
                elif epoint == "session/start":
                    h = self.headers.copy()
                    h["Content-Type"] = "application/x-www-form-urlencoded"
                    async with self.session.post(self.base + epoint, data=params, headers=h) as r:
                        status = r.status
                        text = await r.text()
                        json_resp = await r.json() if "application/json" in r.headers.get("Content-Type", "") else None
                else:
                    async with self.session.get(self.base + epoint, params=params, headers=self.headers) as r:
                        status = r.status
                        text = await r.text()
                        json_resp = await r.json() if "application/json" in r.headers.get("Content-Type", "") else None

                if status in [429, 500, 502, 503, 504]:
                    if attempt < max_retries - 1:
                        import asyncio
                        await asyncio.sleep(backoff_factor * (2 ** attempt))
                        continue
                    else:
                        r.raise_for_status()

                if epoint == "user/login" and status == 400:
                    if "invalid" in text.lower(): raise AuthenticationError("Invalid email or password.")
                    else: logger.info(f"{GREEN}Logged: OK{OFF}")
                elif epoint in ["track/getFileUrl", "favorite/getUserFavorites", "playlist/getUserPlaylists", "file/url"] and status == 400:
                    if json_resp:
                        raise InvalidAppSecretError(f"Invalid app secret: {json_resp}.\n" + RESET)
                    else:
                        raise InvalidAppSecretError(f"Invalid app secret. Status 400.\n" + RESET)

                if epoint == "user/get" and status == 400: return {}
                if status >= 400 and status != 400:
                     r.raise_for_status()

                if json_resp is not None:
                     return self._normalize_json_strings(json_resp)
                try:
                     return self._normalize_json_strings(await r.json())
                except Exception:
                     return {}

            except aiohttp.ClientResponseError as e:
                if attempt < max_retries - 1 and e.status in [429, 500, 502, 503, 504]:
                    import asyncio
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                    continue
                raise
            except aiohttp.ClientError as e:
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                    continue
                raise

    async def multi_meta(self, epoint, key, id, type):
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

    async def get_track_meta(self, id): return await self.api_call("track/get", id=id)

    async def get_track_ids_from_list(self, tracks_list: list) -> list:
        from qobuz_dl.color import OFF, GREEN, RED, YELLOW, CYAN
        import difflib
        
        print(f"{CYAN}[*] Matching Last.fm tracks with Qobuz database (Fuzzy matching & Interactive mode enabled)...{OFF}")
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
                        print(f"    Target (Last.fm): {item['artist']} - {item['title']}")
                        print(f"    Found  (Qobuz)  : {best_match_name}")
                        choice = input(f"{CYAN}    Do you want to download this track anyway? [y/n]: {OFF}").strip().lower()
                        if choice == 'y':
                            valid_track_ids.append(best_match_id)
                            print(f"{GREEN}    [+] Track accepted manually.{OFF}")
                        else:
                            print(f"{RED}    [-] Track skipped manually.{OFF}")
                    else:
                        print(f"{YELLOW}[!] Skipping: '{query}' (Best match was only {highest_ratio*100:.0f}% similar){OFF}")
                else:
                    print(f"{YELLOW}[!] Skipping (No results on Qobuz for): '{query}'{OFF}")
            except Exception as e:
                print(f"{RED}[!] Error searching for '{query}': {e}{OFF}")
                
        print(f"\n{GREEN}[+] Successfully matched {len(valid_track_ids)} out of {len(tracks_list)} tracks!{OFF}")
        return valid_track_ids

    async def search_albums(self, query, limit=20):
        try: return await self.api_call("catalog/search", query=query, type="albums", limit=limit)
        except Exception: return {}

    async def search_tracks(self, query, limit=20):
        try: return await self.api_call("catalog/search", query=query, type="tracks", limit=limit)
        except Exception: return {}

    async def search_playlists(self, query, limit=20):
        try: return await self.api_call("catalog/search", query=query, type="playlists", limit=limit)
        except Exception: return {}

    async def search_artists(self, query, limit=20):
        try: return await self.api_call("catalog/search", query=query, type="artists", limit=limit)
        except Exception: return {}

    async def get_favorites(self, fav_type="albums", limit=100, offset=0):
        try: 
            if fav_type in ["playlists", "playlist"]:
                res = await self.api_call("playlist/getUserPlaylists", limit=limit, offset=offset)
                
                items = []
                total = 0
                if "playlists" in res and "items" in res["playlists"]:
                    items = res["playlists"]["items"]
                    total = res["playlists"].get("total", len(items))
                elif "items" in res:
                    items = res["items"]
                    total = res.get("total", len(items))
                    
                return {
                    "favorites": {
                        "playlists": {
                            "items": items,
                            "total": total
                        }
                    },
                    "playlists": {
                        "items": items,
                        "total": total
                    }
                }
                
            # Default to favorites extraction if NOT playlist
            res = await self.api_call("favorite/getUserFavorites", fav_type=fav_type, limit=limit, offset=offset)

            # Reconstruct safely for normal items so it doesn't return NoneType on items extraction
            items = []
            total = 0
            if "favorites" in res and fav_type in res["favorites"]:
                items = res["favorites"][fav_type].get("items", [])
                total = res["favorites"][fav_type].get("total", len(items))
            elif fav_type in res:
                items = res[fav_type].get("items", [])
                total = res[fav_type].get("total", len(items))

            return {
                "favorites": {
                    fav_type: {
                        "items": items,
                        "total": total
                    }
                },
                fav_type: {
                    "items": items,
                    "total": total
                }
            }

        except Exception as e: 
            logger.error(f"{RED}[!] API Error fetching {fav_type}: {e}{OFF}")
            return {}

    async def get_user_playlists(self, limit=100, offset=0):
        try: 
            return await self.api_call("playlist/getUserPlaylists", limit=limit, offset=offset)
        except Exception as e: 
            logger.error(f"{RED}[!] API Error fetching playlists: {e}{OFF}")
            return {}
            
    async def add_favorite_album(self, album_id):
        return await self.api_call("favorite/create", album_ids=str(album_id), artist_ids="", track_ids="")
        
    async def get_track_url(self, id, fmt_id, force_segments=False):
        if int(fmt_id) == 5:
            return await self.api_call("track/getFileUrl", id=id, fmt_id=fmt_id)

        if not force_segments:
            try:
                track = await self.api_call("track/getFileUrl", id=id, fmt_id=fmt_id)
                if "url" in track: return track
            except Exception: pass

        if self.session_id is None:
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

    def get_artist_meta(self, id): return self.multi_meta("artist/get", "albums_count", id, None)
    def get_plist_meta(self, id): return self.multi_meta("playlist/get", "tracks_count", id, None)
    def get_label_meta(self, id): return self.multi_meta("label/get", "albums_count", id, None)
    async def get_album_meta(self, id): return await self.api_call("album/get", id=id)
    
    async def cfg_setup(self):
        for secret in self.secrets:
            try:
                await self.api_call("track/getFileUrl", id=5966783, fmt_id=5, sec=secret)
                self.sec = secret
                break
            except: continue
        if not self.sec and self.secrets: self.sec = self.secrets[0]
        if not self.sec: raise InvalidAppSecretError("No secret found.")
