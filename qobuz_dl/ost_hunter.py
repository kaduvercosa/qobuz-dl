import os
import re
import json
import configparser
import asyncio
import sys
import unicodedata
import warnings
import logging
import aiohttp
from pathlib import Path
from typing import List, Dict, Tuple, Set, Any
from pick import pick

# --- CALANDO OS AVISOS CHATOS DO AIOHTTP ---
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
logging.getLogger("aiohttp.client").setLevel(logging.CRITICAL)

from qobuz_dl.qopy import Client
from qobuz_dl.core import QobuzDL
from qobuz_dl.color import GREEN, YELLOW, CYAN, OFF, RED, BLUE

# ==============================================================================
# 🧩 HELPERS GERAIS E FORMATAÇÃO
# ==============================================================================
def _safe_get(d: dict, *keys, default=None):
    res = default
    for key in keys:
        if not isinstance(d, dict): return default
        res = d.get(key, default)
        if res is None: return default
        d = res
    return res

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

def formatar_nota(score: Any) -> str:
    try:
        return f"{float(score):.2f}"
    except (ValueError, TypeError):
        return "N/A "

def obter_titulo_localizado(anime_data: dict) -> str:
    titulos_alternativos = anime_data.get("titles", [])
    for t in titulos_alternativos:
        if t.get("type") in ["Portuguese", "Portuguese (BR)", "Brazilian Portuguese"]:
            return t.get("title")
    eng = anime_data.get("title_english")
    if eng: return eng
    return anime_data.get("title", "Unknown")

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

# ==============================================================================
# 📺 INTEGRAÇÃO COM A API DO JIKAN (MYANIMELIST) E EXPORTAÇÃO JSON
# ==============================================================================
async def consultar_jikan_api(endpoint: str, params: dict = None) -> List[Dict]:
    url = f"https://api.jikan.moe/v4/{endpoint}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, params=params, timeout=10) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("data", [])
                elif r.status == 429:
                    print(f"\n{RED}[!] O MyAnimeList pediu para esperar (Muitas requisições). Aguarde uns segundos.{OFF}")
                    return []
                else:
                    print(f"\n{RED}[!] A API recusou a conexão (Erro HTTP {r.status}).{OFF}")
                    return []
    except Exception as e:
        print(f"\n{RED}[!] Falha na conexão com a API do Jikan: {e}{OFF}")
        return []

def gerar_json_anime(anime_data: Dict, pasta_destino: Path) -> None:
    """Gera o JSON na pasta específica do Anime, junto com os downloads."""
    titulo_pt = obter_titulo_localizado(anime_data)
    titulo_limpo = re.sub(r'[\\/*?:"<>|]', "", titulo_pt)
    filename = f"{titulo_limpo} - Metadata.json"
    
    pasta_destino.mkdir(parents=True, exist_ok=True)
    filepath = pasta_destino / filename
    
    payload = {
        "title_localized": titulo_pt,
        "title_romaji": anime_data.get("title"),
        "title_english": anime_data.get("title_english"),
        "title_japanese": anime_data.get("title_japanese"),
        "type": anime_data.get("type"),
        "episodes": anime_data.get("episodes"),
        "status": anime_data.get("status"),
        "score": formatar_nota(anime_data.get("score")),
        "year": anime_data.get("year"),
        "season": anime_data.get("season"),
        "studios": [s.get("name") for s in anime_data.get("studios", [])],
        "genres": [g.get("name") for g in anime_data.get("genres", [])],
        "synopsis": anime_data.get("synopsis"),
        "cover_url_hq": _safe_get(anime_data, "images", "jpg", "large_image_url"),
        "mal_url": anime_data.get("url")
    }
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        print(f"{GREEN}[+] Metadata do anime exportada: {filepath}{OFF}")
    except Exception as e:
        print(f"{RED}[-] Erro ao salvar o JSON: {e}{OFF}")

# ==============================================================================
# 🎵 INTEGRAÇÃO QOBUZ E DOWNLOAD
# ==============================================================================
async def obter_dados_de_duplicados(api: Client) -> Tuple[Set[str], Set[str]]:
    album_ids, album_titles = set(), set()
    try:
        fav_data = await api.get_favorites(fav_type="albums", limit=100)
        items = _safe_get(fav_data, "favorites", "albums", "items") or _safe_get(fav_data, "albums", "items") or []
        for p in items:
            album_ids.add(str(p["id"]))
            album_titles.add(_limpar_titulo_para_comparacao(p.get("title", "")))
    except Exception: pass
    return album_ids, album_titles

async def salvar_favorito(api: Client, album: Dict) -> None:
    artista = _safe_get(album, "artist", "name", default="Unknown")
    try:
        await api.add_favorite_album(album["id"])
        print(f"{GREEN}[+] Salvo nos favoritos: {artista} - {album['title']}{OFF}")
    except Exception as e:
        print(f"{RED}[-] Erro ao salvar {album['title']}: {e}{OFF}")

async def baixar_album(api: Client, album_id: str, diretorio: str, qualidade: int) -> None:
    # [!] O QobuzDL agora recebe o diretório específico do Anime em vez do geral
    print(f"\n{CYAN}[*] Inicializando motor de download (QobuzDL)...{OFF}")
    qdl = QobuzDL(directory=diretorio, quality=qualidade)
    qdl.client = api 
    await qdl.download_from_id(album_id, album=True)

async def salvar_playlist(api: Client, album: Dict, playlists: List[Dict], query: str) -> None:
    album_id = str(album["id"])
    artista = _safe_get(album, "artist", "name", default="Unknown")
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

    selecao_pl = pick(opcoes_menu, f"Destino para: {album_nome}\nEscolha a playlist (ENTER = confirmar):", multiselect=False)
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
        playlist_escolhida = playlists[pl_index - offset]
        playlist_id = str(playlist_escolhida["id"])
    
    print(f"{CYAN}[*] Puxando faixas de '{album_nome}'...{OFF}")
    track_ids = []
    try:
        album_data = await api.get_album_meta(album_id)
        for f in _safe_get(album_data, "tracks", "items", default=[]):
            track_ids.append(str(f["id"]))
    except Exception as e:
        print(f"{RED}[-] Erro ao ler faixas: {e}{OFF}")
        return

    if not track_ids: return

    try:
        for i in range(0, len(track_ids), 50):
            await api.add_playlist_tracks(playlist_id, ",".join(track_ids[i : i + 50]))
            await asyncio.sleep(0.5) 
        print(f"{GREEN}[+] Adicionado à '{playlist_escolhida['name']}': {album_nome}{OFF}")
        playlist_escolhida["tracks_count"] = playlist_escolhida.get("tracks_count", 0) + len(track_ids)
    except Exception as e:
        print(f"{RED}[-] Erro ao injetar músicas: {e}{OFF}")

# ==============================================================================
# 🚀 CORE DO PROGRAMA
# ==============================================================================
async def amain():
    config = configparser.ConfigParser()
    config_path = Path(os.getenv("HOME", Path.home())) / ".config" / "qobuz-dl" / "config.ini"
    config.read(config_path)
    sec = config.sections()[0]
    
    diretorio_base = config.get(sec, "directory", fallback="QobuzDownloads")
    qualidade_base = int(config.get(sec, "quality", fallback="6"))
    
    api = await setup_client(config, sec)
    
    while True:
        os.system('clear' if os.name == 'posix' else 'cls')
        print(f"{BLUE}============================================================{OFF}")
        print(f"{BLUE}            OST HUNTER - ANIME DATABASE SYSTEM              {OFF}")
        print(f"{BLUE}============================================================{OFF}")
        
        escolha = pick(
            ["1. Ver Animes da Temporada Atual", "2. Pesquisar Anime por Nome", "3. Sair do Sistema"],
            "O que você deseja fazer?",
            multiselect=False
        )[0]

        animes_encontrados = []
        if "3." in escolha:
            print(f"{CYAN}[*] Encerrando o sistema...{OFF}")
            break
            
        elif "1." in escolha:
            print(f"\n{CYAN}[*] Baixando a lista da temporada do Japão...{OFF}")
            animes_encontrados = await consultar_jikan_api("seasons/now", {"limit": 25})
            
        elif "2." in escolha:
            query = input(f"\n{YELLOW}Digite o nome do Anime: {OFF}").strip()
            if not query: continue
            print(f"\n{CYAN}[*] Pesquisando '{query}' no banco de dados MyAnimeList...{OFF}")
            animes_encontrados = await consultar_jikan_api("anime", {"q": query, "order_by": "popularity", "sort": "desc", "limit": 15})

        if not animes_encontrados:
            print(f"{RED}[!] Nenhum anime encontrado. Tente pesquisar com outro nome.{OFF}")
            await asyncio.sleep(2)
            continue

        # -------------------------------------------------------------
        # UI: TABELA DOS ANIMES (Design Flat, Sem Emojis, Alinhamento Perfeito)
        # -------------------------------------------------------------
        # Offset de 2 espaços para casar com o prefixo "* " do pick de escolha única
        cabecalho_anime = f"  {'TÍTULO'.ljust(45)}  {'NOTA'.ljust(6)}  {'TIPO'.ljust(5)}  {'ANO'.ljust(4)}\n" \
                          f"  {'-'*45}  {'-'*6}  {'-'*5}  {'-'*4}"
        opcoes_anime = []
        
        for a in animes_encontrados:
            titulo = _truncar(obter_titulo_localizado(a), 45)
            score = formatar_nota(a.get("score"))
            tipo = str(a.get("type", "TV")).ljust(5)
            ano = str(a.get("year", "N/A")).ljust(4)
            
            opcoes_anime.append(f"{titulo:<45}  {score:>6}  {tipo:<5}  {ano:<4}")
            
        opcoes_anime.append("<< Voltar ao Menu Principal")
        
        anime_idx = pick(
            opcoes_anime, 
            f"Selecione a Obra Desejada (Enter = Confirmar):\n\n{cabecalho_anime}", 
            multiselect=False
        )[1]
        
        if anime_idx == len(animes_encontrados):
            continue
            
        anime_selecionado = animes_encontrados[anime_idx]
        t_ptbr = obter_titulo_localizado(anime_selecionado)
        t_romaji = anime_selecionado.get("title", "")
        t_ingles = anime_selecionado.get("title_english", "")
        
        print(f"\n{CYAN}[*] Obra selecionada: {t_ptbr}{OFF}")
        print(f"{CYAN}[*] Iniciando varredura profunda no Qobuz...{OFF}")
        
        termos_busca = set([t for t in [t_romaji, t_ingles, t_ptbr] if t and len(t) > 2])
        tarefas_qobuz = []
        
        for termo in termos_busca:
            tarefas_qobuz.append(api.api_call("catalog/search", query=f"{termo} soundtrack", limit=30, type="albums"))
            tarefas_qobuz.append(api.api_call("catalog/search", query=termo, limit=30, type="albums"))

        resultados = await asyncio.gather(*tarefas_qobuz)
        
        albums_brutos = []
        for res in resultados:
            albums_brutos.extend(_safe_get(res, "albums", "items", default=[]))

        print(f"{CYAN}[*] O Qobuz retornou {len(albums_brutos)} resultados brutos. Filtrando o lixo...{OFF}")

        termos_limpos = [normalizar_texto(t) for t in termos_busca]
        
        unicos = {}
        for item in albums_brutos:
            album_id = str(item.get("id"))
            if not album_id or album_id in unicos: continue
                
            title_norm = normalizar_texto(item.get("title", ""))
            artist_norm = normalizar_texto(_safe_get(item, "artist", "name", default=""))
            
            matches_anime = any(t in title_norm or t in artist_norm for t in termos_limpos)
            is_ost_explicit = any(kw in title_norm for kw in ["soundtrack", "ost", "score", "theme", "opening", "ending", "vocal", "character song"])
            is_trash = any(kw in title_norm for kw in ["cover", "tribute", "karaoke", "lullaby", "8-bit", "piano version", "relaxing", "music box"])
            
            if (matches_anime or is_ost_explicit) and not is_trash:
                unicos[album_id] = item
                
        todos_osts = list(unicos.values())
        
        if not todos_osts:
            print(f"\n{RED}[!] Nenhuma trilha oficial encontrada no Qobuz para essa obra.{OFF}")
            print(f"{YELLOW}Motivos comuns:{OFF}")
            print(f"{YELLOW}1. Obras recém anunciadas (ex: 2025/2026) ainda não possuem músicas publicadas.{OFF}")
            print(f"{YELLOW}2. O catálogo japonês do Qobuz (França) possui lacunas comparado à Apple/Spotify.{OFF}")
            await asyncio.sleep(4)
            continue
            
        fav_ids, fav_titles = await obter_dados_de_duplicados(api)
        
        # -------------------------------------------------------------
        # UI: TABELA DAS OSTS (Design Flat, Sem Emojis)
        # -------------------------------------------------------------
        # Offset de 4 espaços para casar com o prefixo "[ ] " do pick de múltipla escolha
        cabecalho_ost = f"    {'DB'.ljust(3)}  {'TIPO'.ljust(4)}  {'ARTISTA PRINCIPAL'.ljust(25)}  {'NOME DO ÁLBUM'.ljust(45)}\n" \
                        f"    {'-'*3}  {'-'*4}  {'-'*25}  {'-'*45}"
        labels, validos = [], []
        
        for item in todos_osts:
            is_dup = str(item.get("id")) in fav_ids or _limpar_titulo_para_comparacao(item.get("title", "")) in fav_titles
            tipo = classificar_tipo_lancamento(item.get("release_type", ""), item.get("title", ""), item.get("tracks_count", 0), item.get("duration", 0))
            
            artist_name = _truncar(_safe_get(item, "artist", "name", default="Unknown"), 25)
            titulo = _truncar(item.get('title', ''), 45)
            tipo_str = tipo.upper()[:4]
            status = "SIM" if is_dup else "---"
            
            labels.append(f"{status:^3}  {tipo_str:<4}  {artist_name:<25}  {titulo:<45}")
            validos.append(item)

        selecoes = pick(labels, f"OSTs de '{t_ptbr}' no Qobuz\n(Espaço p/ marcar, Enter p/ confirmar):\n\n{cabecalho_ost}", multiselect=True)
            
        if selecoes:
            try:
                pl_data = await api.get_user_playlists(limit=100) 
                user_playlists = pl_data.get("playlists", {}).get("items", []) or []
            except:
                user_playlists = []

            # Cria o caminho da subpasta com o nome do Anime Limpo (Removendo caracteres inválidos para pastas)
            nome_pasta_anime = re.sub(r'[\\/*?:"<>|]', "", t_ptbr)
            pasta_destino_downloads = Path(diretorio_base) / nome_pasta_anime

            for item_label, index in selecoes:
                album = validos[index]
                album_nome = f"{_safe_get(album, 'artist', 'name', default='Unknown')} - {album['title']}"

                if "SIM " in item_label:
                    print(f"{YELLOW}[!] Aviso de duplicado (Já salvo): {album_nome}{OFF}")

                resp = pick(
                    [
                        "1. Baixar Imediatamente (QobuzDL)", 
                        "2. Salvar nos Álbuns Favoritos", 
                        "3. Adicionar a uma Playlist", 
                        "4. Pular"
                    ],
                    f"O que deseja fazer com:\n► {album_nome}",
                    multiselect=False
                )
                
                if "1." in resp[0]:
                    # Agora envia a pasta do anime para o QobuzDL!
                    await baixar_album(api, str(album["id"]), str(pasta_destino_downloads), qualidade_base)
                elif "2." in resp[0]:
                    await salvar_favorito(api, album)
                elif "3." in resp[0]:
                    await salvar_playlist(api, album, user_playlists, t_ptbr)

            # Gera o JSON na mesma pasta onde a música foi salva
            gerar_json_anime(anime_selecionado, pasta_destino_downloads)
            
        print(f"\n{YELLOW}[*] Pressione ENTER para voltar ao menu principal...{OFF}")
        input()

    await api.close()

if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print(f"\n{RED}[!] Sistema interrompido. (CTRL+C){OFF}")
        sys.exit(0)