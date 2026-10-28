"""
Storage Module
==============
Handles reading and writing indexed songs and unindexed/failed files to JSON,
persisting previously scanned folder paths, and providing cached lookups
to support high-speed incremental refresh on slow hard drives.
"""

from __future__ import annotations

import json
import os
from typing import List, Dict, Any, Tuple, Optional
from .metadata import AudioMetadata
from .scanner import FileScanStatus, ScanResult


DEFAULT_SONGS_JSON = "indexed_songs.json"
DEFAULT_UNINDEXED_JSON = "unindexed_files.json"


class StorageManager:
    """Manages serialization of audio metadata and scan reports to JSON."""

    @staticmethod
    def save_scan_result(
        result: ScanResult,
        songs_filepath: str = DEFAULT_SONGS_JSON,
        unindexed_filepath: str = DEFAULT_UNINDEXED_JSON,
        indent: int = 2,
    ) -> Tuple[str, str]:
        """
        Saves indexed songs to one big JSON file and unindexed/failed files
        to a separate JSON file.
        """
        songs_path = os.path.abspath(songs_filepath)
        unindexed_path = os.path.abspath(unindexed_filepath)

        # 1. Big JSON file of all song metadata
        songs_payload = {
            "metadata_version": "1.1",
            "total_songs": len(result.songs),
            "incomplete_songs_count": sum(1 for s in result.songs if s.has_incomplete_metadata),
            "scanned_folders": result.folders,
            "generated_at": result.finished_at,
            "songs": [s.to_dict() for s in result.songs],
        }

        with open(songs_path, "w", encoding="utf-8") as f:
            json.dump(songs_payload, f, indent=indent, ensure_ascii=False)

        # 2. JSON file for non-song files or failed extractions
        unindexed_payload = {
            "metadata_version": "1.1",
            "total_unindexed": len(result.unindexed_files),
            "scanned_folders": result.folders,
            "generated_at": result.finished_at,
            "files": [u.to_dict() for u in result.unindexed_files],
        }

        with open(unindexed_path, "w", encoding="utf-8") as f:
            json.dump(unindexed_payload, f, indent=indent, ensure_ascii=False)

        return songs_path, unindexed_path

    @staticmethod
    def load_cached_library(
        songs_filepath: str = DEFAULT_SONGS_JSON,
        unindexed_filepath: str = DEFAULT_UNINDEXED_JSON,
    ) -> Tuple[Dict[str, AudioMetadata], Dict[str, FileScanStatus], List[str]]:
        """
        Loads previously indexed songs and unindexed files as dictionary mappings
        keyed by normalized absolute file path, along with previously scanned folders.
        Returns empty mappings if files do not exist.
        """
        songs_dict: Dict[str, AudioMetadata] = {}
        unindexed_dict: Dict[str, FileScanStatus] = {}
        folders: List[str] = []

        songs_path = os.path.abspath(songs_filepath)
        if os.path.isfile(songs_path):
            try:
                with open(songs_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    folders = data.get("scanned_folders", [])
                    raw_songs = data.get("songs", [])
                else:
                    raw_songs = data

                for item in raw_songs:
                    meta = AudioMetadata.from_dict(item)
                    norm_path = os.path.normcase(os.path.abspath(meta.file_path))
                    songs_dict[norm_path] = meta
            except Exception:
                pass

        unindexed_path = os.path.abspath(unindexed_filepath)
        if os.path.isfile(unindexed_path):
            try:
                with open(unindexed_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                raw_files = data.get("files", []) if isinstance(data, dict) else data
                for item in raw_files:
                    status = FileScanStatus.from_dict(item)
                    norm_path = os.path.normcase(os.path.abspath(status.file_path))
                    unindexed_dict[norm_path] = status
            except Exception:
                pass

        return songs_dict, unindexed_dict, folders

    @staticmethod
    def load_songs(songs_filepath: str = DEFAULT_SONGS_JSON) -> List[AudioMetadata]:
        """Load songs list from a previously saved JSON file."""
        abs_path = os.path.abspath(songs_filepath)
        if not os.path.isfile(abs_path):
            return []

        with open(abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        song_list_data = data.get("songs", []) if isinstance(data, dict) else data
        return [AudioMetadata.from_dict(item) for item in song_list_data]

    @staticmethod
    def load_unindexed(unindexed_filepath: str = DEFAULT_UNINDEXED_JSON) -> List[FileScanStatus]:
        """Load unindexed/failed files list from JSON."""
        abs_path = os.path.abspath(unindexed_filepath)
        if not os.path.isfile(abs_path):
            return []

        with open(abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_files = data.get("files", []) if isinstance(data, dict) else data
        return [FileScanStatus.from_dict(item) for item in raw_files]
