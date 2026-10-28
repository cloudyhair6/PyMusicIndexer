"""
Scanner Module & Smart Incremental HDD Engine
=============================================
Traverses directories, utilizes filesystem timestamps for near-instant
smart cache validation on slow hard drives, extracts metadata only for
new/modified files, applies VLC fingerprinting for incomplete tags,
and categorizes files into songs and unindexed/failed records.
"""

from __future__ import annotations

import os
import time
import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Callable, Set, Tuple

from .metadata import (
    MetadataExtractor,
    AudioMetadata,
    VLCMetadataEnricher,
    AUDIO_EXTENSIONS,
    format_file_size,
)


@dataclass
class FileScanStatus:
    """Record of a file that was examined, particularly non-songs or failures."""
    file_path: str
    file_name: str
    file_size_bytes: int
    file_size_human: str
    extension: str
    is_song: bool
    reason: str
    error_details: Optional[str] = None
    last_modified: str = ""
    mtime_timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileScanStatus":
        safe_data = dict(data)
        safe_data.setdefault("mtime_timestamp", 0.0)
        return cls(**safe_data)


@dataclass
class ScanResult:
    """Container for the full outcome of a folder scan."""
    folders: List[str]
    total_files_examined: int
    songs: List[AudioMetadata]
    unindexed_files: List[FileScanStatus]
    elapsed_time_seconds: float
    started_at: str
    finished_at: str
    new_files_count: int = 0
    modified_files_count: int = 0
    cached_files_count: int = 0
    deleted_files_count: int = 0

    @property
    def song_count(self) -> int:
        return len(self.songs)

    @property
    def unindexed_count(self) -> int:
        return len(self.unindexed_files)

    @property
    def incomplete_count(self) -> int:
        return sum(1 for s in self.songs if s.has_incomplete_metadata)

    def summary(self) -> str:
        lines = [
            "=" * 55,
            "               INDEXING SUMMARY",
            "=" * 55,
            f"Folders scanned:          {len(self.folders)}",
            f"Total files on disk:      {self.total_files_examined}",
            f"Songs indexed:            {self.song_count}",
            f"  - Complete songs:       {self.song_count - self.incomplete_count}",
            f"  - Incomplete metadata:  {self.incomplete_count}",
            f"Unindexed / other files:  {self.unindexed_count}",
            f"Smart Cache Stats:",
            f"  - Unchanged (cached):   {self.cached_files_count} (0 disk reads)",
            f"  - New files indexed:    {self.new_files_count}",
            f"  - Modified files:       {self.modified_files_count}",
            f"  - Removed / deleted:    {self.deleted_files_count}",
            f"Time elapsed:             {self.elapsed_time_seconds:.2f}s",
            "=" * 55,
        ]
        return "\n".join(lines)


class AudioIndexer:
    """
    Crawls folders, extracts song metadata, tracks failures, and features
    a smart incremental refresh engine optimized for slow mechanical HDDs.
    """

    def __init__(self, audio_extensions: Optional[Set[str]] = None, enable_vlc_enrichment: bool = True):
        self.audio_extensions = audio_extensions or AUDIO_EXTENSIONS
        self.enable_vlc_enrichment = enable_vlc_enrichment

    def discover_files_fast(self, folder_paths: List[str], recursive: bool = True) -> Dict[str, Tuple[int, float]]:
        """
        Fast directory traversal using os.scandir.
        Returns a dictionary mapping: {norm_path: (st_size, st_mtime)}
        This is an extremely fast inode/directory-table lookup that does NOT
        read file contents, making it ideal for slow mechanical HDDs.
        """
        discovered: Dict[str, Tuple[int, float]] = {}

        def scan_dir(dir_path: str):
            try:
                with os.scandir(dir_path) as it:
                    for entry in it:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                stat_info = entry.stat(follow_symlinks=False)
                                norm_path = os.path.normcase(os.path.abspath(entry.path))
                                discovered[norm_path] = (stat_info.st_size, stat_info.st_mtime)
                            elif recursive and entry.is_dir(follow_symlinks=False):
                                scan_dir(entry.path)
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
            except (PermissionError, FileNotFoundError, OSError):
                pass

        for folder in folder_paths:
            abs_folder = os.path.abspath(folder)
            if os.path.isdir(abs_folder):
                scan_dir(abs_folder)

        return discovered

    def scan_folders(
        self,
        folder_paths: List[str],
        recursive: bool = True,
        cached_songs: Optional[Dict[str, AudioMetadata]] = None,
        cached_unindexed: Optional[Dict[str, FileScanStatus]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        on_song_indexed: Optional[Callable[[AudioMetadata], None]] = None,
        on_file_failed: Optional[Callable[[FileScanStatus], None]] = None,
    ) -> ScanResult:
        """
        Smart Incremental Indexer:
        1. Fast scandir discovers disk files and timestamps without opening them.
        2. Compares with cached metadata. Unchanged files are reused instantly with 0 disk I/O.
        3. Only new or modified files are read and processed with a progress bar.
        4. Incomplete songs are enriched with LibVLC fingerprinting.
        """
        started_time = datetime.datetime.now().isoformat()
        t0 = time.time()

        cached_songs = cached_songs or {}
        cached_unindexed = cached_unindexed or {}

        # 1. Fast filesystem scan (directory tables only)
        disk_files = self.discover_files_fast(folder_paths, recursive=recursive)
        total_disk_files = len(disk_files)

        final_songs: Dict[str, AudioMetadata] = {}
        final_unindexed: Dict[str, FileScanStatus] = {}

        to_process: List[Tuple[str, int, float, str]] = []  # (path, size, mtime, action)
        cached_count = 0
        new_count = 0
        modified_count = 0

        for norm_path, (st_size, st_mtime) in disk_files.items():
            # Check if in cached songs
            if norm_path in cached_songs:
                cached_meta = cached_songs[norm_path]
                # Compare size and mtime (allow 1s tolerance for FAT/NTFS rounding)
                if cached_meta.file_size_bytes == st_size and abs(cached_meta.mtime_timestamp - st_mtime) < 1.0:
                    final_songs[norm_path] = cached_meta
                    cached_count += 1
                    continue
                else:
                    to_process.append((norm_path, st_size, st_mtime, "modified"))
                    modified_count += 1
                    continue

            # Check if in cached unindexed
            if norm_path in cached_unindexed:
                cached_status = cached_unindexed[norm_path]
                if cached_status.file_size_bytes == st_size and abs(cached_status.mtime_timestamp - st_mtime) < 1.0:
                    final_unindexed[norm_path] = cached_status
                    cached_count += 1
                    continue
                else:
                    to_process.append((norm_path, st_size, st_mtime, "modified"))
                    modified_count += 1
                    continue

            # Brand new file
            to_process.append((norm_path, st_size, st_mtime, "new"))
            new_count += 1

        # Calculate deleted files count
        deleted_count = 0
        for norm_cached in list(cached_songs.keys()):
            if norm_cached not in disk_files:
                deleted_count += 1
        for norm_cached in list(cached_unindexed.keys()):
            if norm_cached not in disk_files:
                deleted_count += 1

        # 2. Process only new or modified files
        total_to_process = len(to_process)

        for idx, (file_path, file_size, mtime, action) in enumerate(to_process, start=1):
            file_name = os.path.basename(file_path)
            _, ext = os.path.splitext(file_name)
            ext_lower = ext.lower()
            mod_iso = datetime.datetime.fromtimestamp(mtime).isoformat()

            if progress_callback:
                progress_callback(idx, total_to_process, file_name)

            # Check extension
            if ext_lower not in self.audio_extensions:
                status = FileScanStatus(
                    file_path=file_path,
                    file_name=file_name,
                    file_size_bytes=file_size,
                    file_size_human=format_file_size(file_size),
                    extension=ext_lower,
                    is_song=False,
                    reason=f"Non-audio file extension ({ext_lower or 'no extension'})",
                    last_modified=mod_iso,
                    mtime_timestamp=mtime,
                )
                final_unindexed[file_path] = status
                if on_file_failed:
                    on_file_failed(status)
                continue

            # Attempt metadata extraction
            try:
                meta = MetadataExtractor.extract(file_path)
                meta.mtime_timestamp = mtime

                # If metadata is incomplete, attempt VLC fingerprinting / parsing
                if meta.has_incomplete_metadata and self.enable_vlc_enrichment:
                    VLCMetadataEnricher.enrich(meta)

                final_songs[file_path] = meta
                if on_song_indexed:
                    on_song_indexed(meta)
            except Exception as err:
                status = FileScanStatus(
                    file_path=file_path,
                    file_name=file_name,
                    file_size_bytes=file_size,
                    file_size_human=format_file_size(file_size),
                    extension=ext_lower,
                    is_song=False,
                    reason="Corrupted audio or metadata extraction failure",
                    error_details=str(err),
                    last_modified=mod_iso,
                    mtime_timestamp=mtime,
                )
                final_unindexed[file_path] = status
                if on_file_failed:
                    on_file_failed(status)

        t1 = time.time()
        finished_time = datetime.datetime.now().isoformat()

        return ScanResult(
            folders=[os.path.abspath(f) for f in folder_paths if os.path.isdir(f)],
            total_files_examined=total_disk_files,
            songs=list(final_songs.values()),
            unindexed_files=list(final_unindexed.values()),
            elapsed_time_seconds=(t1 - t0),
            started_at=started_time,
            finished_at=finished_time,
            new_files_count=new_count,
            modified_files_count=modified_count,
            cached_files_count=cached_count,
            deleted_files_count=deleted_count,
        )
