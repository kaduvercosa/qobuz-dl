"""
Duplicate Detector Module
Scans local library for duplicate albums/tracks with different versions/qualities
Provides intelligent comparison and management suggestions
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError
from qobuz_dl.color import GREEN, RED, YELLOW, CYAN, OFF

logger = logging.getLogger(__name__)


class DuplicateChecker:
    """Detects and manages duplicate albums/tracks in local library"""
    
    # Version keywords that indicate special editions
    VERSION_KEYWORDS = {
        'remaster': 5,
        'remastered': 5,
        'deluxe': 4,
        'deluxe edition': 4,
        'live': 3,
        'remix': 2,
        'cover': 1,
        'instrumental': 1,
        'karaoke': 0,  # Skip these
    }
    
    def __init__(self, library_path: str):
        self.library_path = Path(library_path)
        self.duplicates: Dict[str, List[Dict]] = {}
        self.duplicates_by_isrc: Dict[str, List[Dict]] = {}
        
    def scan_library(self) -> Dict:
        """Scan library and detect duplicates"""
        logger.info(f"{CYAN}[*] Scanning library for duplicates...{OFF}")
        
        albums_by_id = {}
        tracks_by_isrc = {}
        tracks_by_name = {}
        
        for root, dirs, files in os.walk(self.library_path):
            for file in files:
                if file.lower().endswith(('.flac', '.mp3')):
                    file_path = os.path.join(root, file)
                    metadata = self._extract_metadata(file_path)
                    
                    if not metadata:
                        continue
                    
                    # Group by album ID (primary)
                    album_id = metadata.get('album_id')
                    if album_id:
                        if album_id not in albums_by_id:
                            albums_by_id[album_id] = []
                        albums_by_id[album_id].append(metadata)
                    
                    # Group by ISRC (track fingerprint)
                    isrc = metadata.get('isrc')
                    if isrc:
                        if isrc not in tracks_by_isrc:
                            tracks_by_isrc[isrc] = []
                        tracks_by_isrc[isrc].append(metadata)
                    
                    # Group by album + artist (fuzzy matching)
                    key = f"{metadata.get('album_artist', 'Unknown')} - {metadata.get('album', 'Unknown')}".lower()
                    if key not in tracks_by_name:
                        tracks_by_name[key] = []
                    tracks_by_name[key].append(metadata)
        
        # Find duplicates
        self._find_album_duplicates(albums_by_id)
        self._find_track_duplicates(tracks_by_isrc)
        self._find_version_duplicates(tracks_by_name)
        
        return self._generate_report()
    
    def _extract_metadata(self, file_path: str) -> Dict:
        """Extract metadata from FLAC or MP3"""
        try:
            metadata = {
                'path': file_path,
                'filename': os.path.basename(file_path),
                'filesize_mb': os.path.getsize(file_path) / (1024 * 1024),
            }
            
            if file_path.lower().endswith('.flac'):
                audio = FLAC(file_path)
                metadata.update(self._parse_flac_tags(audio))
                metadata['format'] = 'FLAC'
            else:  # MP3
                try:
                    audio = ID3(file_path)
                    metadata.update(self._parse_id3_tags(audio))
                except ID3NoHeaderError:
                    pass
                metadata['format'] = 'MP3'
            
            return metadata
        except Exception as e:
            logger.debug(f"Error reading metadata from {file_path}: {e}")
            return None
    
    def _parse_flac_tags(self, audio: FLAC) -> Dict:
        """Parse FLAC tags"""
        tags = {}
        tags['album_id'] = audio.get('QOBUZALBUMID', [''])[0] if audio.get('QOBUZALBUMID') else None
        tags['track_id'] = audio.get('QOBUZTRACKID', [''])[0] if audio.get('QOBUZTRACKID') else None
        tags['isrc'] = audio.get('ISRC', [''])[0] if audio.get('ISRC') else None
        tags['album'] = audio.get('ALBUM', [''])[0] if audio.get('ALBUM') else 'Unknown'
        tags['title'] = audio.get('TITLE', [''])[0] if audio.get('TITLE') else 'Unknown'
        tags['album_artist'] = audio.get('ALBUMARTIST', [''])[0] if audio.get('ALBUMARTIST') else 'Unknown'
        tags['artist'] = audio.get('ARTIST', [''])[0] if audio.get('ARTIST') else 'Unknown'
        tags['bit_depth'] = int(audio.get('BITDEPTH', ['16'])[0] or 16)
        tags['sample_rate'] = float(audio.get('SAMPLERATE', ['44.1'])[0] or 44.1)
        tags['version'] = audio.get('VERSION', [''])[0] if audio.get('VERSION') else ''
        tags['duration'] = audio.info.length if hasattr(audio, 'info') else 0
        
        # Get comment info
        if audio.get('COMMENT'):
            tags['comment'] = audio.get('COMMENT', [''])[0]
        
        return tags
    
    def _parse_id3_tags(self, audio: ID3) -> Dict:
        """Parse ID3 tags"""
        from mutagen.id3 import TALB, TIT2, TPE1, TPE2, TXXX, COMM
        
        tags = {}
        tags['album_id'] = self._get_id3_txxx(audio, 'QOBUZALBUMID')
        tags['track_id'] = self._get_id3_txxx(audio, 'QOBUZTRACKID')
        tags['isrc'] = audio.getall('TSRC')[0].text[0] if audio.getall('TSRC') else None
        tags['album'] = audio.get('TALB').text[0] if audio.get('TALB') else 'Unknown'
        tags['title'] = audio.get('TIT2').text[0] if audio.get('TIT2') else 'Unknown'
        tags['album_artist'] = audio.get('TPE2').text[0] if audio.get('TPE2') else 'Unknown'
        tags['artist'] = audio.get('TPE1').text[0] if audio.get('TPE1') else 'Unknown'
        tags['bit_depth'] = int(self._get_id3_txxx(audio, 'BITDEPTH') or 16)
        tags['sample_rate'] = float(self._get_id3_txxx(audio, 'SAMPLERATE') or 44.1)
        tags['version'] = self._get_id3_txxx(audio, 'VERSION') or ''
        tags['duration'] = audio.info.length if hasattr(audio, 'info') else 0
        
        # Get comment
        if audio.getall('COMM'):
            tags['comment'] = audio.getall('COMM')[0].text[0]
        
        return tags
    
    @staticmethod
    def _get_id3_txxx(audio: ID3, desc: str) -> str:
        """Extract TXXX value from ID3"""
        from mutagen.id3 import TXXX
        for frame in audio.getall('TXXX'):
            if frame.desc == desc:
                return frame.text[0] if frame.text else None
        return None
    
    def _find_album_duplicates(self, albums_by_id: Dict):
        """Find albums with same ID but different files"""
        for album_id, files in albums_by_id.items():
            if len(files) > 1:
                self.duplicates[f"album_{album_id}"] = files
    
    def _find_track_duplicates(self, tracks_by_isrc: Dict):
        """Find tracks with same ISRC but different quality"""
        for isrc, files in tracks_by_isrc.items():
            if len(files) > 1 and isrc:
                self.duplicates[f"isrc_{isrc}"] = files
    
    def _find_version_duplicates(self, tracks_by_name: Dict):
        """Find albums with different versions (Remaster vs Original, Deluxe vs Standard)"""
        for album_key, files in tracks_by_name.items():
            if len(files) > 1:
                # Check if different versions exist
                versions = set()
                for f in files:
                    version = f.get('version', '').lower()
                    versions.add(version if version else 'original')
                
                if len(versions) > 1:
                    self.duplicates[f"version_{album_key}"] = files
    
    def _generate_report(self) -> Dict:
        """Generate detailed duplicate report"""
        report = {
            'total_duplicates': len(self.duplicates),
            'details': []
        }
        
        for dup_key, files in self.duplicates.items():
            # Sort by quality (highest first)
            sorted_files = sorted(
                files,
                key=lambda x: (x.get('bit_depth', 16), x.get('sample_rate', 44.1)),
                reverse=True
            )
            
            dup_info = {
                'type': dup_key.split('_')[0],  # album, isrc, version
                'files': [],
                'recommendation': self._get_recommendation(sorted_files)
            }
            
            for i, f in enumerate(sorted_files):
                file_info = {
                    'rank': i + 1,
                    'path': f['path'],
                    'filename': f['filename'],
                    'format': f.get('format', 'Unknown'),
                    'quality': f"{f.get('bit_depth', 16)}-bit / {f.get('sample_rate', 44.1)} kHz",
                    'filesize_mb': round(f.get('filesize_mb', 0), 2),
                    'version': f.get('version', 'Original'),
                    'duration_sec': round(f.get('duration', 0), 2),
                }
                dup_info['files'].append(file_info)
            
            report['details'].append(dup_info)
        
        return report
    
    @staticmethod
    def _get_recommendation(sorted_files: List[Dict]) -> Dict:
        """Get action recommendation"""
        if not sorted_files:
            return {'action': 'skip', 'reason': 'No files to compare'}
        
        best = sorted_files[0]
        others = sorted_files[1:]
        
        # Check quality difference
        quality_diff = best.get('bit_depth', 16) - others[0].get('bit_depth', 16) if others else 0
        sample_diff = best.get('sample_rate', 44.1) - others[0].get('sample_rate', 44.1) if others else 0
        
        recommendation = {
            'action': 'keep',
            'keep_file': best['filename'],
            'reason': f"Best quality: {best.get('bit_depth', 16)}-bit / {best.get('sample_rate', 44.1)} kHz"
        }
        
        if quality_diff == 0 and sample_diff == 0:
            recommendation['action'] = 'review'
            recommendation['reason'] = 'Same quality - check version/edition'
        
        if others:
            recommendation['delete_files'] = [f['filename'] for f in others]
            recommendation['potential_space_saved_mb'] = round(sum(f.get('filesize_mb', 0) for f in others), 2)
        
        return recommendation
    
    def display_report(self, report: Dict):
        """Display duplicate report in terminal"""
        if report['total_duplicates'] == 0:
            logger.info(f"{GREEN}[✓] No duplicates found!{OFF}")
            return
        
        logger.info(f"\n{YELLOW}Found {report['total_duplicates']} duplicate groups{OFF}\n")
        
        for i, dup in enumerate(report['details'], 1):
            logger.info(f"{CYAN}--- Duplicate Group {i} ({dup['type'].upper()}) ---{OFF}")
            
            for file_info in dup['files']:
                rank_symbol = "🥇" if file_info['rank'] == 1 else "🥈" if file_info['rank'] == 2 else "🥉"
                logger.info(f"  {rank_symbol} Rank {file_info['rank']}: {file_info['filename']}")
                logger.info(f"     Quality: {file_info['quality']} | Format: {file_info['format']}")
                logger.info(f"     Size: {file_info['filesize_mb']} MB | Version: {file_info['version']}")
            
            rec = dup['recommendation']
            if rec['action'] == 'keep':
                logger.info(f"  {GREEN}➜ Action: KEEP '{rec['keep_file']}'{OFF}")
                logger.info(f"     {GREEN}Reason: {rec['reason']}{OFF}")
                if 'delete_files' in rec:
                    logger.info(f"     {RED}Delete: {', '.join(rec['delete_files'])}{OFF}")
                    if 'potential_space_saved_mb' in rec:
                        logger.info(f"     {YELLOW}Space saved: ~{rec['potential_space_saved_mb']} MB{OFF}")
            elif rec['action'] == 'review':
                logger.info(f"  {YELLOW}⚠ Action: REVIEW MANUALLY{OFF}")
                logger.info(f"     {YELLOW}Reason: {rec['reason']}{OFF}")
            
            logger.info("")
    
    def export_report(self, report: Dict, output_format: str = 'json', output_path: str = None):
        """Export report to JSON or CSV"""
        if output_path is None:
            output_path = self.library_path / f"duplicates_report.{output_format}"
        
        output_path = Path(output_path)
        
        try:
            if output_format == 'json':
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(report, f, indent=2, ensure_ascii=False)
            elif output_format == 'csv':
                import csv
                with open(output_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Group', 'Rank', 'Filename', 'Quality', 'Format', 'Size MB', 'Action'])
                    
                    for i, dup in enumerate(report['details'], 1):
                        rec = dup['recommendation']
                        for file_info in dup['files']:
                            action = 'KEEP' if file_info['filename'] == rec.get('keep_file') else 'DELETE'
                            writer.writerow([
                                i,
                                file_info['rank'],
                                file_info['filename'],
                                file_info['quality'],
                                file_info['format'],
                                file_info['filesize_mb'],
                                action
                            ])
            
            logger.info(f"{GREEN}[✓] Report exported to: {output_path}{OFF}")
        except Exception as e:
            logger.error(f"{RED}[!] Error exporting report: {e}{OFF}")
