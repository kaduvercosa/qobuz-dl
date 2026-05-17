import os
import json
import logging
import asyncio
import aiohttp
import time
from datetime import datetime, timezone
from qobuz_dl.color import OFF, GREEN, RED, YELLOW, CYAN
from qobuz_dl.settings import QobuzDLSettings

logger = logging.getLogger(__name__)

async def scan_new_releases(qobuz_client, run_once=True, test_mode=False):
    print(f"\n{CYAN}=============================================={OFF}")
    print(f"{CYAN}       QOBUZ-DL AUTONOMOUS WATCHER DAEMON    {OFF}")
    print(f"{CYAN}=============================================={OFF}\n")

    settings: QobuzDLSettings = qobuz_client.settings
    webhook_url = getattr(settings, 'webhook_url', '')

    if not webhook_url:
        print(f"{RED}[!] Webhook URL is not configured.{OFF}")
        print(f"{YELLOW}Please add 'webhook_url = http://seuservidor-n8n.com/webhook/...' to the [qobuz] section of your config.ini.{OFF}")
        return

    # Initialize seen releases local database
    import qobuz_dl.cli
    db_path = os.path.join(qobuz_dl.cli.CONFIG_PATH, "seen_releases.json")

    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as f:
            try:
                seen_releases = json.load(f)
            except json.JSONDecodeError:
                seen_releases = {}
    else:
        seen_releases = {}

    new_releases = []
    current_year = str(datetime.now(timezone.utc).year)

    print(f"{CYAN}[*] Fetching your favorite artists from Qobuz...{OFF}")
    try:
        fav_response = await qobuz_client.client.get_favorites(fav_type="artists", limit=200)
    except Exception as e:
        print(f"{RED}[!] Error fetching favorite artists: {e}{OFF}")
        return

    artists = []
    if "favorites" in fav_response and "artists" in fav_response["favorites"]:
        artists = fav_response["favorites"]["artists"].get("items", [])
    elif "artists" in fav_response:
        artists = fav_response["artists"].get("items", [])

    if not artists:
        print(f"{YELLOW}[!] No favorite artists found in your Qobuz account.{OFF}")
        return

    print(f"{GREEN}[+] Found {len(artists)} favorite artists. Scanning for new releases...{OFF}")

    # Process concurrent requests but limit batching to avoid rate limits
    sem = asyncio.Semaphore(5)

    async def fetch_artist_albums(artist):
        async with sem:
            try:
                # Using extra="albums" filters out Singles and EPs on some endpoints.
                # Removing the "extra" parameter altogether forces Qobuz to return all releases (Albums, EPs, Singles)
                meta = await qobuz_client.client.api_call("artist/get", artist_id=artist["id"], limit=20)

                # Depending on the Qobuz endpoint response for 'artist/get' without 'extra',
                # releases might be in meta["albums"] or meta["releases"]
                albums_items = meta.get("albums", {}).get("items", []) or meta.get("releases", {}).get("items", [])

                for album in albums_items:
                    album_id = str(album["id"])
                    release_date = album.get("release_date_original", "")

                    if test_mode:
                        print(f"{YELLOW}[!] Running in TEST MODE. Bypassing date restrictions and using real Qobuz data...{OFF}")
                        return album

                    # Only care about recent releases (this year) that haven't been seen yet
                    if release_date.startswith(current_year) and album_id not in seen_releases:
                        return album
            except Exception:
                pass
        return None

    if test_mode:
        # Just grab the latest releases from the first 2 artists to avoid spamming the webhook
        tasks = [fetch_artist_albums(artist) for artist in artists[:2]]
    else:
        tasks = [fetch_artist_albums(artist) for artist in artists]

    results = await asyncio.gather(*tasks)

    for album in results:
        if album:
            new_releases.append(album)

    if not new_releases:
        print(f"{GREEN}[+] No new releases detected. You are completely up to date!{OFF}")
        return

    print(f"\n{YELLOW}[!] Found {len(new_releases)} NEW releases! Dispatching Webhooks to n8n...{OFF}")

    async with aiohttp.ClientSession() as session:
        for album in new_releases:
            album_id = str(album.get("id"))
            artist_name = album.get("artist", {}).get("name", "Unknown Artist")
            album_title = album.get("title", "Unknown Title")
            release_date = album.get("release_date_original", "Unknown")

            bit_depth = album.get("maximum_bit_depth", 16)
            sampling_rate = album.get("maximum_sampling_rate", 44.1)
            hires = "Yes" if bit_depth >= 24 else "No"

            release_type = album.get("release_type", "album").capitalize()
            cover_url = album.get("image", {}).get("large", "")
            qobuz_url = f"https://open.qobuz.com/album/{album_id}"

            # Additional detailed metadata
            label = album.get("label", {}).get("name", "Independent")
            track_count = album.get("tracks_count", 0)
            genres_list = album.get("genres_list", [])
            explicit = album.get("parental_warning", False)

            payload = {
                "event": "new_release",
                "artist": artist_name,
                "title": album_title,
                "type": release_type,
                "release_date": release_date,
                "is_hires": hires,
                "bit_depth": bit_depth,
                "sampling_rate": sampling_rate,
                "label": label,
                "track_count": track_count,
                "genres": genres_list,
                "explicit": explicit,
                "cover_url": cover_url,
                "url": qobuz_url
            }

            try:
                async with session.post(webhook_url, json=payload, timeout=10) as resp:
                    if resp.status in [200, 201, 202, 204]:
                        print(f"  {GREEN}➔ Dispatched:{OFF} {artist_name} - {album_title}")
                        # Mark as seen
                        seen_releases[album_id] = int(time.time())
                    else:
                        print(f"  {RED}➔ Failed to dispatch (HTTP {resp.status}):{OFF} {artist_name} - {album_title}")
            except Exception as e:
                 print(f"  {RED}➔ Network Error dispatching webhook:{OFF} {e}")

    # Save updated local DB
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(seen_releases, f, ensure_ascii=False, indent=4)

    print(f"\n{GREEN}Scan complete!{OFF}")
