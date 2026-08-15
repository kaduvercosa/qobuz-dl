"""
utils_delivery.py
------------------
Suporte para o endpoint GET /api/download/{job_id}/file: junta os arquivos
que o job baixou em job.job_dir (ver JOBS_ROOT em qobuz_service.py), entrega
pro navegador (arquivo único ou .zip) e, assim que a resposta termina de ser
enviada, apaga tudo do servidor -- nada fica guardado depois do download.
"""
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional

from qobuz_dl.utils import clean_filename

# extensões/arquivos que não fazem parte do conteúdo baixado (temporários,
# metadados do SO etc.) -- não entram no zip nem contam pra decidir se é
# "arquivo único"
_IGNORED_SUFFIXES = {".part", ".tmp", ".ytdl"}
_IGNORED_NAMES = {".DS_Store", "Thumbs.db"}


def collect_files(job_dir: Path) -> List[Path]:
    """Lista (recursivamente) os arquivos reais baixados dentro de job_dir."""
    if not job_dir.exists():
        return []
    out = []
    for p in job_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.name in _IGNORED_NAMES or p.suffix in _IGNORED_SUFFIXES:
            continue
        out.append(p)
    return sorted(out)


def build_zip(job_dir: Path, zip_stem: str, files: List[Path]) -> Path:
    """Cria um .zip (fora de job_dir, em outro temp dir) com os arquivos,
    preservando a estrutura de pastas relativa a job_dir (ex.: Artista/Álbum/
    01 - Faixa.flac). Retorna o caminho do .zip criado."""
    zip_dir = Path(tempfile.mkdtemp(prefix="qbdl_zip_"))
    zip_path = zip_dir / f"{zip_stem}.zip"
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_STORED) as zf:
        # ZIP_STORED (sem recompressão) porque FLAC/Hi-Res já vem comprimido --
        # recomprimir só gastaria CPU/tempo à toa por praticamente nada de ganho.
        for f in files:
            zf.write(f, arcname=str(f.relative_to(job_dir)))
    return zip_path


def build_download_filename(job) -> str:
    """Monta um nome de arquivo/zip legível a partir do que o job baixou --
    em vez de sempre 'FIXME.zip' ou o job_id cru. Exemplos:
      "Tame Impala - Currents (2015) [Hi-Res].zip"
      "Kendrick Lamar - To Pimp a Butterfly.zip"          (sem ano/hi-res quando não sabido)
      "Selecionadas.zip"                                   (playlist, sem artista único)
    """
    base = (job.content_name or "").strip() or job.id
    if job.artist and job.content_type in ("album", "track"):
        name = f"{job.artist} - {base}"
    else:
        name = base
    if job.year:
        name += f" ({job.year})"
    if job.hires:
        name += " [Hi-Res]"
    cleaned = clean_filename(name)
    return cleaned or job.id


def cleanup_job(job, zip_path: Optional[Path] = None) -> None:
    """Chamado depois que a resposta HTTP já foi 100% enviada pro cliente
    (via BackgroundTask do Starlette) -- apaga a pasta do job e o .zip
    temporário (se houver), e marca o job como sem arquivos disponíveis."""
    if job.job_dir:
        shutil.rmtree(job.job_dir, ignore_errors=True)
    if zip_path is not None:
        shutil.rmtree(zip_path.parent, ignore_errors=True)
    job.job_dir = None
