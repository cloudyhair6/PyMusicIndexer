"""
Audio Playback Engine Module
============================
Provides unified audio playback using LibVLC (via ctypes or python-vlc)
and PyQt6 QtMultimedia as a high-compatibility fallback.
"""

from __future__ import annotations

import os
import sys
import ctypes
from abc import ABC, abstractmethod
from typing import Optional, Callable


class BaseAudioPlayer(ABC):
    """Abstract base class for all audio player backends."""

    def __init__(self):
        self.current_file: Optional[str] = None
        self.on_track_end: Optional[Callable[[], None]] = None

    @abstractmethod
    def load(self, file_path: str) -> bool:
        """Load an audio file into the player."""
        pass

    @abstractmethod
    def play(self) -> None:
        """Start or resume playback."""
        pass

    @abstractmethod
    def pause(self) -> None:
        """Pause playback."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop playback and reset position."""
        pass

    @abstractmethod
    def seek(self, position_seconds: float) -> None:
        """Seek to a timestamp in seconds."""
        pass

    @abstractmethod
    def set_volume(self, volume_percent: int) -> None:
        """Set volume between 0 and 100."""
        pass

    @abstractmethod
    def get_volume(self) -> int:
        """Get volume between 0 and 100."""
        pass

    @abstractmethod
    def get_position(self) -> float:
        """Return current playback position in seconds."""
        pass

    @abstractmethod
    def get_duration(self) -> float:
        """Return total duration of the track in seconds."""
        pass

    @abstractmethod
    def is_playing(self) -> bool:
        """Return True if media is actively playing."""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Release any underlying system resources."""
        pass


class VLCPlayer(BaseAudioPlayer):
    """
    High-fidelity media player powered by VideoLAN (LibVLC).
    Supports virtually all audio formats, codecs, and streams.
    """

    def __init__(self, vlc_directory: Optional[str] = None):
        super().__init__()
        self._vlc_dll = None
        self._instance = None
        self._player = None
        self._media = None
        self._cached_duration = 0.0
        self._volume = 80

        self._init_vlc(vlc_directory)

    def _init_vlc(self, vlc_directory: Optional[str]):
        # Common VLC installation directories on Windows
        search_dirs = [
            vlc_directory,
            r"C:\Program Files\VideoLAN\VLC",
            r"C:\Program Files (x86)\VideoLAN\VLC",
        ]

        dll_path = None
        for d in search_dirs:
            if d and os.path.isdir(d):
                cand = os.path.join(d, "libvlc.dll")
                if os.path.isfile(cand):
                    dll_path = cand
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(d)
                        except Exception:
                            pass
                    os.environ["PATH"] = d + ";" + os.environ.get("PATH", "")
                    break

        if not dll_path:
            raise RuntimeError("LibVLC DLL could not be located on the system.")

        self._vlc_dll = ctypes.CDLL(dll_path)
        self._setup_prototypes()

        # Initialize VLC instance with quiet flags
        vlc_args = [b"--no-video", b"--quiet", b"--no-xlib"]
        c_args = (ctypes.c_char_p * len(vlc_args))(*vlc_args)
        self._instance = self._vlc_dll.libvlc_new(len(vlc_args), c_args)
        if not self._instance:
            self._instance = self._vlc_dll.libvlc_new(0, None)

        if not self._instance:
            raise RuntimeError("Failed to create LibVLC instance.")

        # Create media player
        self._player = self._vlc_dll.libvlc_media_player_new(self._instance)
        self.set_volume(self._volume)

    def _setup_prototypes(self):
        d = self._vlc_dll

        d.libvlc_new.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
        d.libvlc_new.restype = ctypes.c_void_p

        d.libvlc_release.argtypes = [ctypes.c_void_p]
        d.libvlc_release.restype = None

        d.libvlc_media_player_new.argtypes = [ctypes.c_void_p]
        d.libvlc_media_player_new.restype = ctypes.c_void_p

        d.libvlc_media_player_release.argtypes = [ctypes.c_void_p]
        d.libvlc_media_player_release.restype = None

        d.libvlc_media_new_path.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        d.libvlc_media_new_path.restype = ctypes.c_void_p

        d.libvlc_media_release.argtypes = [ctypes.c_void_p]
        d.libvlc_media_release.restype = None

        d.libvlc_media_player_set_media.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        d.libvlc_media_player_set_media.restype = None

        d.libvlc_media_player_play.argtypes = [ctypes.c_void_p]
        d.libvlc_media_player_play.restype = ctypes.c_int

        d.libvlc_media_player_pause.argtypes = [ctypes.c_void_p]
        d.libvlc_media_player_pause.restype = None

        d.libvlc_media_player_stop.argtypes = [ctypes.c_void_p]
        d.libvlc_media_player_stop.restype = None

        d.libvlc_media_player_is_playing.argtypes = [ctypes.c_void_p]
        d.libvlc_media_player_is_playing.restype = ctypes.c_int

        d.libvlc_media_player_get_time.argtypes = [ctypes.c_void_p]
        d.libvlc_media_player_get_time.restype = ctypes.c_int64

        d.libvlc_media_player_set_time.argtypes = [ctypes.c_void_p, ctypes.c_int64]
        d.libvlc_media_player_set_time.restype = None

        d.libvlc_media_player_get_length.argtypes = [ctypes.c_void_p]
        d.libvlc_media_player_get_length.restype = ctypes.c_int64

        d.libvlc_audio_set_volume.argtypes = [ctypes.c_void_p, ctypes.c_int]
        d.libvlc_audio_set_volume.restype = ctypes.c_int

        d.libvlc_audio_get_volume.argtypes = [ctypes.c_void_p]
        d.libvlc_audio_get_volume.restype = ctypes.c_int

    def load(self, file_path: str) -> bool:
        if not os.path.isfile(file_path):
            return False

        self.stop()
        if self._media:
            self._vlc_dll.libvlc_media_release(self._media)
            self._media = None

        abs_path = os.path.abspath(file_path)
        path_bytes = abs_path.encode(sys.getfilesystemencoding())
        self._media = self._vlc_dll.libvlc_media_new_path(self._instance, path_bytes)
        if not self._media:
            return False

        self._vlc_dll.libvlc_media_player_set_media(self._player, self._media)
        self.current_file = abs_path
        self._cached_duration = 0.0
        return True

    def play(self) -> None:
        if self._player:
            self._vlc_dll.libvlc_media_player_play(self._player)

    def pause(self) -> None:
        if self._player:
            self._vlc_dll.libvlc_media_player_pause(self._player)

    def stop(self) -> None:
        if self._player:
            self._vlc_dll.libvlc_media_player_stop(self._player)

    def seek(self, position_seconds: float) -> None:
        if self._player:
            ms = int(max(0, position_seconds) * 1000)
            self._vlc_dll.libvlc_media_player_set_time(self._player, ms)

    def set_volume(self, volume_percent: int) -> None:
        self._volume = max(0, min(100, volume_percent))
        if self._player:
            self._vlc_dll.libvlc_audio_set_volume(self._player, self._volume)

    def get_volume(self) -> int:
        if self._player:
            v = self._vlc_dll.libvlc_audio_get_volume(self._player)
            if v >= 0:
                self._volume = v
        return self._volume

    def get_position(self) -> float:
        if self._player:
            ms = self._vlc_dll.libvlc_media_player_get_time(self._player)
            if ms >= 0:
                return ms / 1000.0
        return 0.0

    def get_duration(self) -> float:
        if self._player:
            ms = self._vlc_dll.libvlc_media_player_get_length(self._player)
            if ms > 0:
                self._cached_duration = ms / 1000.0
        return self._cached_duration

    def is_playing(self) -> bool:
        if self._player:
            return bool(self._vlc_dll.libvlc_media_player_is_playing(self._player))
        return False

    def cleanup(self) -> None:
        self.stop()
        if self._media and self._vlc_dll:
            self._vlc_dll.libvlc_media_release(self._media)
            self._media = None
        if self._player and self._vlc_dll:
            self._vlc_dll.libvlc_media_player_release(self._player)
            self._player = None
        if self._instance and self._vlc_dll:
            self._vlc_dll.libvlc_release(self._instance)
            self._instance = None


class QtAudioPlayer(BaseAudioPlayer):
    """Fallback audio player based on PyQt6 QtMultimedia."""

    def __init__(self):
        super().__init__()
        from PyQt6.QtCore import QUrl
        from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._volume = 80
        self._audio_output.setVolume(self._volume / 100.0)

    def load(self, file_path: str) -> bool:
        from PyQt6.QtCore import QUrl
        if not os.path.isfile(file_path):
            return False
        abs_path = os.path.abspath(file_path)
        url = QUrl.fromLocalFile(abs_path)
        self._player.setSource(url)
        self.current_file = abs_path
        return True

    def play(self) -> None:
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()

    def seek(self, position_seconds: float) -> None:
        ms = int(max(0, position_seconds) * 1000)
        self._player.setPosition(ms)

    def set_volume(self, volume_percent: int) -> None:
        self._volume = max(0, min(100, volume_percent))
        self._audio_output.setVolume(self._volume / 100.0)

    def get_volume(self) -> int:
        return self._volume

    def get_position(self) -> float:
        return self._player.position() / 1000.0

    def get_duration(self) -> float:
        dur = self._player.duration()
        return dur / 1000.0 if dur > 0 else 0.0

    def is_playing(self) -> bool:
        from PyQt6.QtMultimedia import QMediaPlayer
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def cleanup(self) -> None:
        self.stop()


def get_best_player(preferred_backend: str = "vlc") -> BaseAudioPlayer:
    """
    Factory function that instantiates the preferred player backend.
    Gracefully falls back between VLC and QtAudioPlayer.
    """
    if preferred_backend.lower() == "vlc":
        try:
            return VLCPlayer()
        except Exception:
            return QtAudioPlayer()
    else:
        try:
            return QtAudioPlayer()
        except Exception:
            return VLCPlayer()
