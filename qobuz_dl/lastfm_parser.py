import logging
import asyncio
import aiohttp
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from typing import List, Dict

from qobuz_dl.color import OFF, GREEN, RED, YELLOW, CYAN

# Inicializamos o logger para manter a consistência com o resto do projeto
logger = logging.getLogger(__name__)


async def fetch_lastfm_playlist(url: str, max_retries: int = 3) -> List[Dict[str, str]]:
    """
    Extrai as faixas (artista, título e álbum) de uma ou mais páginas do Last.fm.
    
    Retorna:
        Uma lista de dicionários no formato: [{'artist': 'Nome', 'title': 'Música', 'album': 'Álbum'}]
    """
    # 1. Validação de Entrada (URL Guardrail)
    if "last.fm" not in url.lower():
        logger.error(f"{RED}[!] URL inválida. Forneça um link válido do Last.fm.{OFF}")
        return []

    logger.info(f"{CYAN}[*] Analyzing Last.fm playlist (Suporte a paginação ativado)...{OFF}")

async def fetch_lastfm_playlist(url: str) -> List[Dict[str, str]]:
    """
    Extrai as faixas (artista e título) de um URL de uma playlist do Last.fm.
    
    Retorna:
        Uma lista de dicionários no formato: [{'artist': 'Nome', 'title': 'Música'}]
    """
    logger.info(f"{CYAN}[*] Analyzing Last.fm playlist...{OFF}")

    
    # 2. Camuflagem de Headers Mais Robusta
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
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
    current_url = url
    page_count = 1
    
    timeout = aiohttp.ClientTimeout(total=20)
    
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        # 3. Suporte a Paginação (Loop While)
        while current_url:
            html_content = None
            
            # 4. Sistema de Retentativas (Retry / Backoff)
            for attempt in range(1, max_retries + 1):
                try:
                    async with session.get(current_url) as response:
                        response.raise_for_status()
                        html_content = await response.text()
                        break  # Se deu certo, quebra o loop de tentativas e continua a extração
                        
                except aiohttp.ClientError as e:
                    logger.warning(f"{YELLOW}[!] Falha na rede (Tentativa {attempt}/{max_retries}): {e}{OFF}")
                    if attempt == max_retries:
                        logger.error(f"{RED}[!] Falha definitiva ao acessar Last.fm após {max_retries} tentativas.{OFF}")
                        return tracks
                    
                    # Espera progressiva: 2s na primeira falha, 4s na segunda...
                    await asyncio.sleep(2 * attempt)
                except Exception as e:
                    logger.error(f"{RED}[!] Erro inesperado: {e}{OFF}")
                    return tracks
            
            # Se não conseguiu baixar o HTML após as tentativas, encerra a busca
            if not html_content:
                break
                
            # Analisa o conteúdo HTML da página
            soup = BeautifulSoup(html_content, 'html.parser')
            rows = soup.find_all('tr', class_='chartlist-row')
            
            if not rows:
                break  # Fim da lista ou página vazia
                
            for row in rows:
                artist_tag = row.find('td', class_='chartlist-artist')
                title_tag = row.find('td', class_='chartlist-name')
                
                # 5. Extração de Mais Metadados (Tenta capturar o álbum, se existir)
                album_tag = row.find('td', class_='chartlist-album')
                
                if artist_tag and title_tag:
                    # Limpa espaços em branco e quebras de linha com strip=True
                    artist = artist_tag.get_text(strip=True)
                    title = title_tag.get_text(strip=True)
                    album = album_tag.get_text(strip=True) if album_tag else None
                    
                    # Validação extra: garante que não adicionamos entradas vazias
                    if artist and title:
                        tracks.append({
                            "artist": artist, 
                            "title": title, 
                            "album": album
                        })
            
            # Verifica se existe uma próxima página (Paginação Last.fm)
            next_button = soup.find('li', class_='pagination-next')
            if next_button:
                next_link = next_button.find('a', href=True)
                if next_link:
                    # Une o domínio base com o link relativo (ex: ?page=2)
                    current_url = urljoin(current_url, next_link['href'])
                    page_count += 1
                    logger.info(f"{CYAN}  -> Extraindo página {page_count}...{OFF}")
                    
                    # Pausa educada para não agir como ataque DDoS no Last.fm
                    await asyncio.sleep(1)
                    continue
            
            # Se não encontrar o botão "Next", define URL como None para quebrar o loop While
            current_url = None

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
            
    # Resumo Final
    if not tracks:
        logger.warning(f"{YELLOW}[!] No tracks found. The playlist might be empty or Last.fm changed their layout.{OFF}")
    else:

        logger.info(f"{GREEN}[+] Successfully extracted {len(tracks)} tracks across {page_count} page(s) from Last.fm!{OFF}")

        logger.info(f"{GREEN}[+] Successfully extracted {len(tracks)} tracks from Last.fm!{OFF}")
        
    return tracks