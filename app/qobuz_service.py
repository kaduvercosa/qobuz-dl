"""
qobuz_service.py
-----------------
Ponte entre a API web e a classe QobuzDL do seu fork (core.py). Não duplica
lógica de download/tag -- isso continua 100% dentro de `downloader.py` e
`metadata.py`, testados no seu fork. O que existe aqui é só:

  1. uma sessão QobuzDL única, autenticada uma vez (login) e reutilizada;
  2. `search_json()` -- mesma busca do `client`, mas devolvendo dicts prontos
     pra JSON (o `search_by_type` do core.py é pensado pra tabela no
     terminal, então aqui a gente chama `client.search_*` direto);
  3. `run_download_job()` -- uma versão da lógica de `QobuzDL.handle_url`
     que emite eventos de progresso (faixa atual / total) entre cada
     `download_from_id`, mantendo a MESMA função de download por baixo.
"""
import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from qobuz_dl.core import QobuzDL, classificar_tipo_lancamento
from qobuz_dl.bundle import Bundle
from qobuz_dl.utils import get_url_info, clean_filename, create_and_return_dir
from qobuz_dl.settings import QobuzDLSettings

from .progress import Job, current_job

# Raiz onde cada job baixa para uma subpasta isolada (job_id), em vez de
# escrever direto no download_dir "definitivo". Isso é o que permite ao
# endpoint /api/download/{job_id}/file entregar o zip/arquivo pro navegador
# e depois apagar tudo do servidor, sem risco de mexer em arquivos de outro
# job ou em uma biblioteca já existente.
JOBS_ROOT = Path(tempfile.gettempdir()) / "qbdl_jobs"


def cleanup_stale_job_dirs() -> None:
    """Remove pastas de jobs de execuções anteriores (ex.: server reiniciou
    antes do usuário baixar o resultado). Chamado uma vez no startup."""
    if JOBS_ROOT.exists():
        shutil.rmtree(JOBS_ROOT, ignore_errors=True)
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)


class QobuzSession:
    def __init__(self):
        self.client_wrapper: Optional[QobuzDL] = None
        self.logged_in: bool = False

    async def login(self, download_dir: str = "FLAC", quality: int = 7,
                     user_auth_token: Optional[str] = None,
                     email: Optional[str] = None, password: Optional[str] = None) -> None:
        """Prioriza login por user_auth_token (mesmo caminho que o cli.py já usa --
        `qopy.Client.auth()` ignora email/senha quando um token é passado).
        Email/senha ficam como fallback, só pra quem preferir esse caminho."""
        if not user_auth_token and not (email and password):
            raise ValueError("Informe user_auth_token OU email+password.")

        settings = QobuzDLSettings(email=email or "", password="", user_auth_token=user_auth_token or "")
        qdl = QobuzDL(directory=download_dir, quality=quality, settings=settings)
        qdl.get_tokens()  # extrai app_id/secrets do bundle oficial do Qobuz (mesma lógica do CLI)
        # qopy.Client.auth() checa nesta ordem: settings.user_auth_token -> pwd com +60 chars -> email+senha
        await qdl.initialize_client(email or "", password or "", qdl.app_id, qdl.secrets)
        self.client_wrapper = qdl
        self.logged_in = True

    def _require_client(self) -> QobuzDL:
        if not self.logged_in or self.client_wrapper is None:
            raise RuntimeError("Sessão não autenticada. Chame /api/login primeiro.")
        return self.client_wrapper

    # ---------------------------------------------------------------- busca
    async def search_json(self, query: str, item_type: str, limit: int = 20) -> list[dict]:
        qdl = self._require_client()
        client = qdl.client

        funcs = {
            "album": client.search_albums,
            "artist": client.search_artists,
            "track": client.search_tracks,
            "playlist": client.search_playlists,
        }
        keys = {"album": "albums", "artist": "artists", "track": "tracks", "playlist": "playlists"}
        if item_type not in funcs:
            raise ValueError(f"item_type inválido: {item_type}")

        results = await funcs[item_type](query, limit)
        key = keys[item_type]
        if not results or key not in results or "items" not in results[key]:
            return []

        out = []
        for i in results[key]["items"]:
            if item_type in ("album", "track"):
                r_type = classificar_tipo_lancamento(
                    raw_type=i.get("release_type") or i.get("product_type"),
                    title=str(i.get("title", "")), version=str(i.get("version", "")),
                    t_count=i.get("tracks_count", 0), duration=i.get("duration", 0),
                ) if item_type == "album" else "track"
                out.append({
                    "id": str(i.get("id")),
                    "type": item_type,
                    "release_type": r_type,
                    "title": i.get("title") or i.get("name") or "Unknown",
                    "version": i.get("version"),
                    "artist": (i.get("artist") or i.get("performer") or {}).get("name", "Unknown"),
                    "album": (i.get("album") or {}).get("title") if item_type == "track" else None,
                    "year": str(i.get("release_date_original") or i.get("release_date") or "")[:4],
                    "duration_seconds": i.get("duration"),
                    "tracks_count": i.get("tracks_count"),
                    "hires": bool(i.get("hires_streamable")),
                    "bit_depth": i.get("maximum_bit_depth", 16),
                    "sampling_rate": i.get("maximum_sampling_rate", 44.1),
                    "cover_url": (i.get("image") or {}).get("large") or (i.get("album") or {}).get("image", {}).get("large"),
                })
            else:
                out.append({
                    "id": str(i.get("id")),
                    "type": item_type,
                    "title": i.get("name") or i.get("title") or "Unknown",
                    "owner": (i.get("owner") or {}).get("name"),
                    "tracks_count": i.get("tracks_count") or i.get("albums_count"),
                    "cover_url": (i.get("image") or {}).get("large"),
                })
        return out

    async def get_album_tracks(self, album_id: str) -> list[dict]:
        qdl = self._require_client()
        meta = await qdl.client.get_album_meta(album_id)
        items = meta.get("tracks", {}).get("items", [])
        return [{
            "id": str(t.get("id")),
            "title": t.get("title"),
            "version": t.get("version"),
            "track_number": t.get("track_number"),
            "duration_seconds": t.get("duration"),
            "hires": bool(t.get("hires_streamable")),
        } for t in items]

    # --------------------------------------------------------- preview/link
    # "Preview" = mesma ideia do search_json, só que devolvendo o
    # item INTEIRO (capa grande, lista completa de faixas com duração/hi-res
    # de cada uma, etc.) -- é o que alimenta a tela de "colar link" e o
    # clique num resultado de busca no frontend.

    @staticmethod
    def _fmt_track(t: dict) -> dict:
        return {
            "id": str(t.get("id")),
            "number": t.get("track_number"),
            "title": t.get("title") or t.get("name") or "Unknown",
            "version": t.get("version"),
            "artist": (t.get("performer") or {}).get("name") or (t.get("artist") or {}).get("name"),
            "duration_seconds": t.get("duration"),
            "hires": bool(t.get("hires_streamable")),
            "bit_depth": t.get("maximum_bit_depth"),
            "sampling_rate": t.get("maximum_sampling_rate"),
        }

    def _normalize_track(self, t: dict) -> dict:
        album = t.get("album") or {}
        return {
            "type": "track",
            "id": str(t.get("id")),
            "title": t.get("title") or "Unknown",
            "version": t.get("version"),
            "artist": (t.get("performer") or {}).get("name") or (album.get("artist") or {}).get("name", "Unknown"),
            "album_title": album.get("title"),
            "cover_url": (album.get("image") or {}).get("large"),
            "year": str(album.get("release_date_original") or "")[:4],
            "genre": (album.get("genre") or {}).get("name"),
            "duration_seconds": t.get("duration"),
            "tracks_count": 1,
            "hires": bool(t.get("hires_streamable")),
            "bit_depth": t.get("maximum_bit_depth"),
            "sampling_rate": t.get("maximum_sampling_rate"),
            "tracks": [self._fmt_track(t)],
        }

    def _normalize_album(self, meta: dict) -> dict:
        tracks = meta.get("tracks", {}).get("items", [])
        return {
            "type": "album",
            "id": str(meta.get("id")),
            "title": meta.get("title") or "Unknown",
            "version": meta.get("version"),
            "artist": (meta.get("artist") or {}).get("name", "Unknown"),
            "cover_url": (meta.get("image") or {}).get("large"),
            "year": str(meta.get("release_date_original") or meta.get("release_date") or "")[:4],
            "genre": (meta.get("genre") or {}).get("name"),
            "label": (meta.get("label") or {}).get("name"),
            "duration_seconds": meta.get("duration"),
            "tracks_count": meta.get("tracks_count", len(tracks)),
            "hires": bool(meta.get("hires_streamable")),
            "bit_depth": meta.get("maximum_bit_depth"),
            "sampling_rate": meta.get("maximum_sampling_rate"),
            "tracks": [self._fmt_track(t) for t in tracks],
        }

    @staticmethod
    def _pick_cover(item_type: str, head: dict, items: list) -> Optional[str]:
        if item_type == "artist":
            return (head.get("image") or {}).get("large")
        if item_type == "playlist":
            imgs = head.get("images300") or head.get("images") or []
            if isinstance(imgs, list) and imgs:
                return imgs[0]
            if items:
                return ((items[0].get("album") or {}).get("image") or {}).get("large")
            return None
        if item_type == "label" and items:
            return (items[0].get("image") or {}).get("large")
        return None

    def _normalize_playlist(self, head: dict, items: list) -> dict:
        total_dur = sum(it.get("duration") or 0 for it in items)
        return {
            "type": "playlist",
            "id": str(head.get("id")),
            "title": head.get("name") or "Unknown",
            "owner": (head.get("owner") or {}).get("name"),
            "cover_url": self._pick_cover("playlist", head, items),
            "duration_seconds": total_dur,
            "tracks_count": head.get("tracks_count", len(items)),
            "hires": any(bool(it.get("hires_streamable")) for it in items),
            "tracks": [self._fmt_track(it) for it in items],
        }

    def _normalize_artist_or_label(self, item_type: str, head: dict, items: list) -> dict:
        return {
            "type": item_type,
            "id": str(head.get("id")),
            "title": head.get("name") or "Unknown",
            "cover_url": self._pick_cover(item_type, head, items),
            "albums_count": head.get("albums_count", len(items)),
            "albums": [{
                "id": str(al.get("id")),
                "title": al.get("title") or "Unknown",
                "version": al.get("version"),
                "cover_url": (al.get("image") or {}).get("large"),
                "year": str(al.get("release_date_original") or "")[:4],
                "tracks_count": al.get("tracks_count"),
                "hires": bool(al.get("hires_streamable")),
            } for al in items],
        }

    async def preview_by_id(self, item_type: str, item_id: str) -> dict:
        qdl = self._require_client()
        client = qdl.client
        if item_type == "track":
            return self._normalize_track(await client.get_track_meta(item_id))
        if item_type == "album":
            return self._normalize_album(await client.get_album_meta(item_id))
        if item_type in ("playlist", "artist", "label"):
            fetch_map = {
                "playlist": client.get_plist_meta,
                "artist": client.get_artist_meta,
                "label": client.get_label_meta,
            }
            iterable_key = "tracks" if item_type == "playlist" else "albums"
            chunks = [c async for c in fetch_map[item_type](item_id)]
            head = chunks[0] if chunks else {}
            items = [it for c in chunks for it in c.get(iterable_key, {}).get("items", [])]
            if item_type == "playlist":
                return self._normalize_playlist(head, items)
            return self._normalize_artist_or_label(item_type, head, items)
        raise ValueError(f"item_type inválido: {item_type}")

    async def resolve_url(self, url: str) -> dict:
        url_type, item_id = get_url_info(url)
        result = await self.preview_by_id(url_type, item_id)
        result["source_url"] = url
        return result

    # ------------------------------------------------------------ download
    async def run_download_job(self, job: Job) -> None:
        """Reimplementa o roteamento de QobuzDL.handle_url, mas chamando
        job.set_track(...)/job.emit() entre itens. A função que efetivamente
        baixa e tagueia o arquivo continua sendo QobuzDL.download_from_id
        (downloader.py + metadata.py do seu fork), sem alterações."""
        token = current_job.set(job)
        qdl = self._require_client()
        job.status = "running"

        # Pasta exclusiva deste job -- nada é escrito no download_dir global.
        job_dir = JOBS_ROOT / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        job.job_dir = str(job_dir)
        job.emit()
        try:
            url_type, item_id = get_url_info(job.url)

            if url_type in ("album", "track"):
                job.content_type = url_type
                job.content_name = f"{url_type.title()} {item_id}"
                try:
                    preview = await self.preview_by_id(url_type, item_id)
                    job.content_name = preview.get("title") or job.content_name
                    job.artist = preview.get("artist")
                    job.cover_url = preview.get("cover_url")
                    job.content_tracks_count = preview.get("tracks_count")
                    job.year = preview.get("year") or None
                    job.hires = bool(preview.get("hires"))
                except Exception:
                    pass  # não é crítico -- se falhar, o download segue normalmente
                job.set_track(job.content_name, 1, 1)
                await qdl.download_from_id(item_id, album=(url_type == "album"), alt_path=str(job_dir))

            elif url_type in ("playlist", "artist", "label"):
                fetch_map = {
                    "playlist": (qdl.client.get_plist_meta, "tracks"),
                    "artist": (qdl.client.get_artist_meta, "albums"),
                    "label": (qdl.client.get_label_meta, "albums"),
                }
                func, iterable_key = fetch_map[url_type]
                content = [chunk async for chunk in func(item_id)]
                content_name = content[0]["name"]
                job.content_name = content_name
                job.content_type = url_type
                job.cover_url = self._pick_cover(url_type, content[0] if content else {}, [])
                if url_type == "playlist":
                    job.artist = (content[0].get("owner") or {}).get("name") if content else None

                items = [it for chunk in content for it in chunk.get(iterable_key, {}).get("items", [])]
                job.track_total = len(items)
                job.content_tracks_count = len(items)
                job.hires = any(bool(it.get("hires_streamable")) for it in items)

                is_playlist = url_type == "playlist"
                # bug corrigido: a função certa é clean_filename (sanitize_filename
                # nunca existiu em qobuz_dl.utils -- isso derrubava esse branch inteiro)
                new_path = create_and_return_dir(
                    str(job_dir / ("Playlist" if is_playlist else "") / clean_filename(content_name))
                )

                for idx, item in enumerate(items, start=1):
                    name = item.get("title") or item.get("name") or f"item {idx}"
                    job.set_track(name, idx, len(items))
                    await qdl.download_from_id(
                        item["id"],
                        album=(iterable_key == "albums"),
                        alt_path=new_path,
                        is_playlist=is_playlist,
                        playlist_index=idx,
                    )
            else:
                raise ValueError(f"Tipo de URL não suportado: {url_type}")

            job.status = "done"
            job.emit()
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.emit()
            shutil.rmtree(job_dir, ignore_errors=True)
            job.job_dir = None
            raise
        except Exception as exc:  # noqa: BLE001 -- reportar qualquer erro pro cliente via WS
            job.status = "error"
            job.error = str(exc)
            job.emit()
            # não deixa lixo no disco se o download falhou no meio
            shutil.rmtree(job_dir, ignore_errors=True)
            job.job_dir = None
        finally:
            current_job.reset(token)


session = QobuzSession()
