import asyncio
import aiohttp
import re
import sys
import os
import configparser
from pathlib import Path

from qobuz_dl.core import QobuzDL

class Tema:
    CYAN    = "\033[36m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    RED     = "\033[31m"
    PURPLE  = "\033[35m"
    BOLD    = "\033[1m"
    OFF     = "\033[0m"
    SYS     = f"{CYAN}[ANIME HUNTER]{OFF} ❯ "

async def fetch_anime_data(query: str):
    print(f"\n{Tema.SYS}Buscando dados no MyAnimeList para: {Tema.YELLOW}{query}{Tema.OFF}...")
    
    headers = {"User-Agent": "Mozilla/5.0"}
    
    async with aiohttp.ClientSession(headers=headers) as session:
        # 1. Procurar o ID do anime
        search_url = f"https://api.jikan.moe/v4/anime?q={query}&limit=1"
        async with session.get(search_url) as resp:
            if resp.status != 200:
                print(f"{Tema.RED}[!] Erro ao contactar a API do Jikan. Tente novamente.{Tema.OFF}")
                return None
            data = await resp.json()
            
            if not data.get("data"):
                print(f"{Tema.RED}[!] Nenhum anime encontrado com o nome '{query}'.{Tema.OFF}")
                return None
                
            anime_info = data["data"][0]
            mal_id = anime_info["mal_id"]
            titulo = anime_info["title"]
            
        # 2. Buscar as músicas (Themes) usando o ID exato
        print(f"{Tema.GREEN}✔ Anime encontrado:{Tema.OFF} {titulo} {Tema.CYAN}(ID: {mal_id}){Tema.OFF}")
        themes_url = f"https://api.jikan.moe/v4/anime/{mal_id}/themes"
        
        async with session.get(themes_url) as resp:
            if resp.status != 200:
                print(f"{Tema.RED}[!] Erro ao extrair as faixas deste anime.{Tema.OFF}")
                return None
            themes_data = await resp.json()
            
            return {
                "titulo": titulo,
                "openings": themes_data.get("data", {}).get("openings", []),
                "endings": themes_data.get("data", {}).get("endings", [])
            }

def clean_theme_string(theme_str: str) -> dict:
    """Extrai e limpa os dados da string bruta (ex: '1: "Otonoke (オトノケ)" by Creepy Nuts')"""
    # Regex para capturar o nome da música (entre aspas) e o artista (depois do "by")
    match = re.search(r'"([^"]+)".*?by\s+([^\(]+)', theme_str)
    
    if match:
        raw_song = match.group(1).strip()
        raw_artist = match.group(2).strip()
        
        # Removemos caracteres japoneses entre parêntesis do nome da música
        # A Qobuz encontra os ficheiros muito mais facilmente com os nomes em Romaji/Inglês
        clean_song = re.sub(r'\(.*?\)', '', raw_song).strip()
        clean_artist = raw_artist.split('feat.')[0].strip()
        
        return {
            "display": f"{clean_song} - {clean_artist}",
            "search_query": f"{clean_artist} {clean_song}"
        }
    return None

async def amain():
    # Como o cli.py já removeu a palavra 'anime' da lista, o nome do anime agora é a segunda palavra (índice 1)
    if len(sys.argv) < 2:
        print(f"{Tema.RED}Uso correto: python3 -m qobuz_dl anime \"Nome do Anime\"{Tema.OFF}")
        sys.exit(1)
        
    query = " ".join(sys.argv[1:])
    resultado = await fetch_anime_data(query)
    
    if not resultado:
        sys.exit(1)
        
    temas_processados = {}
    contador = 1
    
    print(f"\n{Tema.PURPLE}=== OPENINGS (Aberturas) ==={Tema.OFF}")
    for op in resultado["openings"]:
        parsed = clean_theme_string(op)
        if parsed:
            temas_processados[contador] = parsed["search_query"]
            print(f"  {Tema.CYAN}[{contador}]{Tema.OFF} 🎵 {parsed['display']}")
            contador += 1
            
    print(f"\n{Tema.PURPLE}=== ENDINGS (Encerramentos) ==={Tema.OFF}")
    for ed in resultado["endings"]:
        parsed = clean_theme_string(ed)
        if parsed:
            temas_processados[contador] = parsed["search_query"]
            print(f"  {Tema.CYAN}[{contador}]{Tema.OFF} 🎵 {parsed['display']}")
            contador += 1
            
    if not temas_processados:
        print(f"\n{Tema.YELLOW}[!] O MyAnimeList ainda não tem registo das músicas deste anime.{Tema.OFF}")
        sys.exit(0)
        
    print(f"\n{Tema.SYS}Quais faixas deseja baixar na Qobuz?")
    print(f"  {Tema.YELLOW}[Dica]{Tema.OFF} Digite os números separados por vírgula (ex: 1, 3) ou 'todas'.")
    escolha = input(f"{Tema.CYAN}❯ Escolha:{Tema.OFF} ").strip().lower()
    
    if not escolha:
        sys.exit(0)
        
    # Identificar pastas do iOS/Sistema para ler o config.ini
    OS_CONFIG = Path.home() / "Documents" if sys.platform == "ios" else (Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") if os.name == "nt" else Path.home() / ".config")
    CONFIG_FILE = OS_CONFIG / "qobuz-dl" / "config.ini"
    
    config = configparser.ConfigParser(interpolation=None)
    config.read(CONFIG_FILE)
    section = "qobuz" if config.has_section("qobuz") else "DEFAULT"
    
    # 1. Instanciamos o motor
    qobuz = QobuzDL(
        directory=config.get(section, "directory", fallback="Qobuz Downloads"),
        quality=config.get(section, "default_quality", fallback="7"),
        embed_art=config.getboolean(section, "embed_art", fallback=True)
    )
    
    # 2. O SEGREDO REVELADO: Guardamos o Token no "cofre" interno de configurações do motor
    token = config.get(section, "auth_token", fallback=config.get(section, "user_auth_token", fallback=""))
    qobuz.settings.user_auth_token = token

    # 3. Autenticamos! (O core.py agora vai ler o qobuz.settings e autorizar a entrada)
    await qobuz.initialize_client(
        email=config.get(section, "email", fallback=""),
        pwd=config.get(section, "password", fallback=""),
        app_id=config.get(section, "app_id", fallback=""),
        secrets=config.get(section, "secrets", fallback="").split(",")
    )

    app_id = config.get(section, "app_id", fallback="")
    
    # Processar escolhas do utilizador
    alvos = []
    if escolha == "todas":
        alvos = list(temas_processados.values())
    else:
        indices = [i.strip() for i in escolha.split(",") if i.strip().isdigit()]
        alvos = [temas_processados[int(i)] for i in indices if int(i) in temas_processados]

    print(f"\n{Tema.GREEN}Iniciando Motor de Download para {len(alvos)} faixa(s)...{Tema.OFF}")
    
        # 2. Busca e Download Inteligente usando o motor oficial autenticado
    for alvo in alvos:
        print(f"\n{Tema.SYS}Caçando: {Tema.BOLD}{alvo}{Tema.OFF}")
        
        try:
            # O motor interno (api_call) já injeta o Token e o App ID automaticamente!
            data = await qobuz.client.api_call("catalog/search", query=alvo, limit=1, type="tracks")
            items = data.get("tracks", {}).get("items", [])
            
            if items:
                track = items[0]
                track_id = track["id"]
                track_url = f"https://open.qobuz.com/track/{track_id}"
                
                # Extrai o nome do artista de forma segura
                artist_name = track.get("performer", {}).get("name", "Artista Desconhecido")
                if artist_name == "Artista Desconhecido" and "album" in track:
                    artist_name = track["album"].get("artist", {}).get("name", "Artista Desconhecido")
                    
                print(f"  {Tema.GREEN}✔ Encontrado na Qobuz:{Tema.OFF} {track.get('title', 'Desconhecido')} - {artist_name}\n")
                
                # Manda baixar a música!
                await qobuz.handle_url(track_url)
            else:
                print(f"  {Tema.RED}[!] Música não encontrada no catálogo da Qobuz com esse nome.{Tema.OFF}\n")
        except Exception as e:
            print(f"  {Tema.RED}[Erro] A Qobuz rejeitou a busca (Verifique a sua conexão): {e}{Tema.OFF}")

    # 3. Limpeza Final (Fecha as portas silenciosamente e resolve o aviso de "Unclosed session")
    if hasattr(qobuz, "client") and hasattr(qobuz.client, "session"):
        await qobuz.client.session.close()
