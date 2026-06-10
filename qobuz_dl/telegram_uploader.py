import os
import re
import sys
import json
import shutil
import logging
import configparser
from datetime import date
from pathlib import Path
from typing import Optional
import time

# ─────────────────────────────────────────────
# Silencia logs do Pyrogram
# ─────────────────────────────────────────────
logging.getLogger("pyrogram").setLevel(logging.ERROR)

# ══════════════════════════════════════════════════════════════════
#  LEITURA DO CONFIG.INI
# ══════════════════════════════════════════════════════════════════

def carregar_config(caminho_ini: str = "config.ini") -> configparser.ConfigParser:
    """
    Carrega o config.ini na seguinte ordem de prioridade:
      1. Variável de ambiente QOBUZ_DL_CONFIG  (definida pelo cli.py automaticamente)
      2. Argumento explícito caminho_ini
      3. Fallback: "config.ini" no diretório corrente
    """
    path = os.environ.get("QOBUZ_DL_CONFIG") or caminho_ini
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    return cfg


def telegram_habilitado(cfg: configparser.ConfigParser) -> bool:
    """Retorna True somente se [telegram] enabled = true no config.ini."""
    return cfg.getboolean("telegram", "enabled", fallback=False)


# ══════════════════════════════════════════════════════════════════
#  LOG EM TEMPO REAL + RESUMO DIÁRIO  (Canal Geral)
# ══════════════════════════════════════════════════════════════════

# Arquivo onde os eventos do dia ficam acumulados até o resumo ser enviado
_LOG_DB = "telegram_log_diario.json"


def _carregar_log_diario() -> dict:
    """Carrega o log do dia atual. Descarta automaticamente dias anteriores."""
    hoje = str(date.today())
    if os.path.exists(_LOG_DB):
        try:
            with open(_LOG_DB, "r", encoding="utf-8") as f:
                dados = json.load(f)
            if dados.get("data") == hoje:
                return dados
        except Exception:
            pass
    return {"data": hoje, "entradas": []}


def _salvar_log_diario(dados: dict) -> None:
    with open(_LOG_DB, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def _registrar_entrada_log(
    album_title: str,
    artista: str,
    ano: str,
    tipo: str,
    qualidade: str,      # ex: "FLAC 24bit/96kHz" ou "MP3 320kbps"
    n_faixas: int,
    link_album: str,
) -> None:
    """Acrescenta uma entrada ao log diário em disco (sem Telegram ainda)."""
    dados = _carregar_log_diario()
    dados["entradas"].append({
        "album":    album_title,
        "artista":  artista,
        "ano":      ano,
        "tipo":     tipo,
        "qualidade": qualidade,
        "faixas":   n_faixas,
        "link":     link_album,
        "hora":    datetime.datetime.now().strftime("%H:%M"),
    })
    _salvar_log_diario(dados)


async def enviar_log_tempo_real(
    app,
    ch_geral: int,
    album_title: str,
    artista: str,
    ano: str,
    tipo: str,
    qualidade: str,
    n_faixas: int,
    link_album: str,
    capa_path: Optional[str]  = None,
) -> None:
    """Envia uma mensagem de log imediata no canal Geral."""
    icone = {"álbum": "💿", "single": "🎵", "ep": "📀", "playlist": "📋"}.get(tipo.lower(), "🎵")
    detalhe_faixas = f"· {n_faixas} faixas" if n_faixas > 1 else ""

    texto = (
        f"{icone} **{album_title}** ({ano})\n"
        f"👤 {artista}\n"
        f"🏷 {tipo.upper()} {detalhe_faixas}\n"
        f"🎚 {qualidade}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 **[Ver no canal de álbuns]({link_album})**"
    )

    try:
        if capa_path and os.path.exists(capa_path) and len(texto) <= 1024:
            await app.send_photo(ch_geral, photo=capa_path, caption=texto)
        else:
            await app.send_message(ch_geral, text=texto, disable_web_page_preview=True)
    except Exception as e:
        log(f"Aviso: falha no log em tempo real -- {e}")


async def enviar_resumo_diario(app, ch_geral: int) -> None:
    """
    Envia (ou atualiza) a mensagem de resumo do dia no canal Geral.
    Usa um arquivo de IDs local para editar a mensagem existente em vez de criar uma nova.
    Deve ser chamado após cada upload -- o resumo vai crescendo ao longo do dia.
    """
    dados = _carregar_log_diario()
    entradas = dados.get("entradas", [])
    if not entradas:
        return

    hoje = dados["data"]
    arq_resumo_id = f"telegram_resumo_id_{hoje}.txt"

    # Monta o texto do resumo
    linhas = []
    for e in entradas:
        icone = {"álbum": "💿", "single": "🎵", "ep": "📀", "playlist": "📋"}.get(e["tipo"].lower(), "🎵")
        faixas_str = f" · {e['faixas']} faixas" if e["faixas"] > 1 else ""
        linhas.append(
            f"{icone} [{e['album']}]({e['link']}) -- {e['artista']} "
            f"({e['ano']}) · {e['tipo'].upper()}{faixas_str} · _{e['qualidade']}_ · `{e['hora']}`"
        )

    total = len(entradas)
    texto = (
        f"📋 **Resumo do dia -- {hoje}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n".join(linhas)
        + f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"**Total adicionado hoje:** {total} lançamento{'s' if total > 1 else ''}"
    )

    # Edita a mensagem existente ou cria uma nova
    msg_id = None
    if os.path.exists(arq_resumo_id):
        try:
            msg_id = int(Path(arq_resumo_id).read_text().strip())
        except Exception:
            pass

    try:
        if msg_id:
            await app.edit_message_text(
                ch_geral, msg_id, texto, disable_web_page_preview=True
            )
        else:
            nova_msg = await app.send_message(
                ch_geral, texto, disable_web_page_preview=True
            )
            Path(arq_resumo_id).write_text(str(nova_msg.id))
    except Exception as e:
        log(f"Aviso: falha ao editar resumo -- {e}")
        # Mensagem sumiu -- recria
        try:
            nova_msg = await app.send_message(ch_geral, texto, disable_web_page_preview=True)
            Path(arq_resumo_id).write_text(str(nova_msg.id))
        except Exception as e2:
            log(f"Aviso: falha ao recriar resumo -- {e2}")

# ─────────────────────────────────────────────
# Helpers de texto
# ─────────────────────────────────────────────

def obter_artista_principal(artista_str: str) -> str:
    for sep in [",", " & ", " feat.", " feat ", " e ", " x "]:
        artista_str = artista_str.replace(sep, ",")
    return artista_str.split(",")[0].strip()


def criar_hashtag(texto: str) -> str:
    return "#" + re.sub(r"\W+", "", str(texto))


def remover_numero_faixa(nome: str) -> str:
    return re.sub(r"^\d+[\s\-\.]+", "", nome).strip()


def log(texto: str):
    sys.stdout.write(f"\r\033[K     [Telegram] {texto}")
    sys.stdout.flush()


def log_ok(texto: str):
    sys.stdout.write(f"\r\033[K     [Telegram] ✓ {texto}\n")
    sys.stdout.flush()


async def progresso(current, total, prefixo):
    pct = (current / total * 100) if total else 0
    sys.stdout.write(f"\r\033[K     [Telegram] {prefixo} [{pct:.1f}%]")
    sys.stdout.flush()


# ─────────────────────────────────────────────
# Índice paginado -- banco de dados local
# ─────────────────────────────────────────────

async def garantir_indice(app, chat_id: int):
    """Cria a mensagem-âncora do índice, caso ainda não exista."""
    arq_ids = f"indice_msgs_{chat_id}.txt"
    if not os.path.exists(arq_ids):
        msg = await app.send_message(
            chat_id, "🗂 **ÍNDICE DO CANAL**\n\n", disable_web_page_preview=True
        )
        await msg.pin()
        with open(arq_ids, "w", encoding="utf-8") as f:
            f.write(f"{msg.id}\n")


async def atualizar_indice(app, chat_id: int, nome: str, link: str, hashtag: str = ""):
    """
    Índice cronológico com suporte a hashtag para buscas nativas do Telegram.
    Cada item fica em linha separada: ▪️ [Nome](link) #Hashtag
    Atualiza o item existente se o nome já constar; senão, anexa ao final.
    """
    CABECALHO = "🗂 **ÍNDICE DO CANAL**"
    novo_item = f"▪️ [{nome}]({link})" + (f" {hashtag}" if hashtag else "")
    marcador = f"▪️ [{nome}]("

    arq_dados = f"indice_dados_{chat_id}.txt"
    arq_ids   = f"indice_msgs_{chat_id}.txt"

    # 1. Carrega histórico local
    linhas: list[str] = []
    if os.path.exists(arq_dados):
        with open(arq_dados, "r", encoding="utf-8") as f:
            linhas = [l.strip() for l in f if l.strip()]

    # 2. Atualiza ou acrescenta
    encontrado = False
    for i, linha in enumerate(linhas):
        if linha.startswith(marcador):
            linhas[i] = novo_item
            encontrado = True
            break
    if not encontrado:
        linhas.append(novo_item)

    with open(arq_dados, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")

    # 3. Paginação (limite seguro de 3 800 chars por mensagem)
    paginas: list[list[str]] = []
    pagina_atual: list[str] = []
    tam_atual = len(CABECALHO) + 20

    for item in linhas:
        tam_item = len(item) + 1
        if tam_atual + tam_item > 3800:
            paginas.append(pagina_atual)
            pagina_atual = [item]
            tam_atual = len(CABECALHO) + 20 + tam_item
        else:
            pagina_atual.append(item)
            tam_atual += tam_item
    if pagina_atual:
        paginas.append(pagina_atual)

    # 4. Edita / cria as mensagens do índice
    msg_ids: list[int] = []
    if os.path.exists(arq_ids):
        with open(arq_ids, "r", encoding="utf-8") as f:
            msg_ids = [int(l.strip()) for l in f if l.strip()]

    novos_ids: list[int] = []
    for i, conteudo in enumerate(paginas):
        sufixo = f" (Parte {i + 1})" if len(paginas) > 1 else ""
        texto = f"{CABECALHO}{sufixo}\n\n" + "\n".join(conteudo)

        if i < len(msg_ids):
            try:
                await app.edit_message_text(
                    chat_id, msg_ids[i], texto, disable_web_page_preview=True
                )
                novos_ids.append(msg_ids[i])
                continue
            except Exception:
                pass

        nova_msg = await app.send_message(chat_id, texto, disable_web_page_preview=True)
        if i == 0:
            try:
                await nova_msg.pin()
            except Exception:
                pass
        novos_ids.append(nova_msg.id)

    with open(arq_ids, "w", encoding="utf-8") as f:
        f.write("\n".join(str(mid) for mid in novos_ids) + "\n")


# ─────────────────────────────────────────────
# Página de artista -- atualizada a cada álbum
# ─────────────────────────────────────────────

async def atualizar_pagina_artista(
    app,
    chat_id_artistas: int,
    artista: str,
    hash_artista: str,
    titulo_album: str,
    link_album: str,
    tipo: str,        # "álbum" | "single" | "EP"
):
    """
    Mantém UMA mensagem por artista no canal de artistas.
    Cada novo álbum/single é acrescentado à discografia existente.
    Usa banco de dados local para rastrear o ID da mensagem por artista.
    """
    arq_artistas = "artistas_db.ini"
    db = configparser.ConfigParser()
    db.read(arq_artistas, encoding="utf-8")

    chave = re.sub(r"\W+", "_", artista).lower()
    icone = {"álbum": "💿", "single": "🎵", "ep": "📀"}.get(tipo.lower(), "🎵")
    novo_item = f"{icone} [{titulo_album}]({link_album}) -- _{tipo}_"

    if db.has_section(chave):
        msg_id   = int(db[chave]["msg_id"])
        discografia_raw = db[chave].get("discografia", "")
        itens = [i for i in discografia_raw.split("||") if i]
        # Evita duplicata
        if not any(titulo_album in item for item in itens):
            itens.append(novo_item)
        discografia_str = "||".join(itens)
    else:
        itens = [novo_item]
        discografia_str = novo_item
        msg_id = None

    texto = (
        f"🎙 **{artista}** {hash_artista}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"**Discografia:**\n"
        + "\n".join(itens)
    )

    if msg_id:
        try:
            await app.edit_message_text(
                chat_id_artistas, msg_id, texto, disable_web_page_preview=True
            )
        except Exception:
            msg_id = None   # mensagem sumiu -- recria

    if not msg_id:
        nova_msg = await app.send_message(
            chat_id_artistas, texto, disable_web_page_preview=True
        )
        msg_id = nova_msg.id

    # Salva no banco local
    if not db.has_section(chave):
        db.add_section(chave)
    db[chave]["msg_id"]      = str(msg_id)
    db[chave]["nome"]        = artista
    db[chave]["discografia"] = discografia_str

    with open(arq_artistas, "w", encoding="utf-8") as f:
        db.write(f)

    return msg_id


# ─────────────────────────────────────────────
# Extração de capa embutida
# ─────────────────────────────────────────────

def extrair_capa(arquivo: str, destino: str) -> bool:
    try:
        if arquivo.lower().endswith(".flac"):
            from mutagen.flac import FLAC
            audio = FLAC(arquivo)
            if audio.pictures:
                with open(destino, "wb") as f:
                    f.write(audio.pictures[0].data)
                return True
        elif arquivo.lower().endswith(".mp3"):
            from mutagen.mp3 import MP3
            from mutagen.id3 import APIC
            audio = MP3(arquivo)
            for tag in audio.tags.values():
                if isinstance(tag, APIC):
                    with open(destino, "wb") as f:
                        f.write(tag.data)
                    return True
    except Exception:
        pass
    return False


# ══════════════════════════════════════════════════════════════════
#  FUNÇÃO PRINCIPAL
# ══════════════════════════════════════════════════════════════════

async def upload_album_completo(
    dir_album:    str,
    album_title:  str,
    artista_faixa: str,
    artista_album: str,
    ano:          str  = "2026",
    tipo:         str  = "álbum",   # "álbum" | "single" | "EP"
    cfg_path:     str  = "config.ini",
):
    """
    Parâmetros
    ----------
    dir_album      : pasta com os arquivos .flac / .mp3 (e opcionalmente cover.jpg)
    album_title    : título do álbum/single exibido no Telegram
    artista_faixa  : artista que aparece no player de áudio (pode incluir feats)
    artista_album  : artista principal para índices e página de artista
    ano            : ano de lançamento
    tipo           : "álbum", "single" ou "EP"  -- muda o ícone e o tratamento
    cfg_path       : caminho para o config.ini
    """

    # ── 0. Verifica se o envio está habilitado ──────────────────────
    cfg = carregar_config(cfg_path)

    if not telegram_habilitado(cfg):
        return

    # ── 1. Lê credenciais e IDs do config.ini ──────────────────────
    from pyrogram import Client
 
    api_id   = cfg.getint("telegram", "api_id")
    api_hash = cfg.get("telegram", "api_hash")
    session  = cfg.get("telegram", "session", fallback="qobuz_session")

    CH_MUSICAS  = cfg.getint("channels", "musicas")
    CH_ALBUNS   = cfg.getint("channels", "albuns")
    CH_ARTISTAS = cfg.getint("channels", "artistas")
    CH_GERAL    = cfg.getint("channels", "geral", fallback=None)  # 0 = desabilitado

    app = Client(session, api_id=api_id, api_hash=api_hash)

    async with app:

        # ── 2. Varre arquivos de áudio ──────────────────────────────
        log("Varrendo pasta...")
        arquivos_audio = sorted(
            str(p) for p in Path(dir_album).rglob("*")
            if p.suffix.lower() in {".flac", ".mp3"}
        )

        if not arquivos_audio:
            log("Nenhum áudio encontrado -- abortando.\n")
            return

        is_single = (tipo.lower() == "single") or (len(arquivos_audio) == 1)
        artista_principal = obter_artista_principal(artista_album)
        hash_artista      = criar_hashtag(artista_principal)

        # ── 3. Garante índices iniciais ─────────────────────────────
        await garantir_indice(app, CH_MUSICAS)
        await garantir_indice(app, CH_ALBUNS)

        # ── 4. Capa ─────────────────────────────────────────────────
        capa_path      = os.path.join(dir_album, "cover.jpg")
        capa_temporaria = False

        if not os.path.exists(capa_path):
            log("Extraindo capa embutida...")
            if extrair_capa(arquivos_audio[0], capa_path):
                capa_temporaria = True

        tem_capa = os.path.exists(capa_path)

        # ── 5. Envia capa no canal de músicas ───────────────────────
        if tem_capa:
            icone_tipo = {"álbum": "💿", "single": "🎵", "ep": "📀"}.get(tipo.lower(), "💿")
            await app.send_photo(
                chat_id=CH_MUSICAS,
                photo=capa_path,
                caption=(
                    f"{icone_tipo} **{album_title}** ({ano})\n"
                    f"👤 {artista_principal} {hash_artista}\n"
                    f"🏷 #{tipo.upper()}"
                ),
            )

        # ── 6. Faz upload de cada faixa ─────────────────────────────
        links_musicas: list[str] = []

        for caminho in arquivos_audio:
            nome_arquivo = os.path.basename(caminho)
            nome_limpo   = re.sub(r"\.(flac|mp3)$", "", nome_arquivo, flags=re.IGNORECASE)
            nome_exibido = remover_numero_faixa(nome_limpo)
            tamanho_mb   = os.path.getsize(caminho) / 1024 / 1024

            log(f"Enviando: {nome_exibido}...")

            msg_musica = await app.send_audio(
                chat_id=CH_MUSICAS,
                audio=caminho,
                caption=(
                    f"🎵 **{nome_exibido}**\n"
                    f"💿 {album_title} ({ano})\n"
                    f"👤 {artista_faixa} {hash_artista}"
                ),
                file_name=nome_arquivo,
                title=nome_exibido,
                performer=artista_faixa,
                thumb=capa_path if tem_capa else None,
                progress=progresso,
                progress_args=(f"⬆ {tamanho_mb:.1f} MB |",),
            )

            # Letra sincronizada (.lrc)
            lrc_path = re.sub(r"\.(flac|mp3)$", ".lrc", caminho, flags=re.IGNORECASE)
            if os.path.exists(lrc_path):
                log(f"Enviando letra: {nome_exibido}.lrc...")
                await app.send_document(
                    chat_id=CH_MUSICAS,
                    document=lrc_path,
                    caption=f"📝 **Letra Sincronizada** -- {nome_exibido}",
                    file_name=f"{nome_exibido}.lrc",
                )

            # Índice de músicas (sem hashtag nas faixas -- hashtag fica no álbum)
            await atualizar_indice(app, CH_MUSICAS, nome_exibido, msg_musica.link)
            links_musicas.append((nome_limpo, msg_musica.link))

        # ── 7. Vitrine do álbum / single ────────────────────────────
        log("Montando vitrine...")

        faixas_str = "\n".join(f"▪️ [{nome}]({link})" for nome, link in links_musicas)

        if is_single:
            link_direto = links_musicas[0][1]
            legenda_album = (
                f"🎵 **{album_title}** ({ano})\n"
                f"👤 **{artista_principal}** {hash_artista}\n"
                f"🏷 #SINGLE\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎧 **[▶ Ouvir Agora]({link_direto})**\n\n"
                f"**Faixa:**\n{faixas_str}"
            )
        else:
            total = len(links_musicas)
            legenda_album = (
                f"💿 **{album_title}** ({ano})\n"
                f"👤 **{artista_principal}** {hash_artista}\n"
                f"🏷 #{tipo.upper()} · {total} faixas\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"**🎶 Faixas:**\n{faixas_str}"
            )

        # Envia vitrine (foto + legenda ou só texto se legenda > 1 024 chars)
        if tem_capa and len(legenda_album) <= 1024:
            msg_album = await app.send_photo(
                chat_id=CH_ALBUNS,
                photo=capa_path,
                caption=legenda_album,
            )
        else:
            if tem_capa:
                await app.send_photo(chat_id=CH_ALBUNS, photo=capa_path)
            msg_album = await app.send_message(
                chat_id=CH_ALBUNS,
                text=legenda_album,
                disable_web_page_preview=True,
            )

        # Índice de álbuns -- com hashtag do artista para busca nativa
        await atualizar_indice(app, CH_ALBUNS, album_title, msg_album.link, hashtag=hash_artista)

        # ── 8. ZIP do álbum completo (não para singles) ─────────────
        if not is_single:
            log("Compactando ZIP...")
            zip_base = str(Path(dir_album))
            shutil.make_archive(zip_base, "zip", dir_album)
            zip_path   = f"{zip_base}.zip"
            tam_zip_mb = os.path.getsize(zip_path) / 1024 / 1024

            await app.send_document(
                chat_id=CH_ALBUNS,
                document=zip_path,
                caption=(
                    f"📦 **Download Completo -- {album_title}**\n"
                    f"👤 {artista_principal} {hash_artista}\n"
                    f"📁 {tam_zip_mb:.1f} MB · todas as faixas + letras"
                ),
                file_name=f"{album_title}.zip",
                progress=progresso,
                progress_args=(f"⬆ ZIP {tam_zip_mb:.1f} MB |",),
            )
            try:
                os.remove(zip_path)
            except Exception:
                pass

        # ── 9. Página de artista (atualizada, não duplicada) ────────
        log("Atualizando página do artista...")
        msg_artista_id = await atualizar_pagina_artista(
            app,
            chat_id_artistas=CH_ARTISTAS,
            artista=artista_principal,
            hash_artista=hash_artista,
            titulo_album=album_title,
            link_album=msg_album.link,
            tipo=tipo,
        )

        # Índice de artistas -- aponta para a página do artista
        link_artista = f"https://t.me/c/{str(CH_ARTISTAS).replace('-100', '')}/{msg_artista_id}"
        await atualizar_indice(app, CH_ARTISTAS, artista_principal, link_artista, hashtag=hash_artista)

        # ── 10. Limpeza ─────────────────────────────────────────────
        if capa_temporaria and os.path.exists(capa_path):
            try:
                os.remove(capa_path)
            except Exception:
                pass

        # ── 11. Log em tempo real + resumo diário (Canal Geral) ─────
        if CH_GERAL:
            log("Enviando log para o canal Geral...")

            # Determina qualidade a partir dos arquivos baixados
            amostra = arquivos_audio[0] if arquivos_audio else ""
            if amostra.lower().endswith(".mp3"):
                qualidade_str = "MP3 320kbps"
            else:
                try:
                    from mutagen.flac import FLAC as _FLAC
                    _audio = _FLAC(amostra)
                    _info  = _audio.info
                    qualidade_str = f"FLAC {_info.bits_per_sample}bit/{int(_info.sample_rate / 1000)}kHz"
                except Exception:
                    qualidade_str = "FLAC"

            # Registra no log diário em disco
            _registrar_entrada_log(
                album_title = album_title,
                artista     = artista_principal,
                ano         = ano,
                tipo        = tipo,
                qualidade   = qualidade_str,
                n_faixas    = len(arquivos_audio),
                link_album  = msg_album.link,
            )

            # Log imediato (foto + texto)
            capa_para_log = capa_path if (tem_capa and not capa_temporaria) else None
            await enviar_log_tempo_real(
                app, CH_GERAL,
                album_title, artista_principal, ano, tipo,
                qualidade_str, len(arquivos_audio),
                msg_album.link, capa_para_log,
            )

            # Atualiza (ou cria) o resumo do dia -- uma única mensagem editável
            await enviar_resumo_diario(app, CH_GERAL)

    log_ok(f"'{album_title}' catalogado com sucesso!")