"""
Storage Module
==============
Handles reading and writing indexed songs and unindexed/failed files to JSON.
"""

from __future__ import annotations

import json
import os
from typing import List, Dict, Any, Tuple
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
        
        Returns:
            Tuple of (songs_abs_path, unindexed_abs_path)
        """
        songs_path = os.path.abspath(songs_filepath)
        unindexed_path = os.path.abspath(unindexed_filepath)

        # 1. Big JSON file of all song metadata
        songs_payload = {
            "metadata_version": "1.0",
            "total_songs": len(result.songs),
            "scanned_folders": result.folders,
            "generated_at": result.finished_at,
            "songs": [s.to_dict() for s in result.songs],
        }

        with open(songs_path, "w", encoding="utf-8") as f:
            json.dump(songs_payload, f, indent=indent, ensure_ascii=False)

        # 2. JSON file for non-song files or failed extractions
        unindexed_payload = {
            "metadata_version": "1.0",
            "total_unindexed": len(result.unindexed_files),
            "scanned_folders": result.folders,
            "generated_at": result.finished_at,
            "files": [u.to_dict() for u in result.unindexed_files],
        }

        with open(unindexed_path, "w", encoding="utf-8") as f:
            json.dump(unindexed_payload, f, indent=indent, ensure_ascii=False)

        return songs_path, unindexed_path

    @staticmethod
    def load_songs(songs_filepath: str = DEFAULT_SONGS_JSON) -> List[AudioMetadata]:
        """Load songs from a previously saved JSON file."""
        abs_path = os.path.abspath(songs_filepath)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"Songs JSON file not found: {abs_path}")

        with open(abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        song_list_data = data.get("songs", []) if isinstance(data, dict) else data
        return [AudioMetadata.from_dict(item) for item in song_list_data]

    @staticmethod
    def load_unindexed(unindexed_filepath: str = DEFAULT_UNINDEXED_JSON) -> List[FileScanStatus]:
        """Load unindexed/failed files list from JSON."""
        abs_path = os.path.abspath(unindexed_filepath)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"Unindexed JSON file not found: {abs_path}")

        with open(abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_files = data.get("files", []) if isinstance(data, dict) else data
        return [FileScanStatus(**item) for item in raw_files]
