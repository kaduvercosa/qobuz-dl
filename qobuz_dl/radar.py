import os
import re
import configparser
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Tuple, Set
from pick import pick

from qobuz_dl.qopy import Client
from qobuz_dl.color import GREEN, YELLOW, RED, CYAN, OFF
from qobuz_dl.core import classificar_tipo_lancamento

# --- Configurações de Logging ---
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("radar")

# --- Helpers de UI ---
def print_separator(): 
    print(f"\n{CYAN}{'='*75}{OFF}\n")

def _pluralizar(n, sing, plur): 
    return f"{n} {sing if n == 1 else plur}"

def _truncar(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[:limite - 3] + "..."

def _data_relativa(data_str, hoje):
    try:
        data = datetime.strptime(data_str, "%Y-%m-%d").date()
        delta = (hoje - data).days
        if delta == 0: return "hoje"
        if delta == 1: return "ontem"
        if delta <= 6: return f"há {delta} dias"
        return f"há {delta} dias"
    except: return data_str

def _limpar_titulo(titulo: str) -> str:
    t = (titulo or "").lower()
    t = re.sub(r"[\(\[].*?[\)\]]", "", t) 
    return re.sub(r"[^\w\s]", "", t).strip()

def _progresso(atual: int, total: int, nome: str) -> None:
    if not sys.stdout.isatty() or total == 0: 
        return
        
    tamanho = 25
    percentual = atual / total
    blocos = int(percentual * tamanho)
    resto = (percentual * tamanho) - blocos
    fracoes = [' ', '▏', '▎', '▍', '▌', '▋', '▊', '▉', '█']
    
    barra = '█' * blocos
    if blocos < tamanho:
        barra += fracoes[int(resto * 8)]
        barra += ' ' * (tamanho - blocos - 1)
        
    pct_str = f"{int(percentual * 100):>3}%"
    print(f"\r\033[K{CYAN}Progresso: {OFF}[{GREEN}{barra}{OFF}] {CYAN}{pct_str} ({atual}/{total}) {YELLOW}► {OFF}{nome}", end="", flush=True)

_PREFIX_TIPO = {
    "Álbum":  "[Álbum ]",
    "EP":     "[EP    ]",
    "Single": "[Single]",
    "Live":   "[Live  ]",
    "VA / Coletânea": "[Colet ]"
}

# --- Lógica de Montagem do Menu ---
def montar_opcoes(lancamentos: List[Dict], hoje: "datetime.date") -> Tuple[List[str], List[int]]:
    grupos: Dict[str, List[Tuple[int, Dict]]] = {}
    for original_idx, l in enumerate(lancamentos):
        grupos.setdefault(l["artist"], []).append((original_idx, l))

    labels:  List[str] = []
    indices: List[int] = []

    for artista, items in grupos.items():
        if labels:
            labels.append(" ")
            indices.append(-1)
            
        badge = f"  ({_pluralizar(len(items), 'novo', 'novos')})"
        labels.append(f"── {artista}{badge} {'─' * max(0, 45 - len(artista))}")
        indices.append(-1) 

        for original_idx, item in items:
            data_rel = _data_relativa(item["date"], hoje)
            hires = "HR " if item.get("hires") else "   "
            
            if item["role"] == "featured":
                tipo_str = "[Feat  ]"
                titulo   = _truncar(f"{item['album_artist']} - {item['title']} ft. {item['artist']}", 55)
            else:
                tipo_str = _PREFIX_TIPO.get(item["type"], f"[{item['type'][:6].ljust(6)}]")
                titulo   = _truncar(f"{item['artist']} - {item['title']}", 55)

            label = f"  ► {tipo_str:<10} {hires:<3} {titulo:<55} {data_rel:>10}"

            labels.append(label)
            indices.append(original_idx)

    return labels, indices

# --- Lógica do Radar ---
class RadarConfig:
    def __init__(self, config, section):
        self.dias_de_busca = config.getint(section, "dias_de_busca", fallback=7)
        self.max_concurrent = config.getint(section, "max_concurrent", fallback=10)
        self.ignorar_titulos = [t.strip().lower() for t in config.get(section, "ignorar_titulos", fallback="").split(",") if t.strip()]

def _checar_papel(album, artist_id):
    artists = album.get("artists") or []
    for a in artists:
        if str(a.get("id") or "") == artist_id:
            return True, "main"
    return False, ""

async def setup_client(config, section):
    api = Client(
        email=config.get(section, "email", fallback=""),
        pwd=config.get(section, "password", fallback=""),
        app_id=config.get(section, "app_id"),
        secrets=[s.strip() for s in config.get(section, "secrets").split(",")],
        user_auth_token=config.get(section, "auth_token", fallback="")
    )
    await api.start()
    return api

async def obter_dados_das_playlists(api: Client) -> Tuple[Set[str], Set[str]]:
    album_ids = set()
    album_titles = set()
    try:
        playlists_data = await api.get_user_playlists(limit=100)
        playlists = playlists_data.get("playlists", {}).get("items", [])
        if not playlists:
            return album_ids, album_titles
        
        async def fetch_playlist_tracks(pl_id):
            local_ids = set()
            local_titles = set()
            try:
                async for chunk in api.get_plist_meta(pl_id):
                    for track in chunk.get("tracks", {}).get("items", []):
                        if "album" in track and "id" in track["album"]:
                            local_ids.add(str(track["album"]["id"]))
                            local_titles.add(_limpar_titulo(track["album"].get("title", "")))
            except: pass
            return local_ids, local_titles
        
        resultados = await asyncio.gather(*(fetch_playlist_tracks(str(p["id"])) for p in playlists))
        for r_ids, r_titles in resultados:
            album_ids.update(r_ids)
            album_titles.update(r_titles)
    except Exception: pass
    return album_ids, album_titles

async def fetch_artist_latest_releases(api, artist_id, artist_name, semaphore, cfg, contador):
    novidades = []
    ids_locais = set()
    hoje = datetime.now(timezone.utc).date()
    data_limite = hoje - timedelta(days=cfg.dias_de_busca)

    async with semaphore:
        try:
            async for chunk in api.get_artist_meta(artist_id):
                for categoria in ["albums", "singles", "eps", "appears_on", "featured_in"]:
                    for album in chunk.get(categoria, {}).get("items", []):
                        if album.get("id") in ids_locais: continue
                        ids_locais.add(album.get("id"))
                        
                        participa, papel = _checar_papel(album, artist_id)
                        if not participa: continue

                        data_str = str(album.get("release_date_original") or album.get("release_date") or "")
                        match = re.search(r"\d{4}-\d{2}-\d{2}", data_str)
                        if match and datetime.strptime(match.group(), "%Y-%m-%d").date() >= data_limite:
                            tipo_raw = classificar_tipo_lancamento(
                                raw_type=album.get("release_type") or album.get("product_type"),
                                title=str(album.get("title", "")),
                                version=str(album.get("version", "")),
                                t_count=album.get("tracks_count", 0),
                                duration=album.get("duration", 0),
                            )
                            is_va = (album.get("artist") or {}).get("name") == "Various Artists"
                            tipo_display = "VA / Coletânea" if is_va else {"album": "Álbum", "ep": "EP"}.get(tipo_raw, tipo_raw.title())
                            hires = bool(album.get("hires_streamable") or album.get("hires") or (album.get("maximum_bit_depth", 0) or 0) > 16)
                            
                            novidades.append({
                                "id": str(album.get("id")), "title": album.get("title", "Unknown"), 
                                "artist": artist_name, "album_artist": (album.get("artist") or {}).get("name", artist_name),
                                "type": tipo_display, "date": match.group(), "role": papel, "hires": hires
                            })
        except: pass
        finally:
            contador[0] += 1
            _progresso(contador[0], contador[1], artist_name)
    return novidades

async def salvar_favorito(api: Client, album: Dict) -> None:
    try:
        await api.add_favorite_album(album["id"])
        print(f"{GREEN}[+] Salvo nos favoritos: {album['artist']} - {album['title']}{OFF}")
    except Exception as e:
        print(f"{RED}[-] Erro ao salvar {album['title']}: {e}{OFF}")

async def salvar_playlist(api: Client, album: Dict, playlists: List[Dict]) -> None:
    album_id = str(album["id"])
    album_nome = f"{album['artist']} - {album['title']}"
    nome_nova_pl = album['artist'].upper()

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

async def _async_run_radar():
    config_path = Path.home() / ".config" / "qobuz-dl" / "config.ini"
    config = configparser.ConfigParser()
    config.read(config_path)

    if not config.sections():
        print(f"{RED}[!] Erro: Seção não encontrada no config.ini em {config_path}{OFF}")
        return

    section = config.sections()[0]
    cfg = RadarConfig(config, section)
    
    try:
        api = await setup_client(config, section)
    except Exception as e:
        print(f"{RED}[!] Erro ao conectar: {e}{OFF}")
        return
    
    print(f"{CYAN}[*] Sincronizando e analisando a sua biblioteca...{OFF}")
    # ADICIONE ESTA LINHA AQUI:
    print(f"{CYAN}[*] Período de busca configurado: {cfg.dias_de_busca} dias{OFF}")
    hoje = datetime.now(timezone.utc).date()
    
    fav_data, favs_artists_data, playlist_data = await asyncio.gather(
        api.get_favorites(fav_type="albums",  limit=1_000),
        api.get_favorites(fav_type="artists", limit=500),
        obter_dados_das_playlists(api)
    )

    playlist_album_ids, playlist_album_titles = playlist_data
    fav_ids = {str(item.get("id")) for item in fav_data.get("favorites", {}).get("albums", {}).get("items", [])}
    fav_ids.update(playlist_album_ids)
    
    fav_titles = {_limpar_titulo(item.get("title", "")) for item in fav_data.get("favorites", {}).get("albums", {}).get("items", [])}
    fav_titles.update(playlist_album_titles)

    artistas = favs_artists_data.get("favorites", {}).get("artists", {}).get("items", [])
    
    if not artistas:
        print(f"\n{YELLOW}[!] Nenhum artista favorito encontrado na conta.{OFF}")
        await api.close()
        return
        
    contador = [0, len(artistas)]
    print() 
    
    sem = asyncio.Semaphore(cfg.max_concurrent)
    tarefas = [fetch_artist_latest_releases(api, str(a["id"]), a["name"], sem, cfg, contador) for a in artistas]
    
    resultados = await asyncio.gather(*tarefas)
    if sys.stdout.isatty(): print() 
    
    lista_plana = [item for sublist in resultados for item in sublist]
    
    unicos = {}
    for l in lista_plana:
        chave = f"{_limpar_titulo(l['artist'])}::{_limpar_titulo(l['title'])}"
        if chave not in unicos or (l.get("hires") and not unicos[chave].get("hires")):
            unicos[chave] = l
            
    lancamentos_brutos = sorted(list(unicos.values()), key=lambda x: (x["date"], x["artist"]), reverse=True)
    lancamentos_novos = [l for l in lancamentos_brutos if l["id"] not in fav_ids and _limpar_titulo(l["title"]) not in fav_titles]
    
    if not lancamentos_novos:
        print(f"\n{GREEN}[+] Caixa de Entrada Zerada! Nenhuma novidade pendente nos últimos {cfg.dias_de_busca} dias.{OFF}")
        await api.close()
        return
        
    print_separator()
    print(f"{GREEN}[+] {len(lancamentos_novos)} lançamentos encontrados (Ocultando o que já está na biblioteca)!{OFF}\n")
    
    labels, indices = montar_opcoes(lancamentos_novos, hoje)
        
    selected_raw = pick(
        labels, 
        "Selecione os lançamentos (ESPAÇO para marcar, ENTER para confirmar):\n(Linhas '──' são separadores)", 
        multiselect=True
    )
    
    selecionados_validos = [(label, indices[pick_idx]) for label, pick_idx in selected_raw if indices[pick_idx] >= 0]
    
    if selecionados_validos:
        # Puxa a lista de playlists uma única vez para não demorar
        try:
            pl_data = await api.get_user_playlists(limit=100) 
            user_playlists = pl_data.get("playlists", {}).get("items", []) or []
        except:
            user_playlists = []

        print_separator()
        for label, pick_idx in selecionados_validos:
            album = lancamentos_novos[pick_idx]
            album_nome = f"{album['artist']} - {album['title']}"
            
            resp = pick(
                ["1. Salvar nos Álbuns Favoritos", "2. Adicionar a uma Playlist", "3. Pular"],
                f"O que deseja fazer com:\n► {album_nome}?",
                multiselect=False
            )
            
            if "1." in resp[0]:
                await salvar_favorito(api, album)
            elif "2." in resp[0]:
                await salvar_playlist(api, album, user_playlists)
            else:
                print(f"{YELLOW}[*] Pulado: {album_nome}{OFF}")
    else:
        print(f"{YELLOW}[*] Nenhum álbum selecionado.{OFF}")
    
    await api.close()

def run_radar():
    try: asyncio.run(_async_run_radar())
    except KeyboardInterrupt: print(f"\n{YELLOW}Cancelado pelo usuário.{OFF}")