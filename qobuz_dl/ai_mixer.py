import os
import json
import logging
import asyncio
import aiohttp
from pathvalidate import sanitize_filename
from qobuz_dl.color import OFF, GREEN, RED, YELLOW, CYAN
from qobuz_dl.settings import QobuzDLSettings
from qobuz_dl.utils import make_m3u

logger = logging.getLogger(__name__)

async def get_ai_recommendation(provider: str, api_key: str, concept: str, tracks: list, limit: int) -> list:
    if not api_key:
        print(f"{RED}[!] API key for {provider} is not configured. Please set it in config.ini or pass it as an argument.{OFF}")
        return []

    system_prompt = (
        f"You are an AI DJ creating a playlist based on the concept: '{concept}'. "
        f"You have a specific catalog of available tracks. "
        f"Return ONLY a raw JSON list of integers corresponding to the track IDs from the catalog. "
        f"Select up to {limit} tracks. Do NOT include markdown blocks like ```json."
    )

    catalog_text = "\n".join([f"{i}: {t['artist']} - {t['title']}" for i, t in enumerate(tracks)])
    user_prompt = f"Available Catalog:\n{catalog_text}\n\nReturn ONLY the JSON list of IDs."

    selected_ids = []

    async with aiohttp.ClientSession() as session:
        if provider.lower() == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7
            }
            try:
                async with session.post(url, headers=headers, json=data, timeout=30) as resp:
                    if resp.status != 200:
                        print(f"{RED}[!] OpenAI API Error: {resp.status} - {await resp.text()}{OFF}")
                        return []
                    res_json = await resp.json()
                    content = res_json["choices"][0]["message"]["content"].strip()
                    # Strip markdown blocks if the model ignored instructions
                    if content.startswith("```"):
                        content = content.split('\n', 1)[1].rsplit('\n', 1)[0]
                    selected_ids = json.loads(content)
            except Exception as e:
                print(f"{RED}[!] Failed to communicate with OpenAI: {e}{OFF}")
                return []

        elif provider.lower() == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            data = {
                "contents": [
                    {"parts": [{"text": system_prompt + "\n\n" + user_prompt}]}
                ],
                "generationConfig": {"temperature": 0.7}
            }
            try:
                async with session.post(url, headers=headers, json=data, timeout=30) as resp:
                    if resp.status != 200:
                        print(f"{RED}[!] Gemini API Error: {resp.status} - {await resp.text()}{OFF}")
                        return []
                    res_json = await resp.json()
                    content = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if content.startswith("```"):
                        content = content.split('\n', 1)[1].rsplit('\n', 1)[0]
                    selected_ids = json.loads(content)
            except Exception as e:
                print(f"{RED}[!] Failed to communicate with Gemini: {e}{OFF}")
                return []
        else:
            print(f"{RED}[!] Unsupported AI Provider: {provider}{OFF}")
            return []

    if not isinstance(selected_ids, list):
        print(f"{RED}[!] AI returned malformed response. Ensure it outputs a JSON list of integers.{OFF}")
        return []

    # Filter out invalid IDs
    valid_selected = []
    for t_id in selected_ids:
        try:
            tid = int(t_id)
            if 0 <= tid < len(tracks):
                valid_selected.append(tracks[tid])
        except (ValueError, TypeError):
            continue

    return valid_selected

def extract_metadata_from_file(file_path):
    import os
    ext = os.path.splitext(file_path)[1].lower()
    artist = "Unknown Artist"
    title = os.path.basename(file_path)

    try:
        if ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(file_path)
            if audio.get("ARTIST"): artist = audio.get("ARTIST")[0]
            if audio.get("TITLE"): title = audio.get("TITLE")[0]
        elif ext == ".mp3":
            from mutagen.id3 import ID3
            audio = ID3(file_path)
            if audio.get("TPE1"): artist = audio.get("TPE1").text[0]
            if audio.get("TIT2"): title = audio.get("TIT2").text[0]
    except Exception:
        pass

    return artist, title

def scan_local_library(directory):
    import os
    tracks = []
    EXTENSIONS = (".mp3", ".flac")
    print(f"{CYAN}[*] Scanning local library in {directory}...{OFF}")
    for root, _, files in os.walk(directory):
        for f in files:
            if os.path.splitext(f)[-1].lower() in EXTENSIONS:
                full_path = os.path.abspath(os.path.join(root, f))
                artist, title = extract_metadata_from_file(full_path)
                tracks.append({
                    "path": full_path,
                    "artist": artist,
                    "title": title
                })
    return tracks

async def generate_smart_mix(directory: str, concept: str, limit: int, settings: QobuzDLSettings):
    print(f"\n{GREEN}=== Qobuz-DL Smart Mix ==={OFF}")

    if not os.path.exists(directory):
        print(f"{RED}[!] Directory not found: {directory}{OFF}")
        return

    tracks = scan_local_library(directory)
    if not tracks:
        print(f"{YELLOW}[!] No audio files found in {directory}. Download some tracks first!{OFF}")
        return

    print(f"{GREEN}[+] Found {len(tracks)} tracks in your library.{OFF}")

    provider = settings.ai_provider
    api_key = settings.openai_api_key if provider.lower() == "openai" else settings.gemini_api_key

    if not api_key:
        print(f"{RED}[!] You must provide an API Key in config.ini ([qobuz] {provider}_api_key=YOUR_KEY) or via CLI.{OFF}")
        return

    print(f"{CYAN}[*] Requesting AI playlist for concept: '{concept}' (Provider: {provider})...{OFF}")

    selected_tracks = await get_ai_recommendation(provider, api_key, concept, tracks, limit)

    if not selected_tracks:
        print(f"{RED}[!] No tracks were selected by the AI.{OFF}")
        return

    print(f"{GREEN}[+] AI selected {len(selected_tracks)} tracks!{OFF}")

    # Generate the M3U playlist file
    pl_name = sanitize_filename(concept.title()) + ".m3u"
    pl_path = os.path.join(directory, pl_name)

    track_list = ["#EXTM3U"]
    for t in selected_tracks:
        rel_path = os.path.relpath(t["path"], directory)
        track_list.append(f"#EXTINF:-1,{t['artist']} - {t['title']}")
        track_list.append(rel_path)

    with open(pl_path, "w", encoding="utf-8") as f:
        f.write("\n".join(track_list))

    print(f"{GREEN}  L Completed: Playlist saved as {pl_path}{OFF}")
