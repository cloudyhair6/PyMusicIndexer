"""
Scanner Module
==============
Traverses directories, collects files, extracts metadata,
and categorizes files into indexed songs and unindexed/failed files.
"""

from __future__ import annotations

import os
import time
import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Callable, Set

from .metadata import MetadataExtractor, AudioMetadata, AUDIO_EXTENSIONS, format_file_size


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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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

    @property
    def song_count(self) -> int:
        return len(self.songs)

    @property
    def unindexed_count(self) -> int:
        return len(self.unindexed_files)

    def summary(self) -> str:
        """Returns a formatted human-readable summary of the scan."""
        lines = [
            "=" * 50,
            "               INDEXING SUMMARY",
            "=" * 50,
            f"Folders scanned:        {len(self.folders)}",
            f"Total files examined:   {self.total_files_examined}",
            f"Songs indexed:          {self.song_count}",
            f"Unindexed/failed files: {self.unindexed_count}",
            f"Time elapsed:           {self.elapsed_time_seconds:.2f}s",
            "=" * 50,
        ]
        return "\n".join(lines)


class AudioIndexer:
    """
    Crawls folders, extracts song metadata, and tracks failures/skipped files.
    Designed for standalone CLI use or embedding in larger software.
    """

    def __init__(self, audio_extensions: Optional[Set[str]] = None):
        self.audio_extensions = audio_extensions or AUDIO_EXTENSIONS

    def discover_files(self, folder_paths: List[str], recursive: bool = True) -> List[str]:
        """
        Walk directories and return a flat list of all existing file paths.
        Skips invalid directories or inaccessible files cleanly.
        """
        all_files: List[str] = []
        for folder in folder_paths:
            abs_folder = os.path.abspath(folder)
            if not os.path.isdir(abs_folder):
                continue

            if recursive:
                for root, _, filenames in os.walk(abs_folder):
                    for fn in filenames:
                        all_files.append(os.path.join(root, fn))
            else:
                try:
                    for entry in os.scandir(abs_folder):
                        if entry.is_file():
                            all_files.append(entry.path)
                except PermissionError:
                    continue

        return all_files

    def scan_folders(
        self,
        folder_paths: List[str],
        recursive: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        on_song_indexed: Optional[Callable[[AudioMetadata], None]] = None,
        on_file_failed: Optional[Callable[[FileScanStatus], None]] = None,
    ) -> ScanResult:
        """
        Index audio files across the provided list of folders.
        
        Args:
            folder_paths: List of directory paths to index.
            recursive: Whether to crawl subdirectories.
            progress_callback: Optional callback(current_index, total_count, current_filename).
            on_song_indexed: Optional hook invoked when a song is successfully indexed.
            on_file_failed: Optional hook invoked when a file is skipped or failed.
        
        Returns:
            ScanResult object with songs, unindexed files, and metrics.
        """
        started_time = datetime.datetime.now().isoformat()
        t0 = time.time()

        # Discover all files first to provide accurate progress percentage
        all_files = self.discover_files(folder_paths, recursive=recursive)
        total_files = len(all_files)

        songs: List[AudioMetadata] = []
        unindexed: List[FileScanStatus] = []

        for idx, file_path in enumerate(all_files, start=1):
            file_name = os.path.basename(file_path)
            _, ext = os.path.splitext(file_name)
            ext_lower = ext.lower()

            if progress_callback:
                progress_callback(idx, total_files, file_name)

            # Get stat info safely
            try:
                st = os.stat(file_path)
                file_size = st.st_size
                mod_time = datetime.datetime.fromtimestamp(st.st_mtime).isoformat()
            except Exception as e:
                status = FileScanStatus(
                    file_path=file_path,
                    file_name=file_name,
                    file_size_bytes=0,
                    file_size_human="0 B",
                    extension=ext_lower,
                    is_song=False,
                    reason="Inaccessible file (Permission or IO error)",
                    error_details=str(e),
                )
                unindexed.append(status)
                if on_file_failed:
                    on_file_failed(status)
                continue

            # Check if extension matches supported audio extensions
            if ext_lower not in self.audio_extensions:
                status = FileScanStatus(
                    file_path=file_path,
                    file_name=file_name,
                    file_size_bytes=file_size,
                    file_size_human=format_file_size(file_size),
                    extension=ext_lower,
                    is_song=False,
                    reason=f"Non-audio file extension ({ext_lower or 'no extension'})",
                    last_modified=mod_time,
                )
                unindexed.append(status)
                if on_file_failed:
                    on_file_failed(status)
                continue

            # Attempt to extract metadata
            try:
                meta = MetadataExtractor.extract(file_path)
                songs.append(meta)
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
                    last_modified=mod_time,
                )
                unindexed.append(status)
                if on_file_failed:
                    on_file_failed(status)

        t1 = time.time()
        finished_time = datetime.datetime.now().isoformat()

        return ScanResult(
            folders=[os.path.abspath(f) for f in folder_paths if os.path.isdir(f)],
            total_files_examined=total_files,
            songs=songs,
            unindexed_files=unindexed,
            elapsed_time_seconds=(t1 - t0),
            started_at=started_time,
            finished_at=finished_time,
        )
