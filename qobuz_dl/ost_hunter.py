import os
import re
import configparser
import asyncio
import sys
import unicodedata
import warnings
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Set
from pick import pick

# --- CALANDO OS AVISOS CHATOS DO AIOHTTP ---
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
logging.getLogger("aiohttp.client").setLevel(logging.CRITICAL)

from qobuz_dl.qopy import Client
from qobuz_dl.color import GREEN, YELLOW, CYAN, OFF, RED

# --- NORMALIZAÇÃO DE TEXTO ---
def normalizar_texto(texto: str) -> str:
    if not texto: return ""
    texto = unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('utf-8')
    return texto.lower().strip()

def _limpar_titulo_para_comparacao(titulo: str) -> str:
    t = normalizar_texto(titulo)
    t = re.sub(r"[\(\[].*?[\)\]]", "", t) 
    return re.sub(r"\s+", " ", t).strip()

def _truncar(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[:limite - 3] + "..."

# --- LÓGICA DE CLASSIFICAÇÃO ---
def classificar_tipo_lancamento(raw_type: str, title: str, t_count: int, duration: int) -> str:
    r_type = normalizar_texto(raw_type)
    title_l = normalizar_texto(title)
    if any(kw in title_l for kw in ("ep", "single", "album")):
        if "ep" in title_l: return "ep"
        if "single" in title_l: return "single"
    if t_count <= 1: return "single"
    if t_count <= 4 or duration < 1200: return "ep"
    return "album"

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

async def salvar_favorito(api: Client, album: Dict) -> None:
    artista = album.get("artist", {}).get("name", "Unknown")
    try:
        await api.add_favorite_album(album["id"])
        print(f"{GREEN}[+] Salvo nos favoritos: {artista} - {album['title']}{OFF}")
    except Exception as e:
        print(f"{RED}[-] Erro ao salvar {album['title']}: {e}{OFF}")

async def salvar_playlist(api: Client, album: Dict, playlists: List[Dict], query: str) -> None:
    album_id = str(album["id"])
    artista = album.get("artist", {}).get("name", "Unknown")
    album_nome = f"{artista} - {album['title']}"
    
    tipo = classificar_tipo_lancamento(album.get("release_type", ""), album.get("title", ""), album.get("tracks_count", 0), album.get("duration", 0))
    nome_nova_pl = album.get("title", "OST").upper() if tipo == "album" else f"{query.upper()} ({tipo.upper()})"

    playlist_ja_existe = any(pl.get('name', '').strip().upper() == nome_nova_pl for pl in playlists)

    opcoes_menu = []
    if not playlist_ja_existe:
        opcoes_menu.append(f">> Criar nova playlist: {nome_nova_pl}")

    for pl in playlists:
        opcoes_menu.append(f"{pl['name']} ({pl.get('tracks_count', 0)} faixas)")

    opcoes_menu.append(">> Cancelar / Pular")

    selecao_pl = pick(
        opcoes_menu,
        f"Destino para: {album_nome}\nEscolha a playlist (ENTER = confirmar):",
        multiselect=False
    )
    
    opcao_texto, pl_index = selecao_pl[0], selecao_pl[1]
    
    if opcao_texto.startswith(">> Cancelar"):
        print(f"{YELLOW}[*] Ação cancelada para: {album_nome}{OFF}")
        return
        
    elif opcao_texto.startswith(">> Criar"):
        print(f"{CYAN}[*] Criando playlist '{nome_nova_pl}'...{OFF}")
        try:
            nova_pl = await api.create_playlist(nome_nova_pl)
            playlist_id = str(nova_pl.get("playlist_id", nova_pl.get("id")))
            nova_pl_dict = {"name": nome_nova_pl, "id": playlist_id, "tracks_count": 0}
            playlists.insert(0, nova_pl_dict)
            playlist_escolhida = nova_pl_dict
        except Exception as e:
            print(f"{RED}[!] Erro ao criar playlist: {e}{OFF}")
            return
    else:
        offset = 1 if not playlist_ja_existe else 0
        real_index = pl_index - offset
        playlist_escolhida = playlists[real_index]
        playlist_id = str(playlist_escolhida["id"])
    
    print(f"{CYAN}[*] Puxando faixas de '{album_nome}'...{OFF}")
    track_ids = []
    try:
        album_data = await api.get_album_meta(album_id)
        for f in album_data.get("tracks", {}).get("items", []):
            track_ids.append(str(f["id"]))
    except Exception as e:
        print(f"{RED}[-] Erro ao ler faixas: {e}{OFF}")
        return

    if not track_ids:
        print(f"{RED}[!] Nenhuma faixa encontrada.{OFF}")
        return

    try:
        for i in range(0, len(track_ids), 50):
            lote = track_ids[i : i + 50]
            await api.add_playlist_tracks(playlist_id, ",".join(lote))
            await asyncio.sleep(0.5) 
            
        print(f"{GREEN}[+] Adicionado à '{playlist_escolhida['name']}': {album_nome}{OFF}")
        playlist_escolhida["tracks_count"] = playlist_escolhida.get("tracks_count", 0) + len(track_ids)
    except Exception as e:
        print(f"{RED}[-] Erro ao injetar músicas: {e}{OFF}")

async def amain():
    config = configparser.ConfigParser()
    config_path = Path(os.getenv("HOME", Path.home())) / ".config" / "qobuz-dl" / "config.ini"
    config.read(config_path)
    api = await setup_client(config, config.sections()[0])
    
    # Pega o argumento da linha de comando na primeira rodada, se houver
    query_inicial = sys.argv[1] if len(sys.argv) > 1 else ""
    
    while True:
        query = query_inicial if query_inicial else input(f"\n{YELLOW}Nome da Obra (ou ENTER para sair): {OFF}").strip()
        if not query:
            print(f"{CYAN}[*] Saindo do caçador...{OFF}")
            break
            
        print(f"{CYAN}[*] Caçando OSTs de '{query}'...{OFF}")
        
        # 1. Pesca Tripla expandida
        res_ost, res_albums, res_tracks = await asyncio.gather(
            api.api_call("catalog/search", query=f"{query} soundtrack", limit=100, type="albums"),
            api.api_call("catalog/search", query=query, limit=100, type="albums"),
            api.api_call("catalog/search", query=query, limit=100, type="tracks")
        )
        
        albums_brutos = res_ost.get("albums", {}).get("items", []) + res_albums.get("albums", {}).get("items", [])
        
        for track in res_tracks.get("tracks", {}).get("items", []):
            if "album" in track:
                album_data = track["album"]
                if "artist" not in album_data and "performer" in track:
                    album_data["artist"] = track["performer"]
                albums_brutos.append(album_data)

        must_have = [
            "soundtrack", "ost", "score", "original", "series", "motion picture", 
            "television", "musical", "cast", "music from", "disney", "netflix", 
            "amazon", "prime", "hbo", "apple", "hulu", "paramount", "film", "movie"
        ]
        must_not_have = ["karaoke", "tribute", "cover", "lullaby", "instrumental version", "karaokê", "8-bit"]
        
        query_norm = normalizar_texto(query)
        query_words = query_norm.split()
        must_not_have = [w for w in must_not_have if w not in query_norm]
        
        unicos = {}
        for item in albums_brutos:
            album_id = str(item.get("id"))
            if not album_id or album_id in unicos:
                continue
                
            title_norm = normalizar_texto(item.get("title", ""))
            artist_norm = normalizar_texto(item.get("artist", {}).get("name", ""))
            label_norm = normalizar_texto(item.get("label", {}).get("name", ""))
            
            matches_query = any((w in title_norm or w in artist_norm or w in label_norm) for w in query_words)
            is_ost = any(kw in title_norm or kw in artist_norm or kw in label_norm for kw in must_have)
            is_trash = any(kw in title_norm or kw in artist_norm for kw in must_not_have)
            
            if matches_query and is_ost and not is_trash:
                unicos[album_id] = item
                
        todos = list(unicos.values())
        
        fav_ids, fav_titles = await obter_dados_das_playlists(api)
        
        labels, validos = [], []
        for item in todos:
            item_id = str(item.get("id"))
            is_dup = item_id in fav_ids or _limpar_titulo_para_comparacao(item.get("title", "")) in fav_titles
            tipo = classificar_tipo_lancamento(item.get("release_type", ""), item.get("title", ""), item.get("tracks_count", 0), item.get("duration", 0))
            
            status = " (Já existe na biblioteca)" if is_dup else ""
            
            artista = item.get("artist") or {}
            artist_name = _truncar(artista.get("name", "Unknown") if isinstance(artista, dict) else "Unknown", 25)
            titulo = _truncar(item.get('title', ''), 60)
            
            tipo_str = f"[{tipo.title()[:6].ljust(6)}]"
            label = f"{'✅' if is_dup else '⬜'} {tipo_str} {artist_name:<25} | {titulo:<60}{status}"
            labels.append(label)
            validos.append(item)

        if not labels:
            print(f"\n{RED}[!] Nenhuma OST encontrada para '{query}'.{OFF}")
            print(f"{YELLOW}Dica: Plataformas de música geralmente usam o nome original do filme.{OFF}")
            # Limpa a query inicial para forçar o input na próxima rodada do loop
            query_inicial = "" 
            continue # Volta para o começo do While e pede o nome de novo
        else:
            selecoes = pick(
                labels, 
                f"OSTs encontradas para '{query}'\n(Espaço p/ marcar, Enter p/ confirmar):", 
                multiselect=True
            )
            
            if selecoes:
                try:
                    pl_data = await api.get_user_playlists(limit=100) 
                    user_playlists = pl_data.get("playlists", {}).get("items", []) or []
                except:
                    user_playlists = []

                print(f"\n{CYAN}{'='*75}{OFF}\n")

                for item_label, index in selecoes:
                    album = validos[index]
                    artista = album.get("artist", {}).get("name", "Unknown")
                    album_nome = f"{artista} - {album['title']}"

                    if "✅" in item_label:
                        print(f"{YELLOW}[!] Pulando duplicado: {album_nome}{OFF}")
                        continue

                    resp = pick(
                        ["1. Salvar nos Álbuns Favoritos", "2. Adicionar a uma Playlist", "3. Pular"],
                        f"O que deseja fazer com a OST:\n► {album_nome}?",
                        multiselect=False
                    )
                    
                    if "1." in resp[0]:
                        await salvar_favorito(api, album)
                    elif "2." in resp[0]:
                        await salvar_playlist(api, album, user_playlists, query)
                    else:
                        print(f"{YELLOW}[*] Pulado: {album_nome}{OFF}")
            else:
                print(f"{YELLOW}[*] Nenhuma OST selecionada.{OFF}")
            
            # Se tudo deu certo, quebra o loop e encerra o programa
            break
            
    await api.close()

if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print(f"\n{RED}[!] Caçador de Trilhas manualmente interrompido.. (CTRL+C).{OFF}")
        sys.exit(0)