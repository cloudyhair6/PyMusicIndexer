"""
Media Scanner Package
=====================
A modular, high-performance audio indexing, metadata extraction,
and media playback library with CLI and PyQt GUI interfaces.
"""

from .metadata import AudioMetadata, MetadataExtractor
from .scanner import AudioIndexer, ScanResult, FileScanStatus
from .storage import StorageManager
from .player import BaseAudioPlayer, VLCPlayer, QtAudioPlayer, get_best_player
from .gui import MusicPlayerWindow, launch_gui

__all__ = [
    "AudioMetadata",
    "MetadataExtractor",
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

__version__ = "1.0.0"
