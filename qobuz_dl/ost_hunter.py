import os
import re
import configparser
import asyncio
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Set
from pick import pick

from qobuz_dl.qopy import Client
from qobuz_dl.color import GREEN, YELLOW, CYAN, OFF, RED

# --- LÓGICA DE CLASSIFICAÇÃO ---
def classificar_tipo_lancamento(raw_type: str, title: str, t_count: int, duration: int) -> str:
    r_type = (raw_type or "").lower()
    title_l = title.lower()
    if any(kw in title_l for kw in ("ep", "single", "album")):
        if "ep" in title_l: return "ep"
        if "single" in title_l: return "single"
    if t_count <= 1: return "single"
    if t_count <= 4 or duration < 1200: return "ep"
    return "album"

def _limpar_titulo_para_comparacao(titulo: str) -> str:
    t = (titulo or "").lower()
    t = re.sub(r"[\(\[].*?[\)\]]", "", t) 
    return re.sub(r"\s+", " ", t).strip()

async def setup_client(config: configparser.ConfigParser, section: str) -> Client:
    api = Client(config.get(section, "email"), config.get(section, "password", fallback=""), 
                 app_id=config.get(section, "app_id"), secrets=[s.strip() for s in config.get(section, "secrets").split(",")], 
                 user_auth_token=config.get(section, "auth_token", fallback=""))
    await api.start()
    return api

async def obter_dados_das_playlists(api: Client) -> Tuple[Set[str], Set[str]]:
    album_ids, album_titles = set(), set()
    try:
        playlists_data = await api.get_user_playlists(limit=100)
        playlists = playlists_data.get("playlists", {}).get("items", [])
        for p in playlists:
            async for chunk in api.get_plist_meta(str(p["id"])):
                for track in chunk.get("tracks", {}).get("items", []):
                    if "album" in track:
                        album_ids.add(str(track["album"]["id"]))
                        album_titles.add(_limpar_titulo_para_comparacao(track["album"].get("title", "")))
    except Exception: pass
    return album_ids, album_titles

async def processar_destino(api: Client, item: Dict, query: str) -> None:
    tipo = classificar_tipo_lancamento(item.get("release_type", ""), item.get("title", ""), item.get("tracks_count", 0), item.get("duration", 0))
    playlist_name = item.get("title", "OST").upper() if tipo == "album" else f"{query.upper()} ({tipo.upper()})"

    playlists = (await api.get_user_playlists(limit=100)).get("playlists", {}).get("items", []) or []
    pl_id = next((str(pl["id"]) for pl in playlists if pl.get("name", "").strip().upper() == playlist_name), None)
    
    if not pl_id:
        print(f"{CYAN}[*] Criando playlist '{playlist_name}'...{OFF}")
        nova_pl = await api.create_playlist(playlist_name)
        pl_id = str(nova_pl.get("playlist_id", nova_pl.get("id")))

    meta = await api.get_album_meta(str(item.get("id")))
    track_ids = [str(f["id"]) for f in meta.get("tracks", {}).get("items", [])]
    await api.add_playlist_tracks(pl_id, ",".join(track_ids))
    print(f"{GREEN}[+] Adicionado {len(track_ids)} faixas a '{playlist_name}'.{OFF}")

async def amain():
    config = configparser.ConfigParser()
    config_path = Path(os.getenv("HOME", Path.home())) / ".config" / "qobuz-dl" / "config.ini"
    config.read(config_path)
    api = await setup_client(config, config.sections()[0])
    
    query = sys.argv[1] if len(sys.argv) > 1 else input(f"{YELLOW}Obra: {OFF}")
    print(f"{CYAN}[*] Caçando OSTs de '{query}'...{OFF}")
    
    res = await api.api_call("catalog/search", query=f"{query} soundtrack", limit=50, type="albums")
    must_have = ["soundtrack", "ost", "score", "original", "series", "motion picture", "television"]
    
    todos = [
        item for item in res.get("albums", {}).get("items", [])
        if any(kw in item.get("title", "").lower() for kw in must_have)
    ]
    
    fav_ids, fav_titles = await obter_dados_das_playlists(api)
    
    labels, validos = [], []
    for item in todos:
        item_id = str(item.get("id"))
        is_dup = item_id in fav_ids or _limpar_titulo_para_comparacao(item.get("title", "")) in fav_titles
        tipo = classificar_tipo_lancamento(item.get("release_type", ""), item.get("title", ""), item.get("tracks_count", 0), item.get("duration", 0))
        
        status = " (Já existe)" if is_dup else ""
        # Tabela espaçada e limpa
        label = f"{'✅' if is_dup else '⬜'} [{tipo.upper():^6}] {item.get('artist', {}).get('name', 'Unknown')[:20]:<20} | {item.get('title', '')[:65]:<65}{status}"
        labels.append(label)
        validos.append(item)

    if not labels:
        print(f"{RED}[!] Nenhuma OST encontrada para '{query}'.{OFF}")
    else:
        selecoes = pick(labels, "Espaço p/ selecionar, Enter p/ confirmar:", multiselect=True)
        if selecoes:
            for item_label, index in selecoes:
                if "✅" not in item_label:
                    await processar_destino(api, validos[index], query)
                else:
                    print(f"{YELLOW}[!] Pulando duplicado: {validos[index].get('title')}{OFF}")
    
    await api.close()

if __name__ == "__main__":
    asyncio.run(amain())