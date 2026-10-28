"""
Media Scanner Package
=====================
A modular, high-performance audio indexing, metadata extraction,
and media playback library with CLI and multi-tab PyQt6 GUI interfaces.
Features LibVLC media parsing and smart incremental HDD refresh.
"""

from .metadata import AudioMetadata, MetadataExtractor, VLCMetadataEnricher
from .scanner import AudioIndexer, ScanResult, FileScanStatus
from .storage import StorageManager
from .player import BaseAudioPlayer, VLCPlayer, QtAudioPlayer, get_best_player
from .gui import MusicPlayerWindow, launch_gui

__all__ = [
    "AudioMetadata",
    "MetadataExtractor",
    "VLCMetadataEnricher",
    "AudioIndexer",
    "ScanResult",
    "FileScanStatus",
    "StorageManager",
    "BaseAudioPlayer",
    "VLCPlayer",
    "QtAudioPlayer",
    "get_best_player",
    "MusicPlayerWindow",
    "launch_gui",
]

__version__ = "1.1.0"
