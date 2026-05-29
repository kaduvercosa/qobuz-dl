import logging
import aiohttp
from bs4 import BeautifulSoup
from typing import List, Dict

from qobuz_dl.color import OFF, GREEN, RED, YELLOW, CYAN

# Inicializamos o logger para manter a consistência com o resto do projeto
logger = logging.getLogger(__name__)

async def fetch_lastfm_playlist(url: str) -> List[Dict[str, str]]:
    """
    Extrai as faixas (artista e título) de um URL de uma playlist do Last.fm.
    
    Retorna:
        Uma lista de dicionários no formato: [{'artist': 'Nome', 'title': 'Música'}]
    """
    logger.info(f"{CYAN}[*] Analyzing Last.fm playlist...{OFF}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        # A forma correta e recomendada pelo aiohttp para definir timeouts
        timeout = aiohttp.ClientTimeout(total=15)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                text = await response.text()
                
    except aiohttp.ClientError as e:
        # Captura especificamente erros de rede (ex: site em baixo, sem internet)
        logger.error(f"{RED}[!] Failed to connect to Last.fm: {e}{OFF}")
        return []
    except Exception as e:
        # Captura outros erros inesperados
        logger.error(f"{RED}[!] Unexpected error fetching Last.fm: {e}{OFF}")
        return []

    # Analisa o conteúdo HTML da página
    soup = BeautifulSoup(text, 'html.parser')
    tracks = []
    
    # Localiza todas as linhas da tabela que contêm as faixas
    rows = soup.find_all('tr', class_='chartlist-row')
    
    for row in rows:
        artist_tag = row.find('td', class_='chartlist-artist')
        title_tag = row.find('td', class_='chartlist-name')
        
        if artist_tag and title_tag:
            # Limpa espaços em branco e quebras de linha com strip=True
            artist = artist_tag.get_text(strip=True)
            title = title_tag.get_text(strip=True)
            
            # Validação extra: garante que não adicionamos entradas vazias
            if artist and title:
                tracks.append({"artist": artist, "title": title})
            
    if not tracks:
        logger.warning(f"{YELLOW}[!] No tracks found. The playlist might be empty or Last.fm changed their layout.{OFF}")
    else:
        logger.info(f"{GREEN}[+] Successfully extracted {len(tracks)} tracks from Last.fm!{OFF}")
        
    return tracks