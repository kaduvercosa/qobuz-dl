import os
import re
import configparser
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from pick import pick

from qobuz_dl.qopy import Client
from qobuz_dl.color import GREEN, YELLOW, RED, CYAN, OFF

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("radar")


# ---------------------------------------------------------------------------
# Helpers de UI
# ---------------------------------------------------------------------------

def print_separator():
    print(f"\n{CYAN}{'='*60}{OFF}\n")


def _pluralizar(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _progresso(atual: int, total: int, nome: str) -> None:
    """Imprime linha de progresso sobrescrevendo a anterior."""
    pct  = int((atual / total) * 20)
    barra = f"[{'█' * pct}{'░' * (20 - pct)}]"
    linha = f"\r{CYAN}{barra} {atual}/{total}{OFF} {nome[:40]:<40}"
    print(linha, end="", flush=True)


# ---------------------------------------------------------------------------
# Configuração estendida
# ---------------------------------------------------------------------------

class RadarConfig:
    """Lê e valida todas as opções do config.ini relevantes ao radar."""

    def __init__(self, config: configparser.ConfigParser, section: str):
        self.dias_de_busca  = config.getint(section, "dias_de_busca",  fallback=7)
        self.max_concurrent = config.getint(section, "max_concurrent", fallback=10)

        # Filtro de tipo: "album", "ep", "single", "featured" ou combinações separadas por vírgula
        # Exemplo no config.ini:  tipos_radar = album, ep, single, featured
        # Deixar em branco = mostrar todos
        tipos_raw = config.get(section, "tipos_radar", fallback="").strip()
        if tipos_raw:
            self.tipos_filtro = {t.strip().lower() for t in tipos_raw.split(",")}
        else:
            self.tipos_filtro = set()  # vazio = sem filtro

        # Títulos a ignorar globalmente (substrings, case-insensitive)
        # Exemplo:  ignorar_titulos = karaoke, tribute, originally performed
        ignorar_raw = config.get(section, "ignorar_titulos", fallback="").strip()
        self.ignorar_titulos: List[str] = (
            [t.strip().lower() for t in ignorar_raw.split(",") if t.strip()]
            if ignorar_raw else []
        )


# ---------------------------------------------------------------------------
# Classificação de tipo de lançamento
# ---------------------------------------------------------------------------

def reconciliar_tipo(album: Dict) -> str:
    t_count  = album.get("tracks_count", 0)
    duration = album.get("duration", 0)
    raw_type = (album.get("release_type") or album.get("product_type") or "").lower()

    if "album"  in raw_type: return "Álbum"
    if "ep"     in raw_type: return "EP"
    if "single" in raw_type: return "Single"

    if t_count == 1:                           return "Single"
    if t_count <= 3 or (0 < duration < 1_740): return "EP"
    return "Álbum"


def _normalizar_titulo(titulo: str) -> str:
    titulo = (titulo or "").lower().strip()
    titulo = re.sub(r"[^\w\s]", "", titulo)
    titulo = re.sub(r"\s+", " ", titulo)
    return titulo


def _checar_papel(album: Dict, artist_id: str) -> Tuple[bool, str]:
    """
    Verifica se o artista participa do álbum e retorna (participa, papel).
    papel: "main" | "featured" | ""
    """
    artists_field = album.get("artists") or []

    if not artists_field:
        album_artist_id = str((album.get("artist") or {}).get("id") or "")
        if not album_artist_id or album_artist_id == artist_id:
            return True, "main"
        return False, ""

    for a in artists_field:
        if str(a.get("id") or "") != artist_id:
            continue
        roles_raw = " ".join(a.get("roles") or []).lower()
        if "main" in roles_raw:
            return True, "main"
        if "featured" in roles_raw or "feat" in roles_raw:
            return True, "featured"
        return True, "main"  # listado mas sem role explícito → main

    return False, ""


# ---------------------------------------------------------------------------
# Deduplicação global cross-artista
# ---------------------------------------------------------------------------

class DeduplicadorGlobal:
    """
    Detecta o mesmo lançamento aparecendo via artistas diferentes.

    Exemplo: "The Motto" de Tiësto ft. Ava Max pode aparecer tanto
    ao buscar Tiësto quanto ao buscar Ava Max. A chave usa o ID do
    álbum (que é único por lançamento, independente do artista buscado).
    """

    def __init__(self):
        self._ids_vistos:   set = set()
        self._chaves_vistas: set = set()

    def ja_visto_id(self, album_id) -> bool:
        if album_id in self._ids_vistos:
            return True
        self._ids_vistos.add(album_id)
        return False

    def ja_visto_chave(self, chave: str) -> bool:
        if chave in self._chaves_vistas:
            return True
        self._chaves_vistas.add(chave)
        return False


# ---------------------------------------------------------------------------
# Setup do cliente Qobuz
# ---------------------------------------------------------------------------

async def setup_client(config: configparser.ConfigParser, section: str) -> Client:
    app_id     = config.get(section, "app_id")
    secrets    = [s.strip() for s in config.get(section, "secrets").split(",") if s.strip()]
    auth_token = config.get(section, "auth_token", fallback="")
    email      = config.get(section, "email",      fallback="")
    pwd        = config.get(section, "password",   fallback="")

    api = Client(email, pwd, app_id=app_id, secrets=secrets, user_auth_token=auth_token)
    await api.start()
    return api


# ---------------------------------------------------------------------------
# Busca de lançamentos de um artista
# ---------------------------------------------------------------------------

async def fetch_artist_latest_releases(
    api:           Client,
    artist_id:     str,
    artist_name:   str,
    semaphore:     asyncio.Semaphore,
    cfg:           RadarConfig,
    dedup:         DeduplicadorGlobal,
    contador:      List[int],   # [atual, total] -- mutável para progresso
) -> List[Dict]:
    novidades:     List[Dict] = []
    chaves_locais: set        = set()   # dedup cross-região dentro do artista

    hoje          = datetime.now(timezone.utc).date()
    data_limite   = hoje - timedelta(days=cfg.dias_de_busca)
    limite_futuro = hoje + timedelta(days=1)

    async with semaphore:
        try:
            async for chunk in api.get_artist_meta(artist_id):
                if "albums" not in chunk:
                    continue

                for album in chunk.get("albums", {}).get("items", []):
                    album_id = album.get("id")

                    # Dedup global por ID (evita reprocessar mesmo objeto)
                    if dedup.ja_visto_id(album_id):
                        continue

                    # Papel do artista no lançamento
                    participa, papel = _checar_papel(album, artist_id)
                    if not participa:
                        continue

                    if (album.get("artist") or {}).get("name") == "Various Artists":
                        continue

                    if not album.get("streamable"):
                        continue

                    if "tracks_count" not in album and "release_type" not in album:
                        continue

                    # Filtro de títulos indesejados (config.ini: ignorar_titulos)
                    titulo_lower = (album.get("title") or "").lower()
                    if any(ig in titulo_lower for ig in cfg.ignorar_titulos):
                        continue

                    # Data de lançamento
                    data_str = str(
                        album.get("release_date_original")
                        or album.get("release_date")
                        or ""
                    )
                    match = re.search(r"\d{4}-\d{2}-\d{2}", data_str)
                    if not match:
                        continue

                    try:
                        data_lancamento = datetime.strptime(match.group(), "%Y-%m-%d").date()
                    except ValueError:
                        continue

                    if not (data_limite <= data_lancamento <= limite_futuro):
                        continue

                    tipo = reconciliar_tipo(album)

                    # Filtro de tipo (config.ini: tipos_radar)
                    if cfg.tipos_filtro:
                        tipo_chave = tipo.lower().replace("á", "a")  # "álbum" → "album"
                        papel_chave = papel  # "main" / "featured"
                        if tipo_chave not in cfg.tipos_filtro and papel_chave not in cfg.tipos_filtro:
                            continue

                    # Dedup cross-região local (mesmo título + artista buscado)
                    titulo_norm = _normalizar_titulo(album.get("title", ""))
                    chave_local = f"{artist_id}||{titulo_norm}"
                    if chave_local in chaves_locais:
                        continue
                    chaves_locais.add(chave_local)

                    # Dedup global cross-artista (mesmo álbum via artistas diferentes)
                    # Usa album_id real pois já foi marcado no dedup.ja_visto_id acima;
                    # aqui deduplica pela chave semântica título+data para o caso de
                    # edições regionais com IDs diferentes mas mesmo conteúdo
                    chave_global = f"global||{titulo_norm}||{match.group()}"
                    if dedup.ja_visto_chave(chave_global):
                        continue

                    novidades.append({
                        "id":           album_id,
                        "title":        album.get("title", "Unknown"),
                        "artist":       artist_name,
                        "album_artist": (album.get("artist") or {}).get("name", artist_name),
                        "type":         tipo,
                        "role":         papel,
                        "date":         match.group(),
                    })

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Erro ao buscar '%s' (id=%s): %s", artist_name, artist_id, exc)
        finally:
            # Atualiza progresso independente de sucesso ou erro
            contador[0] += 1
            _progresso(contador[0], contador[1], artist_name)

    return novidades


# ---------------------------------------------------------------------------
# Ordenação e agrupamento
# ---------------------------------------------------------------------------

def ordenar_lancamentos(lancamentos: List[Dict]) -> List[Dict]:
    return sorted(
        lancamentos,
        key=lambda x: (x["date"], x["artist"], x["title"]),
        reverse=True,
    )


def agrupar_por_artista(lancamentos: List[Dict]) -> Dict[str, List[Dict]]:
    grupos: Dict[str, List[Dict]] = {}
    for l in lancamentos:
        grupos.setdefault(l["artist"], []).append(l)
    return grupos


# ---------------------------------------------------------------------------
# Montagem das opções para o pick
# ---------------------------------------------------------------------------

def montar_opcoes(
    lancamentos: List[Dict],
    fav_ids:     set,
) -> Tuple[List[str], List[int]]:
    grupos  = agrupar_por_artista(lancamentos)
    labels:  List[str] = []
    indices: List[int] = []

    idx_map = {i: l for i, l in enumerate(lancamentos)}

    for artista, items in grupos.items():
        labels.append(f"── {artista} {'─' * max(0, 35 - len(artista))}")
        indices.append(-1)

        for item in items:
            idx    = next(i for i, l in idx_map.items() if l is item)
            ja_fav = " ★" if str(item["id"]) in fav_ids else ""

            if item["role"] == "featured":
                label = (
                    f"  [feat] {item['album_artist']} - {item['title']} "
                    f"ft. {item['artist']} ({item['date']}){ja_fav}"
                )
            else:
                label = (
                    f"  [{item['type']}] {item['artist']} - {item['title']} "
                    f"({item['date']}){ja_fav}"
                )

            labels.append(label)
            indices.append(idx)

    return labels, indices


# ---------------------------------------------------------------------------
# Adição de favoritos
# ---------------------------------------------------------------------------

async def adicionar_favoritos(
    api:          Client,
    selecionados: List[tuple],
    todos:        List[Dict],
    fav_ids:      set,
) -> None:
    for item_label, index in selecionados:
        album    = todos[index]
        album_id = str(album["id"])

        if album_id in fav_ids:
            print(f"{YELLOW} [!] Já é favorito: {item_label}{OFF}")
            continue

        try:
            await api.add_favorite_album(album_id)
            print(f"{GREEN} [+] Adicionado: {item_label}{OFF}")
            fav_ids.add(album_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Erro ao adicionar '%s': %s", item_label, exc)
            print(f"{RED} [-] Erro ao adicionar: {item_label}{OFF}")


# ---------------------------------------------------------------------------
# Fluxo principal
# ---------------------------------------------------------------------------

async def _async_run_radar() -> None:
    if os.name == "nt":
        base_path = Path(os.getenv("APPDATA", ""))
    else:
        base_path = Path(os.getenv("HOME", str(Path.home()))) / ".config"

    config_path = base_path / "qobuz-dl" / "config.ini"
    config = configparser.ConfigParser()
    config.read(config_path)

    if not config.sections():
        print(f"{RED}[!] Config não encontrado: {config_path}{OFF}")
        return

    section = config.sections()[0]
    cfg     = RadarConfig(config, section)

    api = await setup_client(config, section)

    try:
        print(
            f"{CYAN}[*] Sincronizando -- verificando novidades "
            f"dos últimos {_pluralizar(cfg.dias_de_busca, 'dia', 'dias')}...{OFF}"
        )
        if cfg.tipos_filtro:
            print(f"{CYAN}[*] Filtro de tipo ativo: {', '.join(sorted(cfg.tipos_filtro))}{OFF}")

        fav_data, favs_artists_data = await asyncio.gather(
            api.get_favorites(fav_type="albums",  limit=1_000),
            api.get_favorites(fav_type="artists", limit=500),
        )

        fav_ids = {
            str(item.get("id"))
            for item in fav_data.get("favorites", {}).get("albums", {}).get("items", [])
        }

        artistas = favs_artists_data.get("favorites", {}).get("artists", {}).get("items", [])

        if not artistas:
            print(f"{YELLOW}[!] Nenhum artista favorito encontrado.{OFF}")
            return

        total    = len(artistas)
        contador = [0, total]   # [atual, total]
        dedup    = DeduplicadorGlobal()

        print(f"{CYAN}[*] Verificando {_pluralizar(total, 'artista', 'artistas')}...{OFF}\n")

        semaphore = asyncio.Semaphore(cfg.max_concurrent)
        tarefas   = [
            fetch_artist_latest_releases(
                api, str(a.get("id")), a.get("name", "Unknown"),
                semaphore, cfg, dedup, contador,
            )
            for a in artistas
        ]
        resultados = await asyncio.gather(*tarefas)

        # Quebra de linha após a barra de progresso
        print()

        todos_lancamentos = ordenar_lancamentos(
            [item for sublist in resultados for item in sublist]
        )

        if not todos_lancamentos:
            print(f"\n{YELLOW}[!] Sem novidades nos últimos {_pluralizar(cfg.dias_de_busca, 'dia', 'dias')}.{OFF}")
            return

        labels, indices = montar_opcoes(todos_lancamentos, fav_ids)

        print_separator()
        total_items = sum(1 for i in indices if i >= 0)
        print(f"{CYAN}[*] {_pluralizar(total_items, 'lançamento encontrado', 'lançamentos encontrados')}{OFF}")

        selected_raw = pick(
            labels,
            "Seleciona os lançamentos para adicionar aos favoritos:\n"
            "(★ = já favoritado  |  ESPAÇO = selecionar  |  ENTER = confirmar)",
            multiselect=True,
            options_map_func=lambda o: o,
        )

        if not selected_raw:
            print(f"\n{YELLOW}[*] Nenhum lançamento selecionado.{OFF}")
            return

        selecionados_validos = [
            (label, indices[pick_idx])
            for label, pick_idx in selected_raw
            if indices[pick_idx] >= 0
        ]

        if not selecionados_validos:
            print(f"\n{YELLOW}[*] Nenhum lançamento válido selecionado.{OFF}")
            return

        await adicionar_favoritos(api, selecionados_validos, todos_lancamentos, fav_ids)

    except (KeyboardInterrupt, asyncio.CancelledError):
        print(f"\n{YELLOW}[!] Operação cancelada pelo usuário.{OFF}")
        raise

    finally:
        await api.close()
        print_separator()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_radar() -> None:
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(_async_run_radar())
    else:
        loop.run_until_complete(_async_run_radar())