import re
import urllib.request
import gzip
from collections import OrderedDict
from typing import Dict, Any, Tuple

class Bundle:
    """
    Dynamically extracts official App ID and App Secrets from the latest 
    Qobuz Web Player bundle.js (play.qobuz.com).
    """
    BASE_URL = "https://play.qobuz.com"
    BUNDLE_URL_REGEX = re.compile(r'<script\s+[^>]*?src="(?P<bundle_url>/resources/[^/]+/bundle\.js)"')
    APP_ID_REGEX = re.compile(r'production:\{api:\{[^{]*?app_id:"(?P<app_id>\d+)"')
    APP_ID_FALLBACK_REGEX = re.compile(r'app_id:\s*["\'](?P<app_id>\d{8,10})["\']')
    SEED_TIMEZONE_REGEX = re.compile(r'[a-z]\.initialSeed\("(?P<seed>[a-f0-9]+)",\s*window\.utimezone\.(?P<timezone>[a-z]+)\)')
    INFO_EXTRAS_REGEX = r'name:"\w+/(?P<timezone>{timezones})",info:"(?P<info>[a-f0-9]+)",extras:"(?P<extras>[a-f0-9]+)"'

    # Hardcoded known fallback credentials
    KNOWN_APP_ID = "712108709"
    KNOWN_SECRETS = {
        "berlin": "b59a6858e945c7d0d0c3260c6d7bb5e4",
        "paris": "4b68453be1a20ee43db2b0cb3ec0cfbe",
        "default": "b59a6858e945c7d0d0c3260c6d7bb5e4"
    }

    def __init__(self):
        self.bundle = ""
        self._app_id = self.KNOWN_APP_ID
        self._secrets = self.KNOWN_SECRETS

    def fetch_bundle(self) -> str:
        """Fetch bundle.js from play.qobuz.com."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br"
        }
        try:
            req = urllib.request.Request(f"{self.BASE_URL}/login", headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    html = gzip.decompress(data).decode("utf-8", errors="ignore")
                else:
                    html = data.decode("utf-8", errors="ignore")

            match = self.BUNDLE_URL_REGEX.search(html)
            bundle_rel = match.group("bundle_url") if match else "/resources/8.1.0-b019/bundle.js"
            bundle_url = f"{self.BASE_URL}{bundle_rel}"

            req_bundle = urllib.request.Request(bundle_url, headers=headers)
            with urllib.request.urlopen(req_bundle, timeout=12) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    self.bundle = gzip.decompress(data).decode("utf-8", errors="ignore")
                else:
                    self.bundle = data.decode("utf-8", errors="ignore")
            return self.bundle
        except Exception as e:
            return ""

    def get_app_id(self) -> str:
        """Extract or return latest App ID."""
        if not self.bundle:
            self.fetch_bundle()
        
        if self.bundle:
            match = self.APP_ID_REGEX.search(self.bundle) or self.APP_ID_FALLBACK_REGEX.search(self.bundle)
            if match:
                self._app_id = match.group("app_id")
                return self._app_id
        return self._app_id

    def get_secrets(self) -> Dict[str, str]:
        """Extract or return App Secrets dictionary."""
        if not self.bundle:
            self.fetch_bundle()

        if not self.bundle:
            return self._secrets

        try:
            seed_matches = list(re.finditer(self.SEED_TIMEZONE_REGEX, self.bundle))
            secrets_dict = OrderedDict()
            for match in seed_matches:
                seed, timezone = match.group("seed", "timezone")
                secrets_dict[timezone] = [seed]

            if not secrets_dict:
                return self._secrets

            timezones_pattern = "|".join([tz.capitalize() for tz in secrets_dict.keys()])
            info_extras_regex = re.compile(self.INFO_EXTRAS_REGEX.format(timezones=timezones_pattern))
            for match in re.finditer(info_extras_regex, self.bundle):
                tz = match.group("timezone").lower()
                info = match.group("info")
                extras = match.group("extras")
                if tz in secrets_dict:
                    secrets_dict[tz].extend([info, extras])

            final_secrets = {}
            for tz, parts in secrets_dict.items():
                if len(parts) == 3:
                    combined = "".join(parts)
                    final_secrets[tz] = combined

            if final_secrets:
                self._secrets = final_secrets
            return self._secrets
        except Exception:
            return self._secrets

    def get_tokens(self) -> Tuple[str, Dict[str, str]]:
        """Convenience method matching Qobuz-DLP."""
        app_id = self.get_app_id()
        secrets = self.get_secrets()
        return app_id, secrets
