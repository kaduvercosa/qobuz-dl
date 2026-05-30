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
    if not sys.stdout.isatty():
        return
    pct   = int((atual / total) * 20)
    barra = f"[{'█' * pct}{'░' * (20 - pct)}]"
    print(f"\r{CYAN}{barra} {atual}/{total}{OFF} {nome[:40]:<40}", end="", flush=True)


def _truncar(texto: str, limite: int) -> str:
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
# Busca de Playlists em Segundo Plano (Extraindo IDs e Títulos para proteção)
# ---------------------------------------------------------------------------

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
                            local_titles.add(_limpar_titulo_para_comparacao(track["album"].get("title", "")))
            except Exception:
                pass
            return local_ids, local_titles
        
        resultados = await asyncio.gather(*(fetch_playlist_tracks(str(p["id"])) for p in playlists))
        for r_ids, r_titles in resultados:
            album_ids.update(r_ids)
            album_titles.update(r_titles)
            
    except Exception as e:
        logger.warning(f"Erro ao buscar faixas de playlists: {e}")
        
    return album_ids, album_titles


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
    t = re.sub(r"[\(\[].*?[\)\]]", "", t) 
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def deduplicar_inteligente(lancamentos: List[Dict]) -> List[Dict]:
    unicos = {}
    for l in lancamentos:
        chave_artista = _limpar_titulo_para_comparacao(l["album_artist"])
        chave_titulo  = _limpar_titulo_para_comparacao(l["title"])
        chave = f"{chave_artista}::{chave_titulo}"

        if chave not in unicos:
            unicos[chave] = l
        else:
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
    hoje:        "datetime.date",
) -> Tuple[List[str], List[int]]:
    
    grupos: Dict[str, List[Tuple[int, Dict]]] = {}
    for original_idx, l in enumerate(lancamentos):
        grupos.setdefault(l["artist"], []).append((original_idx, l))

    labels:  List[str] = []
    indices: List[int] = []

    for artista, items in grupos.items():
        if labels:
            labels.append(" ")
            indices.append(-1)
            
        badge = f"  ({_pluralizar(len(items), 'pendente', 'pendentes')})"
        labels.append(f"── {artista}{badge} {'─' * max(0, 45 - len(artista))}")
        indices.append(-1) 

        for original_idx, item in items:
            data_rel = _data_relativa(item["date"], hoje)
            hires = "[HR]" if item.get("hires") else "    "
            
            if item["role"] == "featured":
                tipo_str = "[Feat  ]"
                titulo   = _truncar(f"{item['album_artist']} - {item['title']} ft. {item['artist']}", 61)
            else:
                tipo_str = _PREFIX_TIPO.get(item["type"], f"[{item['type'][:6].ljust(6)}]")
                titulo   = _truncar(f"{item['artist']} - {item['title']}", 61)

            label = f"  ► {tipo_str:<10} {hires:<4} {titulo:<61} {data_rel:>10}"

            labels.append(label)
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
# Adição a Playlists Existentes (Seleção Individual + Criação Dinâmica)
# ---------------------------------------------------------------------------

async def adicionar_a_playlist(
    api:          Client,
    selecionados: List[Tuple[str, int]],
    todos:        List[Dict],
) -> None:
    print(f"{CYAN}[*] Buscando suas playlists...{OFF}")
    try:
        playlists_data = await api.get_user_playlists(limit=100) 
        playlists = playlists_data.get("playlists", {}).get("items", [])
    except Exception as exc:
        print(f"{RED}[!] Erro ao buscar playlists: {exc}{OFF}")
        return

    if playlists is None:
        playlists = []

    for label, index in selecionados:
        album = todos[index]
        album_id = str(album["id"])
        album_nome = f"{album['artist']} - {album['title']}"
        nome_nova_pl = album['artist'].upper()

        playlist_ja_existe = any(pl.get('name', '').strip().upper() == nome_nova_pl for pl in playlists)

        opcoes_menu = []
        if not playlist_ja_existe:
            opcoes_menu.append(f">> Criar nova playlist: {nome_nova_pl}")

        for pl in playlists:
            opcoes_menu.append(f"{pl['name']} ({pl.get('tracks_count', 0)} faixas)")

        opcoes_menu.append(">> Pular este lançamento (Não adicionar a nenhuma)")

        selecao_pl = pick(
            opcoes_menu,
            f"Destino para: {album_nome}\nEscolha a playlist (ENTER = confirmar):",
            multiselect=False
        )
        
        opcao_texto, pl_index = selecao_pl
        
        if opcao_texto.startswith(">> Pular"):
            print(f"{YELLOW}[*] Pulado: {album_nome}{OFF}")
            continue
            
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
                continue
        else:
            offset = 1 if not playlist_ja_existe else 0
            real_index = pl_index - offset
            playlist_escolhida = playlists[real_index]
            playlist_id = str(playlist_escolhida["id"])
        
        print(f"{CYAN}[*] Puxando faixas de '{album_nome}'...{OFF}")
        
        track_ids = []
        try:
            album_data = await api.get_album_meta(album_id)
            faixas = album_data.get("tracks", {}).get("items", [])
            for f in faixas:
                track_ids.append(str(f["id"]))
        except Exception as e:
            logger.error("Erro ao puxar faixas do álbum %s: %s", album_id, e)
            print(f"{RED}[-] Erro ao ler faixas deste lançamento.{OFF}")
            continue

        if not track_ids:
            print(f"{RED}[!] Nenhuma faixa encontrada.{OFF}")
            continue

        TAMANHO_LOTE = 50
        try:
            for i in range(0, len(track_ids), TAMANHO_LOTE):
                lote = track_ids[i : i + TAMANHO_LOTE]
                track_ids_str = ",".join(lote)
                
                await api.add_playlist_tracks(playlist_id, track_ids_str)
                await asyncio.sleep(0.5) 
                
            print(f"{GREEN}[+] Adicionado à '{playlist_escolhida['name']}': {album_nome}{OFF}")
            playlist_escolhida["tracks_count"] = playlist_escolhida.get("tracks_count", 0) + len(track_ids)
            
        except Exception as e:
            print(f"{RED}[-] Erro ao injetar músicas na playlist: {e}{OFF}")
            
    print(f"{GREEN}[*] Processamento de playlists concluído!{OFF}")


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

        fav_data, favs_artists_data, playlist_data = await asyncio.gather(
            api.get_favorites(fav_type="albums",  limit=1_000),
            api.get_favorites(fav_type="artists", limit=500),
            obter_dados_das_playlists(api)
        )

        playlist_album_ids, playlist_album_titles = playlist_data

        fav_ids: Set[str] = {
            str(item.get("id"))
            for item in fav_data.get("favorites", {}).get("albums", {}).get("items", [])
        }
        fav_ids.update(playlist_album_ids)
        
        fav_titles: Set[str] = {
            _limpar_titulo_para_comparacao(item.get("title", ""))
            for item in fav_data.get("favorites", {}).get("albums", {}).get("items", [])
        }
        fav_titles.update(playlist_album_titles)

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

        lista_plana = [item for sublist in resultados_brutos for item in sublist]
        
        lancamentos_unicos = deduplicar_inteligente(lista_plana)
        todos_lancamentos_brutos = ordenar_lancamentos(lancamentos_unicos)

        todos_lancamentos = [
            l for l in todos_lancamentos_brutos 
            if str(l["id"]) not in fav_ids and _limpar_titulo_para_comparacao(l["title"]) not in fav_titles
        ]

        if not todos_lancamentos:
            print(
                f"\n{GREEN}[+] Caixa de Entrada Zerada! Nenhuma novidade pendente nos últimos "
                f"{_pluralizar(cfg.dias_de_busca, 'dia', 'dias')}.{OFF}"
            )
            return

        labels, indices = montar_opcoes(todos_lancamentos, hoje)

        print_separator()
        total_items = sum(1 for i in indices if i >= 0)

        print(
            f"{CYAN}[*] {_pluralizar(total_items, 'lançamento pendente encontrado', 'lançamentos pendentes encontrados')} "
            f"(Ocultando os que já estão na sua biblioteca){OFF}"
        )
        print(f"{CYAN}[*] Legenda: ► novo/pendente   [HR] = Hi-Res{OFF}\n")

        selected_raw = pick(
            labels,
            "Selecione os lançamentos que você tem interesse:\n"
            "(ESPAÇO = selecionar  |  ENTER = confirmar)\n"
            "(linhas vazias ou com '──' são separadores e não podem ser selecionadas)",
            multiselect=True,
            options_map_func=lambda o: o,
        )

        if not selected_raw:
            print(f"{YELLOW}[*] Nenhum lançamento selecionado.{OFF}")
            return

        selecionados_validos = [
            (label, indices[pick_idx])
            for label, pick_idx in selected_raw
            if indices[pick_idx] >= 0
        ]

        if not selecionados_validos:
            print(f"{YELLOW}[*] Apenas cabeçalhos selecionados -- nada para processar.{OFF}")
            return

        destino_opcoes = [
            "1. Salvar nos Álbuns Favoritos",
            "2. Adicionar a uma Playlist Existente (Escolha individual)"
        ]
        destino_selecionado = pick(
            destino_opcoes,
            "Onde você deseja salvar os lançamentos selecionados?",
            multiselect=False
        )

        if not destino_selecionado:
            print(f"{YELLOW}[*] Ação cancelada.{OFF}")
            return

        opcao_destino_texto, _ = destino_selecionado

        if "1." in opcao_destino_texto:
            await adicionar_favoritos(api, selecionados_validos, todos_lancamentos, fav_ids)
        else:
            await adicionar_a_playlist(api, selecionados_validos, todos_lancamentos)

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