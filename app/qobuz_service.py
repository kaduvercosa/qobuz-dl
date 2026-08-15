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
from pathlib import Path
from typing import Optional

from qobuz_dl.core import QobuzDL, classificar_tipo_lancamento
from qobuz_dl.bundle import Bundle
from qobuz_dl.utils import get_url_info, sanitize_filename, create_and_return_dir
from qobuz_dl.settings import QobuzDLSettings

from .progress import Job, current_job


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

    # ------------------------------------------------------------ download
    async def run_download_job(self, job: Job) -> None:
        """Reimplementa o roteamento de QobuzDL.handle_url, mas chamando
        job.set_track(...)/job.emit() entre itens. A função que efetivamente
        baixa e tagueia o arquivo continua sendo QobuzDL.download_from_id
        (downloader.py + metadata.py do seu fork), sem alterações."""
        token = current_job.set(job)
        qdl = self._require_client()
        job.status = "running"
        job.emit()
        try:
            url_type, item_id = get_url_info(job.url)

            if url_type in ("album", "track"):
                job.content_name = f"{url_type.title()} {item_id}"
                job.set_track(job.content_name, 1, 1)
                await qdl.download_from_id(item_id, album=(url_type == "album"))

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

                items = [it for chunk in content for it in chunk.get(iterable_key, {}).get("items", [])]
                job.track_total = len(items)

                is_playlist = url_type == "playlist"
                base_dir = qdl.directory
                new_path = create_and_return_dir(
                    str(Path(base_dir) / ("Playlist" if is_playlist else "") / sanitize_filename(content_name))
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
        except Exception as exc:  # noqa: BLE001 -- reportar qualquer erro pro cliente via WS
            job.status = "error"
            job.error = str(exc)
            job.emit()
        finally:
            current_job.reset(token)


session = QobuzSession()
