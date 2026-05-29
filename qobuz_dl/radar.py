import os
import re
import configparser
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from pick import pick

from qobuz_dl.qopy import Client
from qobuz_dl.color import GREEN, YELLOW, RED, CYAN, OFF
from qobuz_dl.core import classificar_tipo_lancamento

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
# Helpers de UI & Formatação
# ---------------------------------------------------------------------------

def print_separator() -> None:
    print(f"\n{CYAN}{'='*75}{OFF}\n")


def _pluralizar(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _data_relativa(data_str: str, hoje: "datetime.date") -> str:
    """Converte YYYY-MM-DD em texto relativo legível."""
    try:
        data  = datetime.strptime(data_str, "%Y-%m-%d").date()
        delta = (hoje - data).days
    except ValueError:
        return data_str

    if delta == 0:  return "hoje"
    if delta == 1:  return "ontem"
    if delta <= 6:  return f"há {delta} dias"
    if delta <= 13: return "há 1 sem"
    if delta <= 20: return "há 2 sem"
    if delta <= 27: return "há 3 sem"
    return f"há {delta} dias"


def _progresso(atual: int, total: int, nome: str) -> None:
    """Barra de progresso -- silenciosa quando stdout não é TTY."""
    if not sys.stdout.isatty():
        return
    pct   = int((atual / total) * 20)
    barra = f"[{'█' * pct}{'░' * (20 - pct)}]"
    print(f"\r{CYAN}{barra} {atual}/{total}{OFF} {nome[:40]:<40}", end="", flush=True)


def _truncar(texto: str, limite: int) -> str:
    """Trunca textos muito longos para manter o alinhamento da tabela."""
    return texto if len(texto) <= limite else texto[:limite - 3] + "..."


# ---------------------------------------------------------------------------
# Configuração estendida
# ---------------------------------------------------------------------------

class RadarConfig:
    _TIPO_ALIASES: Dict[str, str] = {
        "album": "album", "álbum": "album", "albun": "album",
        "ep": "ep",
        "single": "single",
        "featured": "featured", "feat": "featured",
        "live": "live",
        "compilation": "compilation", "compilação": "compilation",
    }

    def __init__(self, config: configparser.ConfigParser, section: str):
        self.dias_de_busca  = config.getint(section, "dias_de_busca",  fallback=7)
        self.max_concurrent = config.getint(section, "max_concurrent", fallback=10)

        tipos_raw = config.get(section, "tipos_radar", fallback="").strip()
        self.tipos_filtro: Set[str] = set()
        if tipos_raw:
            for t in tipos_raw.split(","):
                alias = self._TIPO_ALIASES.get(t.strip().lower())
                if alias:
                    self.tipos_filtro.add(alias)

        ignorar_raw = config.get(section, "ignorar_titulos", fallback="").strip()
        self.ignorar_titulos: List[str] = (
            [t.strip().lower() for t in ignorar_raw.split(",") if t.strip()]
            if ignorar_raw else []
        )

    def tipo_permitido(self, tipo: str, papel: str) -> bool:
        if not self.tipos_filtro:
            return True
        tipo_key = self._TIPO_ALIASES.get(tipo.lower(), tipo.lower())
        return tipo_key in self.tipos_filtro or papel in self.tipos_filtro


# ---------------------------------------------------------------------------
# Checagem de papel do artista
# ---------------------------------------------------------------------------

def _checar_papel(album: Dict, artist_id: str) -> Tuple[bool, str]:
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
        if "main"     in roles_raw: return True, "main"
        if "featured" in roles_raw: return True, "featured"
        if "feat"     in roles_raw: return True, "featured"
        return True, "main"

    return False, ""


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
    api:         Client,
    artist_id:   str,
    artist_name: str,
    semaphore:   asyncio.Semaphore,
    cfg:         RadarConfig,
    contador:    List[int],
) -> List[Dict]:
    novidades:  List[Dict] = []
    ids_locais: Set        = set()

    hoje          = datetime.now(timezone.utc).date()
    data_limite   = hoje - timedelta(days=cfg.dias_de_busca)
    limite_futuro = hoje + timedelta(days=1)

    async with semaphore:
        try:
            async for chunk in api.get_artist_meta(artist_id):
                
                # Varre todas as possíveis gavetas que a API do Qobuz usa
                categorias_api = ["albums", "singles", "eps", "appears_on", "featured_in"]
                
                for categoria in categorias_api:
                    for album in chunk.get(categoria, {}).get("items", []):
                        album_id = album.get("id")

                        if album_id in ids_locais:
                            continue
                        ids_locais.add(album_id)

                        participa, papel = _checar_papel(album, artist_id)
                        if not participa:
                            continue

                        if not album.get("streamable"):
                            continue

                        if "tracks_count" not in album and "release_type" not in album:
                            continue

                        titulo_lower = (album.get("title") or "").lower()
                        if any(ig in titulo_lower for ig in cfg.ignorar_titulos):
                            continue

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

                        tipo_raw = classificar_tipo_lancamento(
                            raw_type=album.get("release_type") or album.get("product_type"),
                            title=str(album.get("title", "")),
                            version=str(album.get("version", "")),
                            t_count=album.get("tracks_count", 0),
                            duration=album.get("duration", 0),
                        )
                        
                        # Se for um Various Artists, forçamos o tipo para "VA / Coletânea" visualmente
                        is_va = (album.get("artist") or {}).get("name") == "Various Artists"
                        if is_va:
                            tipo_display = "VA / Coletânea"
                        else:
                            tipo_display = {"album": "Álbum", "ep": "EP"}.get(tipo_raw, tipo_raw.title())

                        if not cfg.tipo_permitido(tipo_display, papel):
                            continue

                        hires = bool(
                            album.get("hires_streamable")
                            or album.get("hires")
                            or (album.get("maximum_bit_depth",    0) or 0) > 16
                            or (album.get("maximum_sampling_rate", 0) or 0) > 44.1
                        )

                        novidades.append({
                            "id":           album_id,
                            "title":        album.get("title", "Unknown"),
                            "artist":       artist_name,
                            "album_artist": (album.get("artist") or {}).get("name", artist_name),
                            "type":         tipo_display,
                            "role":         papel,
                            "date":         match.group(),
                            "hires":        hires,
                        })

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Erro ao buscar '%s' (id=%s): %s", artist_name, artist_id, exc)
        finally:
            contador[0] += 1
            _progresso(contador[0], contador[1], artist_name)

    return novidades


# ---------------------------------------------------------------------------
# Deduplicação Inteligente & Ordenação
# ---------------------------------------------------------------------------

def _limpar_titulo_para_comparacao(titulo: str) -> str:
    """Remove parênteses, colchetes e caracteres especiais para achar duplicatas exatas."""
    t = (titulo or "").lower()
    t = re.sub(r"[\(\[].*?[\)\]]", "", t) # Remove (Deluxe), (Remastered), etc.
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def deduplicar_inteligente(lancamentos: List[Dict]) -> List[Dict]:
    """
    Agrupa lançamentos pelo mesmo Artista + Título base. 
    Se houver colisões (ex: versão 16-bit e 24-bit juntas), descarta a pior e mantém a Hi-Res.
    """
    unicos = {}
    
    for l in lancamentos:
        chave_artista = _limpar_titulo_para_comparacao(l["album_artist"])
        chave_titulo  = _limpar_titulo_para_comparacao(l["title"])
        chave = f"{chave_artista}::{chave_titulo}"

        if chave not in unicos:
            unicos[chave] = l
        else:
            # Se a versão nova for Hi-Res e a guardada não for, substitui pela nova.
            if l.get("hires") and not unicos[chave].get("hires"):
                unicos[chave] = l
                
    return list(unicos.values())


def ordenar_lancamentos(lancamentos: List[Dict]) -> List[Dict]:
    return sorted(
        lancamentos,
        key=lambda x: (x["date"], x["artist"], x["title"]),
        reverse=True,
    )

# ---------------------------------------------------------------------------
# Montagem das opções para o pick (Tabela Alinhada e Indexada)
# ---------------------------------------------------------------------------

_PREFIX_TIPO = {
    "Álbum":  "[Álbum ]",
    "EP":     "[EP    ]",
    "Single": "[Single]",
}

def montar_opcoes(
    lancamentos: List[Dict],
    fav_ids:     Set[str],
    hoje:        "datetime.date",
) -> Tuple[List[str], List[int]]:
    
    # Agrupamento inteligente que preserva o índice original da lista
    grupos: Dict[str, List[Tuple[int, Dict]]] = {}
    for original_idx, l in enumerate(lancamentos):
        grupos.setdefault(l["artist"], []).append((original_idx, l))

    labels:  List[str] = []
    indices: List[int] = []

    for artista, items in grupos.items():
        # Desempacotamos o índice original e o item
        novos = sum(1 for _, it in items if str(it["id"]) not in fav_ids)
        badge = f"  ({novos} {'novo' if novos == 1 else 'novos'})" if novos > 0 else ""
        labels.append(f"── {artista}{badge} {'─' * max(0, 40 - len(artista))}")
        indices.append(-1) # -1 indica que é um cabeçalho não clicável

        for original_idx, item in items:
            ja_fav   = str(item["id"]) in fav_ids
            data_rel = _data_relativa(item["date"], hoje)
            
            # Formatação de Colunas Fixas
            icone = "★" if ja_fav else "►"
            hires = "HR " if item.get("hires") else "   "
            
            if item["role"] == "featured":
                tipo_str = "[Feat  ]"
                titulo   = _truncar(f"{item['album_artist']} - {item['title']} ft. {item['artist']}", 60)
            else:
                tipo_str = _PREFIX_TIPO.get(item["type"], f"[{item['type'][:6].ljust(6)}]")
                titulo   = _truncar(f"{item['artist']} - {item['title']}", 60)

            # Alinhamento perfeito com ljust e rjust
            label = f"  {icone} {tipo_str:<10} {hires:<3} {titulo:<62} {data_rel:>10}"

            labels.append(label)
            
            # Guardamos o índice real da lista todos_lancamentos
            indices.append(original_idx)

    return labels, indices


# ---------------------------------------------------------------------------
# Adição de favoritos
# ---------------------------------------------------------------------------

async def adicionar_favoritos(
    api:          Client,
    selecionados: List[Tuple[str, int]],
    todos:        List[Dict],
    fav_ids:      Set[str],
) -> None:
    for item_label, index in selecionados:
        album    = todos[index]
        album_id = str(album["id"])

        if album_id in fav_ids:
            print(f"{YELLOW} [!] Já é favorito: {album['artist']} - {album['title']}{OFF}")
            continue

        try:
            await api.add_favorite_album(album_id)
            print(f"{GREEN} [+] Adicionado: {album['artist']} - {album['title']}{OFF}")
            fav_ids.add(album_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Erro ao adicionar '%s - %s': %s", album['artist'], album['title'], exc)
            print(f"{RED} [-] Erro: {album['artist']} - {album['title']}{OFF}")


# ---------------------------------------------------------------------------
# Fluxo principal
# ---------------------------------------------------------------------------

async def _async_run_radar() -> None:
    if os.name == "nt":
        base_path = Path(os.getenv("APPDATA", ""))
    else:
        base_path = Path(os.getenv("HOME", str(Path.home()))) / ".config"

    config_path = base_path / "qobuz-dl" / "config.ini"
    config      = configparser.ConfigParser()
    config.read(config_path)

    if not config.sections():
        print(f"{RED}[!] Config não encontrado: {config_path}{OFF}")
        return

    section = config.sections()[0]
    cfg     = RadarConfig(config, section)
    api     = await setup_client(config, section)
    hoje    = datetime.now(timezone.utc).date()

    try:
        print(
            f"{CYAN}[*] Sincronizando -- verificando novidades "
            f"dos últimos {_pluralizar(cfg.dias_de_busca, 'dia', 'dias')}...{OFF}"
        )
        if cfg.tipos_filtro:
            print(f"{CYAN}[*] Filtro ativo: {', '.join(sorted(cfg.tipos_filtro))}{OFF}")

        fav_data, favs_artists_data = await asyncio.gather(
            api.get_favorites(fav_type="albums",  limit=1_000),
            api.get_favorites(fav_type="artists", limit=500),
        )

        fav_ids: Set[str] = {
            str(item.get("id"))
            for item in fav_data.get("favorites", {}).get("albums", {}).get("items", [])
        }

        artistas = favs_artists_data.get("favorites", {}).get("artists", {}).get("items", [])

        if not artistas:
            print(f"{YELLOW}[!] Nenhum artista favorito encontrado.{OFF}")
            return

        total    = len(artistas)
        contador = [0, total]

        print(f"{CYAN}[*] Verificando {_pluralizar(total, 'artista', 'artistas')}...{OFF}\n")

        semaphore  = asyncio.Semaphore(cfg.max_concurrent)
        tarefas    = [
            fetch_artist_latest_releases(
                api, str(a.get("id")), a.get("name", "Unknown"),
                semaphore, cfg, contador,
            )
            for a in artistas
        ]
        resultados_brutos = await asyncio.gather(*tarefas)

        if sys.stdout.isatty():
            print()

        # Achata a lista de resultados
        lista_plana = [item for sublist in resultados_brutos for item in sublist]
        
        # Processa a deduplicação e em seguida a ordenação
        lancamentos_unicos = deduplicar_inteligente(lista_plana)
        todos_lancamentos = ordenar_lancamentos(lancamentos_unicos)

        if not todos_lancamentos:
            print(
                f"\n{YELLOW}[!] Sem novidades nos últimos "
                f"{_pluralizar(cfg.dias_de_busca, 'dia', 'dias')}.{OFF}"
            )
            return

        labels, indices = montar_opcoes(todos_lancamentos, fav_ids, hoje)

        print_separator()
        total_items = sum(1 for i in indices if i >= 0)
        novos_total = sum(
            1 for i in indices
            if i >= 0 and str(todos_lancamentos[i]["id"]) not in fav_ids
        )
        print(
            f"{CYAN}[*] {_pluralizar(total_items, 'lançamento encontrado', 'lançamentos encontrados')}"
            f" -- {GREEN}{_pluralizar(novos_total, 'novo', 'novos')}{OFF}"
        )
        print(f"{CYAN}[*] Legenda: ► novo  ★ já favoritado  HR = Hi-Res{OFF}\n")

        selected_raw = pick(
            labels,
            "Selecione os lançamentos para adicionar aos favoritos:\n"
            "(ESPAÇO = selecionar  |  ENTER = confirmar)\n"
            "(linhas '──' são cabeçalhos e não podem ser selecionadas)",
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
            print(f"\n{YELLOW}[*] Apenas cabeçalhos selecionados -- nada para adicionar.{OFF}")
            return

        print()
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
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_async_run_radar())
    except RuntimeError:
        asyncio.run(_async_run_radar())