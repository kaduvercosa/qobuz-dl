import re
import os
import unicodedata

def sanitize_filename(name: str, max_length: int = 180) -> str:
    """Sanitize strings for safe filesystem storage across Linux, macOS and Windows (FAT32/NTFS)."""
    if not name:
        return "Unknown"
    # Normalize unicode
    name = unicodedata.normalize("NFKC", str(name))
    # Replace illegal characters with underscore or safe equivalents
    name = re.sub(r'[\\/*?:"<>|]', "-", name)
    # Remove control characters
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    # Strip whitespace and trailing dots
    name = name.strip(" .")
    if len(name) > max_length:
        name = name[:max_length].rstrip(" .")
    return name or "Unknown"

def format_bytes(size_bytes: float) -> str:
    """Format bytes to human readable string (KB, MB, GB)."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    size = float(size_bytes)
    while size >= 1024 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1
    return f"{size:.2f} {units[unit_idx]}"

def format_speed(bytes_per_sec: float) -> str:
    """Format download speed to human readable string."""
    return f"{format_bytes(bytes_per_sec)}/s"

def format_duration(seconds: float) -> str:
    """Format duration into mm:ss or hh:mm:ss."""
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def get_quality_badge(bit_depth: int, sample_rate: float) -> str:
    """Return Nothing-style Hi-Res / Lossless quality badge."""
    if bit_depth and bit_depth >= 24:
        sr_khz = sample_rate / 1000.0 if sample_rate > 1000 else sample_rate
        return f"HI-RES • {bit_depth}B/{sr_khz:g}kHz"
    elif bit_depth and bit_depth == 16:
        return "CD QUALITY • 16B/44.1kHz"
    return "MP3 • 320kbps"

def format_path(template: str, meta: dict, max_len: int = 180) -> str:
    """Resolve template variables into a sanitized path string."""
    artist = sanitize_filename(meta.get('artist') or meta.get('album_artist') or 'Unknown Artist')
    album = sanitize_filename(meta.get('album') or 'Unknown Album')
    title = sanitize_filename(meta.get('title') or 'Unknown Track')
    year = str(meta.get('year') or meta.get('release_date_original') or 'Unknown')[:4]
    quality = sanitize_filename(meta.get('quality') or meta.get('quality_str') or 'Lossless')
    track_num = int(meta.get('track_number') or 1)
    disc_num = int(meta.get('disc_number') or meta.get('media_number') or 1)
    genre = sanitize_filename(meta.get('genre') or 'Music')
    label = sanitize_filename(meta.get('label') or 'Unknown Label')

    res = template
    res = res.replace('{artist}', artist)
    res = res.replace('{album}', album)
    res = res.replace('{title}', title)
    res = res.replace('{year}', year)
    res = res.replace('{quality}', quality)
    res = res.replace('{track_number:02d}', f'{track_num:02d}')
    res = res.replace('{track_number}', str(track_num))
    res = res.replace('{disc_number:02d}', f'{disc_num:02d}')
    res = res.replace('{disc_number}', str(disc_num))
    res = res.replace('{genre}', genre)
    res = res.replace('{label}', label)
    
    parts = res.split('/')
    sanitized_parts = [sanitize_filename(p, max_length=max_len) for p in parts if p.strip()]
    return os.path.join(*sanitized_parts) if sanitized_parts else 'Unknown'
