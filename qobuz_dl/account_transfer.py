"""
account_transfer.py -- Modo de Transferência e Diff de Conta
Transfere favoritos (álbuns, artistas, tracks, playlists) entre duas contas Qobuz.

Uso:
  qobuz-dl transfer            # modo transferência interactivo
  qobuz-dl transfer --diff     # modo diff: compara sem transferir
"""
from __future__ import annotations

import asyncio
import configparser
import getpass
import os
import platform
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from qobuz_dl.color import GREEN, RED, YELLOW, CYAN, BLUE, OFF
from qobuz_dl.qopy import Client
from tqdm import tqdm

try:
    from pick import pick
    HAS_PICK = True
except ImportError:
    HAS_PICK = False

# ─────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────

MAX_DIFF_ROWS  = 80   # máximo de linhas mostradas por lado no diff
RATE_SLEEP     = 0.12 # segundos mínimos entre chamadas à API
PLAYLIST_BATCH = 50   # tracks por lote ao adicionar a uma playlist
MAX_RETRIES    = 3    # máximo de tentativas em caso de erro da API (Backoff)

# ─────────────────────────────────────────────────────────────
# CONFIG PATH (replica a lógica do cli.py para compatibilidade)
# ─────────────────────────────────────────────────────────────

def _get_config_path() -> Path:
    is_ios = sys.platform == "ios"
    if not is_ios and sys.platform == "darwin":
        if (
            platform.machine().startswith(("iPhone", "iPad", "iPod"))
            or "PYTHONISTA_ROOT" in os.environ
            or "/var/mobile/" in str(Path.home())
        ):
            is_ios = True
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif is_ios:
        base = Path.home() / "Documents"
    else:
        base = Path(os.environ.get("HOME") or Path.home()) / ".config"
    return base / "qobuz-dl" / "config.ini"


# ─────────────────────────────────────────────────────────────
# UI -- BANNER E HELPERS
# ─────────────────────────────────────────────────────────────

_W = 62  # largura interna da caixa

def _linha(texto: str = "") -> str:
    pad = _W - len(texto)
    return f"║  {texto}{' ' * max(0, pad)}║"

def _banner(modo_diff: bool = False) -> None:
    subtitulo = "   Audite diferenças entre contas Qobuz" if modo_diff else \
                "   Mova favoritos e playlists entre contas Qobuz"
    icone = "🔍" if modo_diff else "🔄"
    sufixo = " -- MODO DIFF" if modo_diff else ""
    print(f"\n{CYAN}╔{'═' * (_W + 2)}╗")
    print(_linha(f"{icone}  QOBUZ-DL MASTER -- TRANSFER DE CONTA{sufixo}"))
    print(_linha(subtitulo))
    print(f"╚{'═' * (_W + 2)}╝{OFF}\n")

def _secao(titulo: str) -> None:
    print(f"\n{YELLOW}── {titulo} {'─' * max(0, _W - len(titulo) - 3)}{OFF}")

def _ok(msg: str)   -> None: tqdm.write(f"{GREEN}  ✔  {msg}{OFF}")
def _erro(msg: str) -> None: tqdm.write(f"{RED}  ✘  {msg}{OFF}")
def _info(msg: str) -> None: tqdm.write(f"{CYAN}  ·  {msg}{OFF}")

def _resumo_tabela(linhas: List[Tuple[str, str]]) -> None:
    larg  = max(len(r[0]) for r in linhas) + 2
    largv = max(len(str(r[1])) for r in linhas) + 2
    sep  = f"  ├{'─' * (larg + 2)}┼{'─' * (largv + 2)}┤"
    topo = f"  ┌{'─' * (larg + 2)}┬{'─' * (largv + 2)}┐"
    base = f"  └{'─' * (larg + 2)}┴{'─' * (largv + 2)}┘"
    print(topo)
    for i, (k, v) in enumerate(linhas):
        print(f"  │ {k:<{larg}} │ {CYAN}{str(v):>{largv}}{OFF} │")
        if i < len(linhas) - 1:
            print(sep)
    print(base)

def _truncar(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


# ─────────────────────────────────────────────────────────────
# PICK HELPERS
# ─────────────────────────────────────────────────────────────

def _pick_one(opcoes: List[str], titulo: str) -> str:
    if HAS_PICK:
        sel, _ = pick(opcoes, titulo, indicator="❯")
        return sel
    print(f"\n{titulo}")
    for i, o in enumerate(opcoes, 1):
        print(f"  {i}. {o}")
    while True:
        try:
            idx = int(input(f"  Escolha [1-{len(opcoes)}]: ").strip()) - 1
            if 0 <= idx < len(opcoes):
                return opcoes[idx]
        except (ValueError, KeyboardInterrupt):
            pass

def _pick_multi(opcoes: List[str], titulo: str) -> List[str]:
    if HAS_PICK:
        selecionados = pick(
            opcoes, titulo, multiselect=True, min_selection_count=1, indicator="❯"
        )
        return [s[0] for s in selecionados]
    print(f"\n{titulo}")
    for i, o in enumerate(opcoes, 1):
        print(f"  {i}. {o}")
    raw = input("  Escolha (números separados por vírgula, ex: 1,3): ").strip()
    resultado = []
    for part in raw.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(opcoes):
                resultado.append(opcoes[idx])
        except ValueError:
            pass
    return resultado or [opcoes[0]]


# ─────────────────────────────────────────────────────────────
# LABELS
# ─────────────────────────────────────────────────────────────

def _label_album(a: Dict) -> str:
    artista = (a.get("artist") or {}).get("name") or str(a.get("artist") or "?")
    titulo  = a.get("title") or "?"
    ano     = str(a.get("release_date_original") or "")[:4]
    return _truncar(f"{artista} -- {titulo}" + (f"  [{ano}]" if ano else ""), 70)

def _label_artista(a: Dict) -> str:
    return _truncar(a.get("name") or "?", 70)

def _label_track(t: Dict) -> str:
    artista = (t.get("performer") or {}).get("name") or "?"
    titulo  = t.get("title") or "?"
    album   = (t.get("album") or {}).get("title") or ""
    label   = f"{artista} -- {titulo}"
    if album:
        label += f"  ({album})"
    return _truncar(label, 70)

def _label_playlist(p: Dict) -> str:
    nome = p.get("name") or "?"
    n    = p.get("tracks_count") or p.get("nb_tracks") or "?"
    return _truncar(f"{nome}  ({n} tracks)", 70)


# ─────────────────────────────────────────────────────────────
# FETCH PAGINADO
# ─────────────────────────────────────────────────────────────

async def _fetch_all_favorites(client: Client, fav_type: str) -> List[Dict]:
    all_items: List[Dict] = []
    offset, page_size = 0, 500
    while True:
        try:
            result = await client.get_favorites(
                fav_type=fav_type, limit=page_size, offset=offset
            )
        except Exception as e:
            _erro(f"Erro a buscar {fav_type} (offset={offset}): {e}")
            break
        if fav_type in ("playlists", "playlist"):
            bucket = result.get("playlists", {})
        else:
            bucket = result.get("favorites", {}).get(fav_type, {})
        items = bucket.get("items", [])
        total = bucket.get("total", 0)
        all_items.extend(items)
        offset += len(items)
        if not items or offset >= total:
            break
    return all_items

async def _fetch_all_playlist_tracks(client: Client, playlist_id: str) -> List[str]:
    track_ids: List[str] = []
    try:
        async for chunk in client.get_plist_meta(str(playlist_id)):
            for t in chunk.get("tracks", {}).get("items", []):
                tid = str(t.get("id") or "")
                if tid:
                    track_ids.append(tid)
    except Exception as e:
        _erro(f"Erro a ler tracks da playlist {playlist_id}: {e}")
    return track_ids


# ─────────────────────────────────────────────────────────────
# SELEÇÃO GRANULAR
# ─────────────────────────────────────────────────────────────

def _selecao_granular(
    items: List[Dict],
    label_fn: Callable[[Dict], str],
    tipo_nome: str,
) -> List[Dict]:
    total = len(items)
    if total == 0:
        return items

    _secao(f"Seleção -- {tipo_nome.capitalize()}")

    escolha = _pick_one(
        [
            f"Transferir todos  ({total} {tipo_nome})",
            f"Escolher individualmente",
        ],
        f"  Como transferir os {tipo_nome}?",
    )

    if "individualmente" not in escolha.lower():
        _ok(f"Todos os {total} {tipo_nome} seleccionados.")
        return items

    labels = [label_fn(item) for item in items]
    selecionados_labels = _pick_multi(
        labels,
        f"  Seleccione os {tipo_nome} (ESPAÇO=marcar, ENTER=confirmar):",
    )
    sel_set = set(selecionados_labels)
    filtrados = [item for item, lbl in zip(items, labels) if lbl in sel_set]
    _ok(f"{len(filtrados)} de {total} {tipo_nome} seleccionados.")
    return filtrados


# ─────────────────────────────────────────────────────────────
# EXECUTORES DE TRANSFERÊNCIA
# ─────────────────────────────────────────────────────────────

async def _exec_generico(
    items: List[Dict], dst_ids: Set[str], metodo_dst: Callable, label: str
) -> Tuple[int, int, int]:
    """
    Executor unificado para Álbuns, Artistas e Tracks com Backoff Exponencial.
    """
    transferidos = duplicados = falhas = 0
    
    # Barra de progresso formatada ao estilo do antigo _progresso
    bar_format = f"  {CYAN}[{{bar:28}}]{OFF} {{percentage:3.0f}}%  {{n_fmt}}/{{total_fmt}}  {{desc}}"
    
    for item in tqdm(items, desc=label, bar_format=bar_format, leave=False):
        item_id = str(item.get("id") or "")
        
        if not item_id:
            falhas += 1
            continue
            
        if item_id in dst_ids:
            duplicados += 1
            continue
            
        # Backoff exponencial em caso de API Rate Limit
        for tentativa in range(MAX_RETRIES):
            try:
                await metodo_dst(item_id)
                transferidos += 1
                await asyncio.sleep(RATE_SLEEP)
                break
            except Exception:
                if tentativa < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** tentativa) # 1s, 2s, 4s...
                else:
                    falhas += 1
                    
    return transferidos, duplicados, falhas


async def _exec_playlists(
    items: List[Dict], dst_nomes: Set[str], dst: Client, src: Client
) -> Tuple[int, int, int]:
    criadas = tracks_ok = falhas = 0
    total = len(items)
    
    for i, pl in enumerate(items, 1):
        nome  = pl.get("name") or f"Playlist Transferida {i}"
        pl_id = str(pl.get("id") or "")
        tqdm.write(f"\n  {CYAN}[{i}/{total}]{OFF} A copiar: {nome}")

        track_ids = await _fetch_all_playlist_tracks(src, pl_id)
        if not track_ids:
            _info(f"Playlist '{nome}' está vazia -- ignorada.")
            continue

        nome_dst = f"{nome} (importada)" if nome.strip().lower() in dst_nomes else nome
        
        try:
            # Criação com Backoff
            nova_id = ""
            for t in range(MAX_RETRIES):
                try:
                    res = await dst.create_playlist(nome_dst)
                    nova_id = str(res.get("id") or res.get("playlist", {}).get("id") or "")
                    break
                except Exception:
                    if t < MAX_RETRIES - 1: await asyncio.sleep(2 ** t)
                    else: raise
                    
            if not nova_id:
                _erro(f"Não foi possível obter ID da playlist '{nome_dst}'.")
                falhas += 1
                continue
                
            # População com Backoff
            for j in range(0, len(track_ids), PLAYLIST_BATCH):
                chunk = track_ids[j : j + PLAYLIST_BATCH]
                for t in range(MAX_RETRIES):
                    try:
                        await dst.add_playlist_tracks(nova_id, ",".join(chunk))
                        tracks_ok += len(chunk)
                        await asyncio.sleep(0.2)
                        break
                    except Exception:
                        if t < MAX_RETRIES - 1: await asyncio.sleep(2 ** t)
                        else: raise
                        
            criadas += 1
            _ok(f"'{nome_dst}' criada com {len(track_ids)} tracks.")
            
        except Exception as e:
            _erro(f"Erro ao criar/popular '{nome_dst}': {e}")
            falhas += 1
            
    return criadas, tracks_ok, falhas


# ─────────────────────────────────────────────────────────────
# MODO DIFF -- RELATÓRIO DE DIFERENÇAS
# ─────────────────────────────────────────────────────────────

def _diff_tabela_dois_campos(
    items: List[Tuple[str, str]],
    cabecalho: Tuple[str, str],
    col_a: int = 32,
    col_b: int = 32,
) -> None:
    C1, C2 = col_a, col_b
    div = f"  ├{'─' * (C1 + 2)}┼{'─' * (C2 + 2)}┤"
    print(f"  ┌{'─' * (C1 + 2)}┬{'─' * (C2 + 2)}┐")
    h1, h2 = cabecalho
    print(f"  │ {YELLOW}{h1:<{C1}}{OFF} │ {YELLOW}{h2:<{C2}}{OFF} │")
    print(div)
    for v1, v2 in items:
        print(f"  │ {_truncar(v1, C1):<{C1}} │ {_truncar(v2, C2):<{C2}} │")
    print(f"  └{'─' * (C1 + 2)}┴{'─' * (C2 + 2)}┘")

def _diff_lista_simples(items: List[str], col: int = 66) -> None:
    print(f"  ┌{'─' * (col + 2)}┐")
    for v in items:
        print(f"  │ {_truncar(v, col):<{col}} │")
    print(f"  └{'─' * (col + 2)}┘")

def _diff_secao_header(emoji: str, titulo: str) -> None:
    largura = _W + 2
    linha = f"  {emoji}  {titulo}"
    print(f"\n{CYAN}{'═' * (largura + 2)}{OFF}")
    print(f"  {CYAN}{linha}{OFF}")
    print(f"{CYAN}{'═' * (largura + 2)}{OFF}")


async def _relatorio_diff(
    main_client: Client,
    outra_client: Client,
    main_label: str,
    outra_label: str,
    fazer_albums: bool,
    fazer_artistas: bool,
    fazer_tracks: bool,
    fazer_playlists: bool,
) -> None:
    _secao("A recolher dados das duas contas...")

    if fazer_albums:
        _info("A carregar álbuns...")
        main_alb  = await _fetch_all_favorites(main_client, "albums")
        outra_alb = await _fetch_all_favorites(outra_client, "albums")

        main_alb_ids  = {str(a.get("id")) for a in main_alb}
        outra_alb_ids = {str(a.get("id")) for a in outra_alb}
        so_main  = [a for a in main_alb  if str(a.get("id")) not in outra_alb_ids]
        so_outra = [a for a in outra_alb if str(a.get("id")) not in main_alb_ids]
        comuns   = len(main_alb_ids & outra_alb_ids)

        _diff_secao_header("🎵", "ÁLBUNS FAVORITOS")
        _resumo_tabela([
            (main_label,         f"{len(main_alb)} álbuns"),
            (outra_label,        f"{len(outra_alb)} álbuns"),
            ("Em ambas as contas", f"{comuns} álbuns"),
        ])

        if so_main:
            print(f"\n  {GREEN}← Apenas em {main_label}{OFF}  ({len(so_main)} álbuns)")
            rows = [
                (_truncar((a.get("artist") or {}).get("name") or "?", 32),
                 _truncar(a.get("title") or "?", 32))
                for a in so_main[:MAX_DIFF_ROWS]
            ]
            _diff_tabela_dois_campos(rows, ("Artista", "Álbum"))
            if len(so_main) > MAX_DIFF_ROWS:
                print(f"  {YELLOW}  ... e mais {len(so_main) - MAX_DIFF_ROWS} álbuns{OFF}")

        if so_outra:
            print(f"\n  {YELLOW}→ Apenas em {outra_label}{OFF}  ({len(so_outra)} álbuns)")
            rows = [
                (_truncar((a.get("artist") or {}).get("name") or "?", 32),
                 _truncar(a.get("title") or "?", 32))
                for a in so_outra[:MAX_DIFF_ROWS]
            ]
            _diff_tabela_dois_campos(rows, ("Artista", "Álbum"))
            if len(so_outra) > MAX_DIFF_ROWS:
                print(f"  {YELLOW}  ... e mais {len(so_outra) - MAX_DIFF_ROWS} álbuns{OFF}")

        if not so_main and not so_outra:
            _ok("Ambas as contas têm exactamente os mesmos álbuns favoritos.")

    if fazer_artistas:
        _info("A carregar artistas...")
        main_art  = await _fetch_all_favorites(main_client, "artists")
        outra_art = await _fetch_all_favorites(outra_client, "artists")

        main_art_ids  = {str(a.get("id")) for a in main_art}
        outra_art_ids = {str(a.get("id")) for a in outra_art}
        so_main  = [a for a in main_art  if str(a.get("id")) not in outra_art_ids]
        so_outra = [a for a in outra_art if str(a.get("id")) not in main_art_ids]
        comuns   = len(main_art_ids & outra_art_ids)

        _diff_secao_header("🎤", "ARTISTAS FAVORITOS")
        _resumo_tabela([
            (main_label,          f"{len(main_art)} artistas"),
            (outra_label,         f"{len(outra_art)} artistas"),
            ("Em ambas as contas", f"{comuns} artistas"),
        ])

        if so_main:
            print(f"\n  {GREEN}← Apenas em {main_label}{OFF}  ({len(so_main)} artistas)")
            _diff_lista_simples([a.get("name") or "?" for a in so_main[:MAX_DIFF_ROWS]])
            if len(so_main) > MAX_DIFF_ROWS:
                print(f"  {YELLOW}  ... e mais {len(so_main) - MAX_DIFF_ROWS} artistas{OFF}")

        if so_outra:
            print(f"\n  {YELLOW}→ Apenas em {outra_label}{OFF}  ({len(so_outra)} artistas)")
            _diff_lista_simples([a.get("name") or "?" for a in so_outra[:MAX_DIFF_ROWS]])
            if len(so_outra) > MAX_DIFF_ROWS:
                print(f"  {YELLOW}  ... e mais {len(so_outra) - MAX_DIFF_ROWS} artistas{OFF}")

        if not so_main and not so_outra:
            _ok("Ambas as contas têm exactamente os mesmos artistas favoritos.")

    if fazer_tracks:
        _info("A carregar tracks...")
        main_trk  = await _fetch_all_favorites(main_client, "tracks")
        outra_trk = await _fetch_all_favorites(outra_client, "tracks")

        main_trk_ids  = {str(t.get("id")) for t in main_trk}
        outra_trk_ids = {str(t.get("id")) for t in outra_trk}
        so_main  = [t for t in main_trk  if str(t.get("id")) not in outra_trk_ids]
        so_outra = [t for t in outra_trk if str(t.get("id")) not in main_trk_ids]
        comuns   = len(main_trk_ids & outra_trk_ids)

        _diff_secao_header("🎧", "TRACKS FAVORITAS")
        _resumo_tabela([
            (main_label,          f"{len(main_trk)} tracks"),
            (outra_label,         f"{len(outra_trk)} tracks"),
            ("Em ambas as contas", f"{comuns} tracks"),
        ])

        def _track_row(t: Dict) -> Tuple[str, str]:
            artista = (t.get("performer") or {}).get("name") or "?"
            titulo  = t.get("title") or "?"
            return _truncar(artista, 28), _truncar(titulo, 36)

        if so_main:
            print(f"\n  {GREEN}← Apenas em {main_label}{OFF}  ({len(so_main)} tracks)")
            _diff_tabela_dois_campos(
                [_track_row(t) for t in so_main[:MAX_DIFF_ROWS]],
                ("Artista", "Track"), col_a=28, col_b=36
            )
            if len(so_main) > MAX_DIFF_ROWS:
                print(f"  {YELLOW}  ... e mais {len(so_main) - MAX_DIFF_ROWS} tracks{OFF}")

        if so_outra:
            print(f"\n  {YELLOW}→ Apenas em {outra_label}{OFF}  ({len(so_outra)} tracks)")
            _diff_tabela_dois_campos(
                [_track_row(t) for t in so_outra[:MAX_DIFF_ROWS]],
                ("Artista", "Track"), col_a=28, col_b=36
            )
            if len(so_outra) > MAX_DIFF_ROWS:
                print(f"  {YELLOW}  ... e mais {len(so_outra) - MAX_DIFF_ROWS} tracks{OFF}")

        if not so_main and not so_outra:
            _ok("Ambas as contas têm exactamente as mesmas tracks favoritas.")

    if fazer_playlists:
        _info("A carregar playlists...")
        main_pl  = await _fetch_all_favorites(main_client, "playlists")
        outra_pl = await _fetch_all_favorites(outra_client, "playlists")

        main_nomes  = {p.get("name", "").strip().lower() for p in main_pl}
        outra_nomes = {p.get("name", "").strip().lower() for p in outra_pl}
        so_main  = [p for p in main_pl  if p.get("name","").strip().lower() not in outra_nomes]
        so_outra = [p for p in outra_pl if p.get("name","").strip().lower() not in main_nomes]
        comuns   = len(main_nomes & outra_nomes)

        _diff_secao_header("📋", "PLAYLISTS")
        _resumo_tabela([
            (main_label,          f"{len(main_pl)} playlists"),
            (outra_label,         f"{len(outra_pl)} playlists"),
            ("Em ambas as contas", f"{comuns} playlists"),
        ])

        def _pl_row(p: Dict) -> Tuple[str, str]:
            nome = p.get("name") or "?"
            n    = p.get("tracks_count") or p.get("nb_tracks") or "?"
            return _truncar(nome, 48), str(n)

        if so_main:
            print(f"\n  {GREEN}← Apenas em {main_label}{OFF}  ({len(so_main)} playlists)")
            _diff_tabela_dois_campos(
                [_pl_row(p) for p in so_main[:MAX_DIFF_ROWS]],
                ("Nome da Playlist", "Tracks"), col_a=48, col_b=8
            )

        if so_outra:
            print(f"\n  {YELLOW}→ Apenas em {outra_label}{OFF}  ({len(so_outra)} playlists)")
            _diff_tabela_dois_campos(
                [_pl_row(p) for p in so_outra[:MAX_DIFF_ROWS]],
                ("Nome da Playlist", "Tracks"), col_a=48, col_b=8
            )

        if not so_main and not so_outra:
            _ok("Ambas as contas têm as mesmas playlists (por nome).")

    print(f"\n  {CYAN}{'─' * (_W + 2)}{OFF}")
    print(f"  {GREEN}Diff concluído.{OFF}  Nada foi transferido.\n")


# ─────────────────────────────────────────────────────────────
# CREDENCIAIS E CLIENTE
# ─────────────────────────────────────────────────────────────

def _pedir_credenciais(label: str, config: configparser.ConfigParser, config_path: Path) -> Tuple[str, str]:
    _secao(label)
    
    sec_name = "transfer_accounts"
    saved_accounts = {}
    if config.has_section(sec_name):
        saved_accounts = dict(config.items(sec_name))
    
    if saved_accounts:
        opcoes = [f"💾 {email}" for email in saved_accounts.keys()]
        opcoes.append("➕ Adicionar nova conta")
        
        escolha = _pick_one(opcoes, "  Contas disponíveis:")
        if escolha.startswith("💾"):
            email = escolha.replace("💾 ", "").strip()
            _ok(f"A usar credenciais guardadas para: {email}")
            return email, saved_accounts[email]
    
    email = input(f"  {CYAN}Email:{OFF} ").strip()
    token = input(
        f"  {CYAN}Token de autenticação{OFF} "
        f"(deixe em branco para usar password): "
    ).strip()
    if not token:
        token = getpass.getpass(f"  {CYAN}Password:{OFF} ")
        
    salvar = input(f"  {YELLOW}Deseja guardar esta conta para as próximas transferências? [S/n]:{OFF} ").strip().lower()
    if salvar not in ('n', 'nao', 'não'):
        if not config.has_section(sec_name):
            config.add_section(sec_name)
        config.set(sec_name, email, token)
        try:
            with open(config_path, "w") as f:
                config.write(f)
            _ok(f"Conta '{email}' guardada com sucesso no config.ini!")
        except Exception as e:
            _erro(f"Não foi possível guardar a conta: {e}")
            
    return email, token

async def _criar_cliente(
    email: str, token_ou_pwd: str, app_id: str, secrets: List[str]
) -> Optional[Client]:
    parece_token = len(token_ou_pwd) > 30 and " " not in token_ou_pwd
    client = Client(
        email=email,
        pwd="" if parece_token else token_ou_pwd,
        app_id=app_id,
        secrets=secrets,
        user_auth_token=token_ou_pwd if parece_token else "",
    )
    try:
        await client.start()
        return client
    except Exception as e:
        _erro(f"Falha ao autenticar '{email}': {e}")
        return None


# ─────────────────────────────────────────────────────────────
# MAIN ASSÍNCRONO
# ─────────────────────────────────────────────────────────────

async def amain() -> None:

    is_diff = "--diff" in sys.argv or "-d" in sys.argv
    _banner(modo_diff=is_diff)

    config_path = _get_config_path()
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path)
    if not config.sections():
        _erro(f"Configuração não encontrada em {config_path}.")
        _erro("Execute 'qobuz-dl -r' para criar a configuração primeiro.")
        return

    section     = config.sections()[0]
    main_email  = config.get(section, "email",       fallback="")
    main_token  = config.get(section, "auth_token",  fallback="")
    main_pwd    = config.get(section, "password",    fallback="")
    app_id      = config.get(section, "app_id",      fallback="")
    secrets_raw = config.get(section, "secrets",     fallback="")
    secrets     = [s.strip() for s in secrets_raw.split(",") if s.strip()]
    main_cred   = main_token or main_pwd

    print(f"  Conta principal: {CYAN}{main_email}{OFF}")

    importar = True
    if not is_diff:
        _secao("Direção da Transferência")
        dir_escolhida = _pick_one(
            [
                "↙  IMPORTAR  --  trazer favoritos de outra conta para ESTA",
                "↗  EXPORTAR  --  enviar favoritos DESTA conta para outra",
            ],
            "  Qual é a direção da transferência?",
        )
        importar = "IMPORTAR" in dir_escolhida

    _secao("O que Analisar" if is_diff else "O que Transferir")
    titulo_pick = "  O que deseja comparar?" if is_diff else \
                  "  O que deseja transferir? (ESPAÇO=marcar, ENTER=confirmar)"
    tipos_sel = _pick_multi(
        [
            "🎵  Álbuns favoritos",
            "🎤  Artistas favoritos",
            "🎧  Tracks favoritas",
            "📋  Playlists",
        ],
        titulo_pick,
    )
    fazer_albums    = any("Álbuns"    in t for t in tipos_sel)
    fazer_artistas  = any("Artistas"  in t for t in tipos_sel)
    fazer_tracks    = any("Tracks"    in t for t in tipos_sel)
    fazer_playlists = any("Playlists" in t for t in tipos_sel)

    if is_diff:
        label_outra = "Outra Conta (a comparar)"
    elif importar:
        label_outra = "Conta de ORIGEM (outra)"
    else:
        label_outra = "Conta de DESTINO (outra)"
        
    outra_email, outra_cred = _pedir_credenciais(label_outra, config, config_path)

    _secao("A Autenticar")
    print(f"  {CYAN}[1/2]{OFF} Conta principal ({main_email})...")
    main_client = await _criar_cliente(main_email, main_cred, app_id, secrets)
    if not main_client:
        return
    _ok("Conta principal autenticada.")

    print(f"  {CYAN}[2/2]{OFF} Outra conta ({outra_email})...")
    outra_client = await _criar_cliente(outra_email, outra_cred, app_id, secrets)
    if not outra_client:
        await main_client.close()
        return
    _ok("Outra conta autenticada.")

    if is_diff:
        await _relatorio_diff(
            main_client, outra_client,
            main_email, outra_email,
            fazer_albums, fazer_artistas, fazer_tracks, fazer_playlists,
        )
        await main_client.close()
        await outra_client.close()
        return

    src_client = outra_client if importar else main_client
    dst_client = main_client  if importar else outra_client
    src_label  = outra_email  if importar else main_email
    dst_label  = main_email   if importar else outra_email

    _secao(f"A Recolher Itens da Origem  ({src_label})")

    sel_albums:    List[Dict] = []
    sel_artistas:  List[Dict] = []
    sel_tracks:    List[Dict] = []
    sel_playlists: List[Dict] = []

    if fazer_albums:
        _info("A carregar álbuns...")
        all_alb    = await _fetch_all_favorites(src_client, "albums")
        sel_albums = _selecao_granular(all_alb, _label_album, "álbuns")

    if fazer_artistas:
        _info("A carregar artistas...")
        all_art      = await _fetch_all_favorites(src_client, "artists")
        sel_artistas = _selecao_granular(all_art, _label_artista, "artistas")

    if fazer_tracks:
        _info("A carregar tracks...")
        all_trk    = await _fetch_all_favorites(src_client, "tracks")
        sel_tracks = _selecao_granular(all_trk, _label_track, "tracks")

    if fazer_playlists:
        _info("A carregar playlists...")
        all_pl       = await _fetch_all_favorites(src_client, "playlists")
        sel_playlists = _selecao_granular(all_pl, _label_playlist, "playlists")

    _secao("Pré-visualização")
    preview: List[Tuple[str, str]] = [
        ("Direcção",  "← IMPORTAR" if importar else "→ EXPORTAR"),
        ("Origem",    src_label),
        ("Destino",   dst_label),
    ]
    if sel_albums:    preview.append(("Álbuns a transferir",    str(len(sel_albums))))
    if sel_artistas:  preview.append(("Artistas a transferir",  str(len(sel_artistas))))
    if sel_tracks:    preview.append(("Tracks a transferir",    str(len(sel_tracks))))
    if sel_playlists: preview.append(("Playlists a copiar",     str(len(sel_playlists))))
    print()
    _resumo_tabela(preview)

    if not any([sel_albums, sel_artistas, sel_tracks, sel_playlists]):
        print(f"\n  {YELLOW}Nenhum item seleccionado para transferir.{OFF}\n")
        await main_client.close()
        await outra_client.close()
        return

    print()
    confirma = input(
        f"  {YELLOW}Iniciar transferência para '{dst_label}'?{OFF} [s/N]: "
    ).strip().lower()
    if confirma not in ("s", "sim", "y", "yes"):
        print(f"\n  {YELLOW}Operação cancelada.{OFF}\n")
        await main_client.close()
        await outra_client.close()
        return

    _secao("A Transferir")
    resultados: List[Tuple[str, int, int, int]] = []

    if sel_albums:
        print()
        _info("A verificar álbuns no destino (duplicados)...")
        dst_alb_ids = {str(a.get("id")) for a in await _fetch_all_favorites(dst_client, "albums")}
        t, d, f = await _exec_generico(sel_albums, dst_alb_ids, dst_client.add_favorite_album, "Álbuns")
        resultados.append(("Álbuns", t, d, f))

    if sel_artistas:
        print()
        _info("A verificar artistas no destino (duplicados)...")
        dst_art_ids = {str(a.get("id")) for a in await _fetch_all_favorites(dst_client, "artists")}
        t, d, f = await _exec_generico(sel_artistas, dst_art_ids, dst_client.add_favorite_artist, "Artistas")
        resultados.append(("Artistas", t, d, f))

    if sel_tracks:
        print()
        _info("A verificar tracks no destino (duplicados)...")
        dst_trk_ids = {str(t.get("id")) for t in await _fetch_all_favorites(dst_client, "tracks")}
        t, d, f = await _exec_generico(sel_tracks, dst_trk_ids, dst_client.add_favorite_track, "Tracks")
        resultados.append(("Tracks", t, d, f))

    if sel_playlists:
        print()
        _info("A verificar playlists no destino...")
        dst_pl       = await _fetch_all_favorites(dst_client, "playlists")
        dst_pl_nomes = {p.get("name", "").strip().lower() for p in dst_pl}
        c, tk, f = await _exec_playlists(sel_playlists, dst_pl_nomes, dst_client, src_client)
        resultados.append(("Playlists criadas", c, tk, f))

    _secao("Relatório Final")
    print()
    for nome, v1, v2, falhas in resultados:
        if nome == "Playlists criadas":
            _ok(f"{nome}: {v1} criadas,  {v2} tracks adicionadas,  {falhas} falhas")
        else:
            _ok(f"{nome}: {v1} transferidos,  {v2} duplicados ignorados,  {falhas} falhas")

    print(f"\n  {GREEN}✅ Transferência concluída!{OFF}\n")

    await main_client.close()
    await outra_client.close()


def run_transfer() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print(f"\n\n{RED}[!] Interrompido (CTRL+C).{OFF}\n")