"""
GUI Music Browser, Inspector & Player
=====================================
Multi-tab PyQt6 graphical interface providing:
- Tab 1: All Songs (Instant search, table, play)
- Tab 2: Incomplete Metadata (VLC fingerprinted tracks, artwork filters, tag writer, album art fetcher)
- Tab 3: Unindexed & Failed Files (Corrupt audio, non-music files, errors)
- Persistent audio player powered by LibVLC or QtMultimedia with live cover art preview
- Asynchronous LibVLC Batch Fingerprint Worker with Live Progress Dialog
- Asynchronous Album Art Search & Downloader Worker with Live Progress Dialog
- Physical File Tag & Cover Art Embedder (Writes directly into MP3, WAV, FLAC files)
"""

from __future__ import annotations

import os
import time
import subprocess
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QUrl
from PyQt6.QtGui import QIcon, QFont, QColor, QPixmap, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton,
    QSlider, QLabel, QComboBox, QMenu, QAbstractItemView, QFrame,
    QTabWidget, QMessageBox, QDialog, QProgressBar, QGridLayout, QCheckBox,
    QScrollArea
)

from .metadata import AudioMetadata, VLCMetadataEnricher, format_seconds
from .artwork import AlbumArtManager
from .writer import AudioMetadataWriter
from .scanner import FileScanStatus
from .player import BaseAudioPlayer, VLCPlayer, QtAudioPlayer, get_best_player
from .storage import StorageManager, DEFAULT_SONGS_JSON


class VLCFingerprintWorker(QThread):
    """
    Background worker thread that runs LibVLC media parsing and fingerprinting
    without blocking the Qt GUI main thread.
    """
    progress_updated = pyqtSignal(int, int, str, int, float, float)
    finished = pyqtSignal(int, bool)

    def __init__(
        self,
        songs: List[AudioMetadata],
        all_library_songs: Optional[List[AudioMetadata]] = None,
        songs_json_path: str = DEFAULT_SONGS_JSON,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.songs = songs
        self.all_library_songs = all_library_songs or songs
        self.songs_json_path = songs_json_path
        self._is_cancelled = False

    def request_cancel(self):
        self._is_cancelled = True

    def run(self):
        total = len(self.songs)
        enriched_count = 0
        t0 = time.time()
        last_save_time = t0

        for idx, song in enumerate(self.songs, start=1):
            if self._is_cancelled:
                if enriched_count > 0:
                    try:
                        StorageManager.update_songs_catalog(self.all_library_songs, self.songs_json_path)
                    except Exception:
                        pass
                self.finished.emit(enriched_count, True)
                return

            try:
                changed = VLCMetadataEnricher.enrich(song)
                if changed:
                    enriched_count += 1
            except Exception:
                pass

            now = time.time()
            elapsed = max(0.001, now - t0)
            rate = idx / elapsed

            self.progress_updated.emit(idx, total, song.file_name, enriched_count, elapsed, rate)

            if (idx % 150 == 0) or (now - last_save_time > 20.0):
                try:
                    StorageManager.update_songs_catalog(self.all_library_songs, self.songs_json_path)
                    last_save_time = now
                except Exception:
                    pass

        try:
            StorageManager.update_songs_catalog(self.all_library_songs, self.songs_json_path)
        except Exception:
            pass

        self.finished.emit(enriched_count, False)


class VLCProgressDialog(QDialog):
    """
    Dedicated responsive progress dialog for LibVLC fingerprint tasks.
    """

    def __init__(
        self,
        songs_to_process: List[AudioMetadata],
        all_library_songs: List[AudioMetadata],
        songs_json_path: str = DEFAULT_SONGS_JSON,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.setWindowTitle("LibVLC Fingerprint & Metadata Enrichment")
        self.resize(580, 260)
        self.setMinimumWidth(500)
        self.setModal(True)

        self.songs_to_process = songs_to_process
        self.all_library_songs = all_library_songs
        self.songs_json_path = songs_json_path
        self.total_songs = len(songs_to_process)
        self.final_enriched = 0
        self.was_cancelled = False

        self._setup_ui()
        self._apply_dialog_theme()

        self.worker = VLCFingerprintWorker(
            songs=self.songs_to_process,
            all_library_songs=self.all_library_songs,
            songs_json_path=self.songs_json_path,
            parent=self,
        )
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl_title = QLabel("⚡ LibVLC Batch Fingerprint & Tag Enrichment")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #89b4fa;")
        layout.addWidget(lbl_title)

        self.lbl_desc = QLabel("Parsing audio streams, retrieving missing tags, and searching for album art...")
        self.lbl_desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self.lbl_desc)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total_songs)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(24)
        layout.addWidget(self.progress_bar)

        self.lbl_current_file = QLabel("Preparing track queue...")
        self.lbl_current_file.setStyleSheet("color: #cdd6f4; font-size: 11px; font-style: italic;")
        layout.addWidget(self.lbl_current_file)

        stats_frame = QFrame()
        stats_frame.setStyleSheet("background-color: #24273a; border-radius: 6px; padding: 6px;")
        grid = QGridLayout(stats_frame)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(4)

        self.lbl_count = QLabel(f"Processed: 0 / {self.total_songs:,}")
        self.lbl_count.setStyleSheet("font-weight: bold; color: #cdd6f4;")
        grid.addWidget(self.lbl_count, 0, 0)

        self.lbl_enriched = QLabel("Enriched: 0 tracks")
        self.lbl_enriched.setStyleSheet("font-weight: bold; color: #a6e3a1;")
        grid.addWidget(self.lbl_enriched, 0, 1)

        self.lbl_speed = QLabel("Speed: -")
        self.lbl_speed.setStyleSheet("color: #bac2de;")
        grid.addWidget(self.lbl_speed, 1, 0)

        self.lbl_eta = QLabel("Estimated Time Remaining: Calculating...")
        self.lbl_eta.setStyleSheet("color: #fab387;")
        grid.addWidget(self.lbl_eta, 1, 1)

        layout.addWidget(stats_frame)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_action = QPushButton("Cancel / Stop")
        self.btn_action.setFixedWidth(120)
        self.btn_action.setFixedHeight(32)
        self.btn_action.clicked.connect(self._on_action_clicked)
        btn_layout.addWidget(self.btn_action)

        layout.addLayout(btn_layout)

    def _apply_dialog_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
            }
            QLabel {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QProgressBar {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #89b4fa, stop:1 #b4befe);
                border-radius: 5px;
            }
            QPushButton {
                background-color: #45475a;
                border: 1px solid #585b70;
                border-radius: 6px;
                padding: 6px 14px;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f38ba8;
                color: #11111b;
            }
        """)

    def _on_progress(self, current: int, total: int, filename: str, enriched_count: int, elapsed_sec: float, rate: float):
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"%p% ({current:,} / {total:,})")

        disp_name = filename if len(filename) < 55 else "..." + filename[-52:]
        self.lbl_current_file.setText(f"Scanning: {disp_name}")

        self.lbl_count.setText(f"Processed: {current:,} / {total:,}")
        self.lbl_enriched.setText(f"Enriched: {enriched_count:,} tracks")
        self.lbl_speed.setText(f"Speed: {rate:.1f} tracks/sec")

        remaining = max(0, total - current)
        if rate > 0 and remaining > 0:
            eta_seconds = remaining / rate
            eta_str = format_seconds(eta_seconds)
            self.lbl_eta.setText(f"ETA: ~{eta_str}")
        else:
            self.lbl_eta.setText("ETA: Finishing up...")

    def _on_action_clicked(self):
        if self.worker.isRunning():
            self.btn_action.setEnabled(False)
            self.btn_action.setText("Stopping...")
            self.lbl_desc.setText("Stopping worker safely. Saving current enriched progress to JSON...")
            self.worker.request_cancel()
        else:
            self.accept()

    def _on_finished(self, enriched_count: int, was_cancelled: bool):
        self.final_enriched = enriched_count
        self.was_cancelled = was_cancelled

        if was_cancelled:
            self.lbl_desc.setText(f"Stopped. Enriched {enriched_count:,} tracks. Progress saved to JSON.")
            self.lbl_desc.setStyleSheet("color: #fab387; font-weight: bold;")
        else:
            self.progress_bar.setValue(self.total_songs)
            self.lbl_desc.setText(f"Complete! Finished examining {self.total_songs:,} tracks ({enriched_count:,} enriched & saved).")
            self.lbl_desc.setStyleSheet("color: #a6e3a1; font-weight: bold;")
            self.lbl_eta.setText("Status: Done")

        self.btn_action.setText("Close")
        self.btn_action.setEnabled(True)
        self.btn_action.setStyleSheet("background-color: #89b4fa; color: #11111b; font-weight: bold;")

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.worker.request_cancel()
            self.worker.wait(3000)
        event.accept()


class AlbumArtFetchWorker(QThread):
    """
    Background worker thread to search and download missing album covers
    from local folders, VLC art cache, and online search APIs (iTunes, Deezer).
    """
    progress_updated = pyqtSignal(int, int, str, int)  # current, total, filename, fetched_count
    finished = pyqtSignal(int, bool)

    def __init__(
        self,
        songs: List[AudioMetadata],
        all_library_songs: List[AudioMetadata],
        songs_json_path: str = DEFAULT_SONGS_JSON,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.songs = songs
        self.all_library_songs = all_library_songs
        self.songs_json_path = songs_json_path
        self._is_cancelled = False

    def request_cancel(self):
        self._is_cancelled = True

    def run(self):
        total = len(self.songs)
        fetched_count = 0

        for idx, song in enumerate(self.songs, start=1):
            if self._is_cancelled:
                break

            # If track lacks art, attempt resolution
            if not song.has_album_art:
                found = AlbumArtManager.resolve_artwork(song, enable_online_download=True)
                if found:
                    fetched_count += 1

            self.progress_updated.emit(idx, total, song.file_name, fetched_count)

            if idx % 50 == 0:
                try:
                    StorageManager.update_songs_catalog(self.all_library_songs, self.songs_json_path)
                except Exception:
                    pass

        try:
            StorageManager.update_songs_catalog(self.all_library_songs, self.songs_json_path)
        except Exception:
            pass

        self.finished.emit(fetched_count, self._is_cancelled)


class AlbumArtFetchProgressDialog(QDialog):
    """
    Progress dialog displayed while searching and downloading missing cover art.
    """

    def __init__(
        self,
        songs_to_fetch: List[AudioMetadata],
        all_library_songs: List[AudioMetadata],
        songs_json_path: str = DEFAULT_SONGS_JSON,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.setWindowTitle("Fetching Album Cover Art")
        self.resize(560, 240)
        self.setModal(True)

        self.songs_to_fetch = songs_to_fetch
        self.all_library_songs = all_library_songs
        self.songs_json_path = songs_json_path
        self.total = len(songs_to_fetch)
        self.fetched = 0

        self._setup_ui()
        self._apply_dialog_theme()

        self.worker = AlbumArtFetchWorker(
            songs=self.songs_to_fetch,
            all_library_songs=self.all_library_songs,
            songs_json_path=self.songs_json_path,
            parent=self
        )
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl_title = QLabel("🖼️ Searching & Downloading Album Artwork")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #f9e2af;")
        layout.addWidget(lbl_title)

        self.lbl_desc = QLabel("Searching local album folders, VLC cache, and online high-res cover art...")
        self.lbl_desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self.lbl_desc)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(24)
        layout.addWidget(self.progress_bar)

        self.lbl_current_file = QLabel("Preparing search query...")
        self.lbl_current_file.setStyleSheet("color: #cdd6f4; font-size: 11px; font-style: italic;")
        layout.addWidget(self.lbl_current_file)

        stats_frame = QFrame()
        stats_frame.setStyleSheet("background-color: #24273a; border-radius: 6px; padding: 6px;")
        grid = QGridLayout(stats_frame)
        grid.setContentsMargins(10, 8, 10, 8)

        self.lbl_scanned = QLabel(f"Examined: 0 / {self.total:,}")
        self.lbl_scanned.setStyleSheet("font-weight: bold; color: #cdd6f4;")
        grid.addWidget(self.lbl_scanned, 0, 0)

        self.lbl_found = QLabel("Art Found & Cached: 0")
        self.lbl_found.setStyleSheet("font-weight: bold; color: #a6e3a1;")
        grid.addWidget(self.lbl_found, 0, 1)

        layout.addWidget(stats_frame)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel / Stop")
        self.btn_cancel.setFixedWidth(110)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def _apply_dialog_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
            }
            QLabel {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QProgressBar {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f9e2af, stop:1 #fab387);
                border-radius: 5px;
            }
            QPushButton {
                background-color: #45475a;
                border: 1px solid #585b70;
                border-radius: 6px;
                padding: 6px 14px;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f38ba8;
                color: #11111b;
            }
        """)

    def _on_progress(self, current: int, total: int, filename: str, fetched: int):
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"%p% ({current:,} / {total:,})")

        disp_name = filename if len(filename) < 55 else "..." + filename[-52:]
        self.lbl_current_file.setText(f"Checking: {disp_name}")
        self.lbl_scanned.setText(f"Examined: {current:,} / {total:,}")
        self.lbl_found.setText(f"Art Found & Cached: {fetched:,}")

    def _on_cancel(self):
        if self.worker.isRunning():
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Stopping...")
            self.worker.request_cancel()
        else:
            self.accept()

    def _on_finished(self, fetched: int, was_cancelled: bool):
        self.fetched = fetched
        self.progress_bar.setValue(self.total)
        status_txt = "Stopped." if was_cancelled else "Completed!"
        self.lbl_desc.setText(f"{status_txt} Successfully located and cached artwork for {fetched:,} albums.")
        self.lbl_desc.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        self.btn_cancel.setText("Close")
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setStyleSheet("background-color: #f9e2af; color: #11111b; font-weight: bold;")

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.worker.request_cancel()
            self.worker.wait(3000)
        event.accept()


class FileTagWriterWorker(QThread):
    """
    Background worker thread that writes metadata tags AND embeds album cover artwork
    directly into physical audio files on disk (MP3, WAV, FLAC).
    """
    progress_updated = pyqtSignal(int, int, str, int, int)
    finished = pyqtSignal(int, int, list)

    def __init__(
        self,
        songs: List[AudioMetadata],
        all_library_songs: List[AudioMetadata],
        songs_json_path: str = DEFAULT_SONGS_JSON,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.songs = songs
        self.all_library_songs = all_library_songs
        self.songs_json_path = songs_json_path
        self._is_cancelled = False

    def request_cancel(self):
        self._is_cancelled = True

    def run(self):
        total = len(self.songs)
        success = 0
        failed = 0
        errors = []

        for idx, song in enumerate(self.songs, start=1):
            if self._is_cancelled:
                break

            ok, err = AudioMetadataWriter.write_metadata(song)
            if ok:
                success += 1
            else:
                failed += 1
                errors.append(f"{song.file_name}: {err}")

            self.progress_updated.emit(idx, total, song.file_name, success, failed)

        try:
            StorageManager.update_songs_catalog(self.all_library_songs, self.songs_json_path)
        except Exception:
            pass

        self.finished.emit(success, failed, errors)


class FileTagWriterProgressDialog(QDialog):
    """
    Progress dialog displayed while writing metadata and embedding artwork into files.
    """

    def __init__(
        self,
        songs_to_write: List[AudioMetadata],
        all_library_songs: List[AudioMetadata],
        songs_json_path: str = DEFAULT_SONGS_JSON,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.setWindowTitle("Writing Tags & Embedding Artwork")
        self.resize(560, 240)
        self.setModal(True)

        self.songs_to_write = songs_to_write
        self.all_library_songs = all_library_songs
        self.songs_json_path = songs_json_path
        self.total = len(songs_to_write)
        self.succeeded = 0
        self.failed = 0

        self._setup_ui()
        self._apply_dialog_theme()

        self.worker = FileTagWriterWorker(
            songs=self.songs_to_write,
            all_library_songs=self.all_library_songs,
            songs_json_path=self.songs_json_path,
            parent=self
        )
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl_title = QLabel("💾 Writing Tags & Embedding Album Artwork into Files")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #a6e3a1;")
        layout.addWidget(lbl_title)

        self.lbl_desc = QLabel("Embedding ID3v2 tags & APIC cover art into audio files on disk...")
        self.lbl_desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self.lbl_desc)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(24)
        layout.addWidget(self.progress_bar)

        self.lbl_current_file = QLabel("Preparing to write tags...")
        self.lbl_current_file.setStyleSheet("color: #cdd6f4; font-size: 11px; font-style: italic;")
        layout.addWidget(self.lbl_current_file)

        stats_frame = QFrame()
        stats_frame.setStyleSheet("background-color: #24273a; border-radius: 6px; padding: 6px;")
        grid = QGridLayout(stats_frame)
        grid.setContentsMargins(10, 8, 10, 8)

        self.lbl_written = QLabel(f"Written: 0 / {self.total:,}")
        self.lbl_written.setStyleSheet("font-weight: bold; color: #a6e3a1;")
        grid.addWidget(self.lbl_written, 0, 0)

        self.lbl_failed = QLabel("Failed: 0")
        self.lbl_failed.setStyleSheet("font-weight: bold; color: #f38ba8;")
        grid.addWidget(self.lbl_failed, 0, 1)

        layout.addWidget(stats_frame)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedWidth(100)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def _apply_dialog_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
            }
            QLabel {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QProgressBar {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #a6e3a1, stop:1 #94e2d5);
                border-radius: 5px;
            }
            QPushButton {
                background-color: #45475a;
                border: 1px solid #585b70;
                border-radius: 6px;
                padding: 6px 14px;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f38ba8;
                color: #11111b;
            }
        """)

    def _on_progress(self, current: int, total: int, filename: str, success: int, fail: int):
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"%p% ({current:,} / {total:,})")

        disp_name = filename if len(filename) < 55 else "..." + filename[-52:]
        self.lbl_current_file.setText(f"Writing: {disp_name}")
        self.lbl_written.setText(f"Written: {success:,} / {total:,}")
        self.lbl_failed.setText(f"Failed: {fail:,}")

    def _on_cancel(self):
        if self.worker.isRunning():
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Stopping...")
            self.worker.request_cancel()
        else:
            self.accept()

    def _on_finished(self, success: int, fail: int, errors: list):
        self.succeeded = success
        self.failed = fail
        self.progress_bar.setValue(self.total)
        self.lbl_desc.setText(f"Completed! Successfully updated tags and embedded artwork in {success:,} audio files.")
        self.lbl_desc.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        self.btn_cancel.setText("Close")
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setStyleSheet("background-color: #a6e3a1; color: #11111b; font-weight: bold;")

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.worker.request_cancel()
            self.worker.wait(3000)
        event.accept()


class ExtendedTrackDetailsDialog(QDialog):
    """
    Detailed inspector dialog showing all extended Windows Details metadata,
    audio technical properties, direct web artwork link, and HTML link.
    """

    def __init__(self, song: AudioMetadata, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.song = song
        self.setWindowTitle(f"Track Details — {song.title}")
        self.resize(640, 580)
        self.setModal(True)
        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header with artwork and title
        header_frame = QFrame()
        header_frame.setStyleSheet("background-color: #24273a; border-radius: 8px; padding: 8px;")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(8, 8, 8, 8)
        header_layout.setSpacing(14)

        # Artwork thumbnail
        self.lbl_art = QLabel()
        self.lbl_art.setFixedSize(100, 100)
        self.lbl_art.setStyleSheet("background-color: #181926; border-radius: 6px; border: 1px solid #45475a;")
        self.lbl_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.song.has_album_art and self.song.album_art_path and os.path.isfile(self.song.album_art_path):
            pix = QPixmap(self.song.album_art_path)
            if not pix.isNull():
                self.lbl_art.setPixmap(pix.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            else:
                self.lbl_art.setText("🎵")
        else:
            self.lbl_art.setText("🎵\nNo Cover")
        header_layout.addWidget(self.lbl_art)

        # Header info
        title_box = QVBoxLayout()
        lbl_song_title = QLabel(self.song.title or "Unknown Title")
        lbl_song_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #89b4fa;")
        lbl_song_title.setWordWrap(True)
        title_box.addWidget(lbl_song_title)

        lbl_artist_album = QLabel(f"by {self.song.artist} — {self.song.album}")
        lbl_artist_album.setStyleSheet("font-size: 13px; color: #cdd6f4;")
        lbl_artist_album.setWordWrap(True)
        title_box.addWidget(lbl_artist_album)

        if self.song.rating:
            stars = "★" * self.song.rating + "☆" * (5 - self.song.rating)
            lbl_rating = QLabel(f"Rating: {stars} ({self.song.rating}/5 stars)")
            lbl_rating.setStyleSheet("color: #f9e2af; font-size: 12px; font-weight: bold;")
            title_box.addWidget(lbl_rating)

        title_box.addStretch()
        header_layout.addLayout(title_box, stretch=1)
        main_layout.addWidget(header_frame)

        # Scrollable content area for detailed properties
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #313244; border-radius: 6px; background-color: #181926; }")

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(14)

        def make_section(title: str, items: list[tuple[str, str]]) -> QWidget:
            box = QFrame()
            box.setStyleSheet("background-color: #1e1e2e; border: 1px solid #313244; border-radius: 6px; padding: 6px;")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(8, 6, 8, 6)
            box_layout.setSpacing(4)

            sec_title = QLabel(title)
            sec_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #fab387; border-bottom: 1px solid #313244; padding-bottom: 3px;")
            box_layout.addWidget(sec_title)

            grid = QGridLayout()
            grid.setContentsMargins(4, 4, 4, 4)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(4)
            for row, (k, v) in enumerate(items):
                lbl_k = QLabel(k)
                lbl_k.setStyleSheet("color: #a6adc8; font-size: 11px;")
                lbl_v = QLabel(str(v) if v not in (None, "") else "—")
                lbl_v.setStyleSheet("color: #cdd6f4; font-size: 11px; font-weight: 500;")
                lbl_v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                grid.addWidget(lbl_k, row, 0)
                grid.addWidget(lbl_v, row, 1)
            grid.setColumnStretch(1, 1)
            box_layout.addLayout(grid)
            return box

        # 1. Description & Origin
        desc_items = [
            ("Subtitle", self.song.subtitle),
            ("Comments", self.song.comments),
            ("Contributing Artists", self.song.artist),
            ("Album Artist", self.song.album_artist),
            ("Publisher", self.song.publisher),
            ("Encoded By", self.song.encoded_by),
            ("Author URL", self.song.author_url),
            ("Copyright", self.song.copyright),
        ]
        content_layout.addWidget(make_section("Description & Origin", desc_items))

        # 2. Media & Musical Content
        media_items = [
            ("Album", self.song.album),
            ("Year", self.song.year),
            ("Track #", self.song.track_number),
            ("Disc # (Part of Set)", self.song.disc_number),
            ("Genre", self.song.genre),
            ("Duration", self.song.duration_formatted),
            ("Composer", self.song.composer),
            ("Conductor", self.song.conductor),
            ("Grouping (Description)", self.song.grouping),
            ("Mood", self.song.mood),
            ("Initial Key", self.song.initial_key),
            ("Beats-Per-Minute (BPM)", str(self.song.bpm) if self.song.bpm else None),
            ("Part of Compilation", "Yes" if self.song.is_compilation else "No"),
        ]
        content_layout.addWidget(make_section("Media & Content", media_items))

        # 3. Audio Stream Properties & File Details
        audio_items = [
            ("Audio Format", self.song.format),
            ("Bitrate", f"{self.song.bitrate_kbps} kbps" if self.song.bitrate_kbps else None),
            ("Sample Rate", f"{self.song.sample_rate_hz} Hz" if self.song.sample_rate_hz else None),
            ("Bits Per Sample", f"{self.song.bits_per_sample} bits" if self.song.bits_per_sample else None),
            ("Channels", f"{self.song.channels} ch" if self.song.channels else None),
            ("File Size", f"{self.song.file_size_human} ({self.song.file_size_bytes:,} bytes)"),
            ("File Name", self.song.file_name),
            ("Physical Path", self.song.file_path),
            ("Last Modified", self.song.last_modified),
        ]
        content_layout.addWidget(make_section("Audio Stream & File Info", audio_items))

        # 4. Web Artwork Links & HTML Anchor Section
        web_box = QFrame()
        web_box.setStyleSheet("background-color: #1e1e2e; border: 1px solid #313244; border-radius: 6px; padding: 6px;")
        web_layout = QVBoxLayout(web_box)
        web_layout.setContentsMargins(8, 6, 8, 6)
        web_layout.setSpacing(6)

        web_title = QLabel("Web Album Artwork Links (Stored in JSON)")
        web_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #a6e3a1; border-bottom: 1px solid #313244; padding-bottom: 3px;")
        web_layout.addWidget(web_title)

        url_text = self.song.album_art_web_url or "—"
        html_text = self.song.album_art_html_link or "—"

        lbl_web_url = QLabel(f"<b>Direct Web Link:</b> {url_text}")
        lbl_web_url.setStyleSheet("color: #89b4fa; font-size: 11px;")
        lbl_web_url.setWordWrap(True)
        lbl_web_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        web_layout.addWidget(lbl_web_url)

        lbl_html_link = QLabel(f"<b>HTML Link:</b> {html_text}")
        lbl_html_link.setStyleSheet("color: #a6adc8; font-size: 11px;")
        lbl_html_link.setWordWrap(True)
        lbl_html_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        web_layout.addWidget(lbl_html_link)

        btn_row = QHBoxLayout()
        if self.song.album_art_web_url:
            btn_open_web = QPushButton("🌐 Open Image Link in Browser")
            btn_open_web.setStyleSheet("background-color: #89b4fa; color: #11111b; font-weight: bold; padding: 5px 10px;")
            btn_open_web.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.song.album_art_web_url)))
            btn_row.addWidget(btn_open_web)

            btn_copy_url = QPushButton("📋 Copy Image URL")
            btn_copy_url.clicked.connect(lambda: QApplication.clipboard().setText(self.song.album_art_web_url))
            btn_row.addWidget(btn_copy_url)

        if self.song.album_art_html_link:
            btn_copy_html = QPushButton("📋 Copy HTML Link")
            btn_copy_html.clicked.connect(lambda: QApplication.clipboard().setText(self.song.album_art_html_link))
            btn_row.addWidget(btn_copy_html)

        btn_row.addStretch()
        web_layout.addLayout(btn_row)
        content_layout.addWidget(web_box)

        content_layout.addStretch()
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll, stretch=1)

        # Bottom buttons
        bottom_row = QHBoxLayout()
        btn_explorer = QPushButton("📁 Show File in Explorer")
        btn_explorer.clicked.connect(self._open_in_explorer)
        bottom_row.addWidget(btn_explorer)

        bottom_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet("background-color: #45475a; color: #ffffff; padding: 6px 18px;")
        btn_close.clicked.connect(self.accept)
        bottom_row.addWidget(btn_close)
        main_layout.addLayout(bottom_row)

    def _open_in_explorer(self):
        if os.path.exists(self.song.file_path):
            subprocess.Popen(f'explorer /select,"{os.path.abspath(self.song.file_path)}"')

    def _apply_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QPushButton {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 6px 12px;
                color: #cdd6f4;
            }
            QPushButton:hover {
                background-color: #45475a;
                color: #ffffff;
            }
            QScrollBar:vertical {
                background-color: #181926;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #45475a;
                border-radius: 5px;
                min-height: 20px;
            }
        """)


class MusicPlayerWindow(QMainWindow):
    """
    Polished Multi-Page Music Library Browser & Player.
    Features:
    - All Songs Tab
    - Incomplete Metadata & VLC Fingerprint Tab with Artwork Filters, Tag Writer & Cover Art Fetcher
    - Unindexed & Failed Files Tab
    - Unified Persistent Audio Player with Live Album Art Thumbnail
    """

    song_selected = pyqtSignal(AudioMetadata)

    def __init__(
        self,
        songs: Optional[List[AudioMetadata]] = None,
        unindexed: Optional[List[FileScanStatus]] = None,
        parent: Optional[QWidget] = None,
        player_engine: str = "vlc",
        songs_json_path: str = DEFAULT_SONGS_JSON,
    ):
        super().__init__(parent)
        self.setWindowTitle("Antigravity Music Library & Player (VLC Fingerprint & Artwork Enabled)")
        self.resize(1200, 760)
        self.setMinimumSize(880, 560)

        self.songs_json_path = os.path.abspath(songs_json_path)
        self.all_songs: List[AudioMetadata] = songs or []
        self.unindexed_files: List[FileScanStatus] = unindexed or []
        
        # User preference: whether to treat missing artwork as making a song "incomplete"
        self.require_artwork_for_complete = True

        self.filtered_all_songs: List[AudioMetadata] = list(self.all_songs)
        self.incomplete_songs: List[AudioMetadata] = []
        self._recalculate_incomplete_list()

        self.filtered_incomplete_songs: List[AudioMetadata] = list(self.incomplete_songs)
        self.filtered_unindexed: List[FileScanStatus] = list(self.unindexed_files)

        self.current_song_index: Optional[int] = None
        self.current_active_list: List[AudioMetadata] = self.filtered_all_songs
        self._is_seeking = False

        # Initialize audio engine
        try:
            self.player: BaseAudioPlayer = get_best_player(preferred_backend=player_engine)
        except Exception:
            self.player = QtAudioPlayer()

        self._setup_ui()
        self._apply_theme()

        # Populate tables
        self.populate_all_songs_table(self.filtered_all_songs)
        self.populate_incomplete_table(self.filtered_incomplete_songs)
        self.populate_unindexed_table(self.filtered_unindexed)

        # Update tab titles with counts
        self._update_tab_headers()

        # Timer for polling playback position
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(250)
        self.update_timer.timeout.connect(self._sync_playback_progress)
        self.update_timer.start()

    def _recalculate_incomplete_list(self):
        res = []
        for s in self.all_songs:
            if self.require_artwork_for_complete:
                if s.has_incomplete_metadata:
                    res.append(s)
            else:
                if s.is_missing_tags:
                    res.append(s)
        self.incomplete_songs = res

    def _setup_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Tabs container
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # --- Tab 1: All Songs ---
        tab_all = QWidget()
        layout_all = QVBoxLayout(tab_all)
        layout_all.setContentsMargins(8, 10, 8, 8)
        layout_all.setSpacing(8)

        search_layout = QHBoxLayout()
        self.search_all = QLineEdit()
        self.search_all.setPlaceholderText("🔍  Search all songs by title, artist, album, genre, or path...")
        self.search_all.textChanged.connect(self._on_search_all_changed)
        self.search_all.setFixedHeight(34)
        search_layout.addWidget(self.search_all)

        btn_clear_all = QPushButton("Clear")
        btn_clear_all.setFixedHeight(34)
        btn_clear_all.clicked.connect(lambda: self.search_all.clear())
        search_layout.addWidget(btn_clear_all)

        self.lbl_stats_all = QLabel(f"Songs: {len(self.all_songs):,}")
        self.lbl_stats_all.setStyleSheet("font-weight: bold; color: #89b4fa; padding: 0 8px;")
        search_layout.addWidget(self.lbl_stats_all)
        layout_all.addLayout(search_layout)

        self.table_all = QTableWidget()
        self.table_all.setColumnCount(9)
        self.table_all.setHorizontalHeaderLabels([
            "#", "Title", "Artist", "Album", "Duration", "Format", "Bitrate", "Art", "Path"
        ])
        self._configure_table(self.table_all)
        self.table_all.cellDoubleClicked.connect(self._on_all_row_double_clicked)
        self.table_all.customContextMenuRequested.connect(lambda pos: self._show_song_context_menu(pos, self.table_all, self.filtered_all_songs))
        layout_all.addWidget(self.table_all)

        self.tabs.addTab(tab_all, "🎵 All Songs")

        # --- Tab 2: Incomplete Metadata & VLC Fingerprint ---
        tab_incomplete = QWidget()
        layout_incomplete = QVBoxLayout(tab_incomplete)
        layout_incomplete.setContentsMargins(8, 10, 8, 8)
        layout_incomplete.setSpacing(8)

        # Filter row
        filter_bar_layout = QHBoxLayout()
        self.search_inc = QLineEdit()
        self.search_inc.setPlaceholderText("🔍  Filter incomplete songs...")
        self.search_inc.textChanged.connect(self._on_search_incomplete_changed)
        self.search_inc.setFixedHeight(34)
        filter_bar_layout.addWidget(self.search_inc, stretch=2)

        self.combo_inc_category = QComboBox()
        self.combo_inc_category.addItems([
            "Show: All Incomplete",
            "Show: Missing Tags (Title/Artist/Album)",
            "Show: Missing Artwork Only",
            "Show: Enriched by VLC",
        ])
        self.combo_inc_category.setFixedHeight(34)
        self.combo_inc_category.currentIndexChanged.connect(lambda _: self._on_search_incomplete_changed(self.search_inc.text()))
        filter_bar_layout.addWidget(self.combo_inc_category)

        self.chk_require_art = QCheckBox("Count missing artwork as incomplete")
        self.chk_require_art.setChecked(True)
        self.chk_require_art.setStyleSheet("color: #bac2de; font-size: 11px;")
        self.chk_require_art.setToolTip(
            "Uncheck this if songs with complete Title, Artist, and Album should be considered complete even if they lack cover artwork."
        )
        self.chk_require_art.toggled.connect(self._on_toggle_require_art)
        filter_bar_layout.addWidget(self.chk_require_art)

        self.lbl_stats_inc = QLabel(f"Incomplete: {len(self.incomplete_songs):,}")
        self.lbl_stats_inc.setStyleSheet("font-weight: bold; color: #fab387; padding: 0 8px;")
        filter_bar_layout.addWidget(self.lbl_stats_inc)
        layout_incomplete.addLayout(filter_bar_layout)

        # Action Buttons Row
        action_bar_layout = QHBoxLayout()
        
        self.btn_vlc_fingerprint_all = QPushButton("⚡ Fingerprint All with VLC")
        self.btn_vlc_fingerprint_all.setFixedHeight(34)
        self.btn_vlc_fingerprint_all.setToolTip("Parse and enrich incomplete tracks using LibVLC with live progress dialog")
        self.btn_vlc_fingerprint_all.clicked.connect(self._fingerprint_all_incomplete)
        action_bar_layout.addWidget(self.btn_vlc_fingerprint_all)

        self.btn_fetch_artwork_all = QPushButton("🖼️ Fetch Missing Album Art")
        self.btn_fetch_artwork_all.setFixedHeight(34)
        self.btn_fetch_artwork_all.setStyleSheet("color: #f9e2af; border-color: #f9e2af;")
        self.btn_fetch_artwork_all.setToolTip("Search and download high-resolution album cover artwork (iTunes, Deezer, VLC cache) for tracks missing artwork.")
        self.btn_fetch_artwork_all.clicked.connect(self._on_fetch_artwork_clicked)
        action_bar_layout.addWidget(self.btn_fetch_artwork_all)

        self.btn_write_tags_to_files = QPushButton("💾 Write Metadata to Audio Files")
        self.btn_write_tags_to_files.setFixedHeight(34)
        self.btn_write_tags_to_files.setStyleSheet("font-weight: bold; color: #a6e3a1; border-color: #a6e3a1;")
        self.btn_write_tags_to_files.setToolTip("Save the current metadata (Title, Artist, Album, etc.) and embed cover art directly into the actual MP3/WAV/FLAC files on disk.")
        self.btn_write_tags_to_files.clicked.connect(self._on_write_tags_clicked)
        action_bar_layout.addWidget(self.btn_write_tags_to_files)

        action_bar_layout.addStretch()
        layout_incomplete.addLayout(action_bar_layout)

        self.table_incomplete = QTableWidget()
        self.table_incomplete.setColumnCount(8)
        self.table_incomplete.setHorizontalHeaderLabels([
            "#", "Title", "Artist", "Album", "Missing Fields", "VLC Status", "Artwork", "Path"
        ])
        self._configure_table(self.table_incomplete)
        self.table_incomplete.cellDoubleClicked.connect(self._on_incomplete_row_double_clicked)
        self.table_incomplete.customContextMenuRequested.connect(lambda pos: self._show_song_context_menu(pos, self.table_incomplete, self.filtered_incomplete_songs))
        layout_incomplete.addWidget(self.table_incomplete)

        self.tabs.addTab(tab_incomplete, "⚠️ Incomplete Metadata")

        # --- Tab 3: Unindexed & Failed Files ---
        tab_unindexed = QWidget()
        layout_unindexed = QVBoxLayout(tab_unindexed)
        layout_unindexed.setContentsMargins(8, 10, 8, 8)
        layout_unindexed.setSpacing(8)

        top_un_layout = QHBoxLayout()
        self.search_un = QLineEdit()
        self.search_un.setPlaceholderText("🔍  Filter failed or skipped files...")
        self.search_un.textChanged.connect(self._on_search_unindexed_changed)
        self.search_un.setFixedHeight(34)
        top_un_layout.addWidget(self.search_un)

        self.lbl_stats_un = QLabel(f"Unindexed: {len(self.unindexed_files):,}")
        self.lbl_stats_un.setStyleSheet("font-weight: bold; color: #f38ba8; padding: 0 8px;")
        top_un_layout.addWidget(self.lbl_stats_un)
        layout_unindexed.addLayout(top_un_layout)

        self.table_unindexed = QTableWidget()
        self.table_unindexed.setColumnCount(6)
        self.table_unindexed.setHorizontalHeaderLabels([
            "#", "File Name", "Reason / Failure Cause", "Details", "Size", "File Path"
        ])
        self._configure_table(self.table_unindexed)
        self.table_unindexed.customContextMenuRequested.connect(self._show_unindexed_context_menu)
        layout_unindexed.addWidget(self.table_unindexed)

        self.tabs.addTab(tab_unindexed, "❌ Unindexed & Failed Files")

        main_layout.addWidget(self.tabs)

        # --- Bottom Playback Controls Frame ---
        controls_frame = QFrame()
        controls_frame.setObjectName("controlsFrame")
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setContentsMargins(15, 10, 15, 12)
        controls_layout.setSpacing(8)

        # Seek Bar
        seek_layout = QHBoxLayout()
        seek_layout.setSpacing(10)
        self.lbl_current_time = QLabel("00:00")
        self.lbl_current_time.setFixedWidth(50)
        self.lbl_current_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        seek_layout.addWidget(self.lbl_current_time)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.sliderPressed.connect(self._on_seek_started)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        seek_layout.addWidget(self.seek_slider)

        self.lbl_total_time = QLabel("00:00")
        self.lbl_total_time.setFixedWidth(50)
        seek_layout.addWidget(self.lbl_total_time)
        controls_layout.addLayout(seek_layout)

        # Button Bar with Artwork Thumbnail Preview
        btn_bar_layout = QHBoxLayout()
        btn_bar_layout.setSpacing(10)

        self.btn_prev = QPushButton("⏮ Prev")
        self.btn_prev.setFixedWidth(75)
        self.btn_prev.clicked.connect(self.play_previous)
        btn_bar_layout.addWidget(self.btn_prev)

        self.btn_play = QPushButton("▶ Play")
        self.btn_play.setFixedWidth(85)
        self.btn_play.setStyleSheet("font-weight: bold;")
        self.btn_play.clicked.connect(self.toggle_play_pause)
        btn_bar_layout.addWidget(self.btn_play)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setFixedWidth(75)
        self.btn_stop.clicked.connect(self.stop_playback)
        btn_bar_layout.addWidget(self.btn_stop)

        self.btn_next = QPushButton("⏭ Next")
        self.btn_next.setFixedWidth(75)
        self.btn_next.clicked.connect(self.play_next)
        btn_bar_layout.addWidget(self.btn_next)

        # Album Art Thumbnail in Player
        self.lbl_now_playing_art = QLabel()
        self.lbl_now_playing_art.setFixedSize(42, 42)
        self.lbl_now_playing_art.setStyleSheet("background-color: #313244; border-radius: 6px; border: 1px solid #45475a;")
        self.lbl_now_playing_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_now_playing_art.setText("🎵")
        btn_bar_layout.addWidget(self.lbl_now_playing_art)

        # Now Playing info
        self.lbl_now_playing = QLabel("No track loaded")
        self.lbl_now_playing.setStyleSheet("font-size: 13px; font-weight: bold; color: #eceff4; padding-left: 6px;")
        btn_bar_layout.addWidget(self.lbl_now_playing, stretch=1)

        # Engine selector
        self.combo_engine = QComboBox()
        self.combo_engine.addItems(["Engine: VLC", "Engine: QtMultimedia"])
        if isinstance(self.player, QtAudioPlayer):
            self.combo_engine.setCurrentIndex(1)
        self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        btn_bar_layout.addWidget(self.combo_engine)

        # Volume
        lbl_vol = QLabel("🔊")
        btn_bar_layout.addWidget(lbl_vol)

        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(self.player.get_volume())
        self.vol_slider.setFixedWidth(100)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        btn_bar_layout.addWidget(self.vol_slider)

        controls_layout.addLayout(btn_bar_layout)
        main_layout.addWidget(controls_frame)

    def _configure_table(self, table: QTableWidget):
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def _update_tab_headers(self):
        self.tabs.setTabText(0, f"🎵 All Songs ({len(self.all_songs):,})")
        self.tabs.setTabText(1, f"⚠️ Incomplete Metadata ({len(self.incomplete_songs):,})")
        self.tabs.setTabText(2, f"❌ Unindexed Failed ({len(self.unindexed_files):,})")

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QWidget {
                color: #cdd6f4;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                font-size: 12px;
            }
            QTabWidget::pane {
                border: 1px solid #313244;
                border-radius: 6px;
                background-color: #181825;
            }
            QTabBar::tab {
                background-color: #24273a;
                color: #a6adc8;
                padding: 8px 18px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #313244;
                color: #89b4fa;
                border-bottom: 2px solid #89b4fa;
            }
            QTabBar::tab:hover {
                color: #ffffff;
            }
            QLineEdit {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 12px;
                color: #ffffff;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #89b4fa;
            }
            QTableWidget {
                background-color: #181825;
                alternate-background-color: #1e1e2e;
                border: none;
                gridline-color: #313244;
                selection-background-color: #45475a;
                selection-color: #ffffff;
            }
            QHeaderView::section {
                background-color: #313244;
                color: #a6adc8;
                padding: 6px;
                font-weight: bold;
                border: none;
                border-right: 1px solid #45475a;
            }
            QPushButton {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 12px;
                color: #cdd6f4;
            }
            QPushButton:hover {
                background-color: #45475a;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #585b70;
            }
            QFrame#controlsFrame {
                background-color: #24273a;
                border-radius: 10px;
                border: 1px solid #363a4f;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #45475a;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #89b4fa;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #cdd6f4;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
            QComboBox {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 4px 8px;
                color: #cdd6f4;
            }
            QCheckBox {
                color: #bac2de;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                background-color: #313244;
                border: 1px solid #585b70;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #89b4fa;
            }
        """)

    # ------------------------------------------------------------------
    # Table Population
    # ------------------------------------------------------------------
    def populate_all_songs_table(self, songs: List[AudioMetadata]):
        self.table_all.setRowCount(len(songs))
        for row, song in enumerate(songs):
            item_num = QTableWidgetItem(str(row + 1))
            item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_title = QTableWidgetItem(song.title or song.file_name)
            item_artist = QTableWidgetItem(song.artist or "Unknown")
            item_album = QTableWidgetItem(song.album or "Unknown")
            item_duration = QTableWidgetItem(song.duration_formatted)
            item_duration.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_fmt = QTableWidgetItem(song.format)
            item_fmt.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            br_str = f"{song.bitrate_kbps} kbps" if song.bitrate_kbps else "-"
            item_bitrate = QTableWidgetItem(br_str)
            item_bitrate.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            art_str = "🖼 Yes" if song.has_album_art else "❌ None"
            item_art = QTableWidgetItem(art_str)
            item_art.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_path = QTableWidgetItem(song.file_path)

            self.table_all.setItem(row, 0, item_num)
            self.table_all.setItem(row, 1, item_title)
            self.table_all.setItem(row, 2, item_artist)
            self.table_all.setItem(row, 3, item_album)
            self.table_all.setItem(row, 4, item_duration)
            self.table_all.setItem(row, 5, item_fmt)
            self.table_all.setItem(row, 6, item_bitrate)
            self.table_all.setItem(row, 7, item_art)
            self.table_all.setItem(row, 8, item_path)

        self.lbl_stats_all.setText(f"Showing: {len(songs):,} of {len(self.all_songs):,}")

    def populate_incomplete_table(self, songs: List[AudioMetadata]):
        self.table_incomplete.setRowCount(len(songs))
        for row, song in enumerate(songs):
            item_num = QTableWidgetItem(str(row + 1))
            item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_title = QTableWidgetItem(song.title or song.file_name)
            item_artist = QTableWidgetItem(song.artist or "Unknown")
            item_album = QTableWidgetItem(song.album or "Unknown")

            missing_str = ", ".join(song.missing_fields) if song.missing_fields else "Complete"
            item_missing = QTableWidgetItem(missing_str)
            item_missing.setForeground(QColor("#fab387"))

            vlc_st = song.vlc_status or ("VLC Parsed" if song.vlc_fingerprinted else "Not run")
            item_vlc = QTableWidgetItem(vlc_st)
            item_vlc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if "Enriched" in vlc_st:
                item_vlc.setForeground(QColor("#a6e3a1"))

            art_str = "🖼 Yes" if song.has_album_art else "❌ No Art"
            item_art = QTableWidgetItem(art_str)
            item_art.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_path = QTableWidgetItem(song.file_path)

            self.table_incomplete.setItem(row, 0, item_num)
            self.table_incomplete.setItem(row, 1, item_title)
            self.table_incomplete.setItem(row, 2, item_artist)
            self.table_incomplete.setItem(row, 3, item_album)
            self.table_incomplete.setItem(row, 4, item_missing)
            self.table_incomplete.setItem(row, 5, item_vlc)
            self.table_incomplete.setItem(row, 6, item_art)
            self.table_incomplete.setItem(row, 7, item_path)

        self.lbl_stats_inc.setText(f"Showing: {len(songs):,} of {len(self.incomplete_songs):,}")

    def populate_unindexed_table(self, unindexed: List[FileScanStatus]):
        self.table_unindexed.setRowCount(len(unindexed))
        for row, item in enumerate(unindexed):
            item_num = QTableWidgetItem(str(row + 1))
            item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_name = QTableWidgetItem(item.file_name)
            item_reason = QTableWidgetItem(item.reason)
            item_reason.setForeground(QColor("#f38ba8"))

            item_err = QTableWidgetItem(item.error_details or "-")
            item_size = QTableWidgetItem(item.file_size_human)
            item_size.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_path = QTableWidgetItem(item.file_path)

            self.table_unindexed.setItem(row, 0, item_num)
            self.table_unindexed.setItem(row, 1, item_name)
            self.table_unindexed.setItem(row, 2, item_reason)
            self.table_unindexed.setItem(row, 3, item_err)
            self.table_unindexed.setItem(row, 4, item_size)
            self.table_unindexed.setItem(row, 5, item_path)

        self.lbl_stats_un.setText(f"Showing: {len(unindexed):,} of {len(self.unindexed_files):,}")

    # ------------------------------------------------------------------
    # Search & Category Filters
    # ------------------------------------------------------------------
    def _on_search_all_changed(self, text: str):
        q = text.strip().lower()
        if not q:
            self.filtered_all_songs = list(self.all_songs)
        else:
            self.filtered_all_songs = [
                s for s in self.all_songs
                if q in s.title.lower() or q in s.artist.lower()
                or q in s.album.lower() or q in s.genre.lower() or q in s.file_path.lower()
            ]
        self.populate_all_songs_table(self.filtered_all_songs)

    def _on_toggle_require_art(self, checked: bool):
        self.require_artwork_for_complete = checked
        self._recalculate_incomplete_list()
        self._on_search_incomplete_changed(self.search_inc.text())
        self._update_tab_headers()

    def _on_search_incomplete_changed(self, text: str):
        q = text.strip().lower()
        cat_idx = self.combo_inc_category.currentIndex()

        candidates = self.incomplete_songs

        if cat_idx == 1:  # Missing Tags (Title/Artist/Album)
            candidates = [s for s in candidates if s.is_missing_tags]
        elif cat_idx == 2:  # Missing Artwork Only
            candidates = [s for s in candidates if s.is_missing_art_only]
        elif cat_idx == 3:  # Enriched by VLC
            candidates = [s for s in candidates if "Enriched" in s.vlc_status]

        if not q:
            self.filtered_incomplete_songs = list(candidates)
        else:
            self.filtered_incomplete_songs = [
                s for s in candidates
                if q in s.title.lower() or q in s.artist.lower()
                or q in s.album.lower() or q in s.file_path.lower()
                or any(q in m.lower() for m in s.missing_fields)
            ]
        self.populate_incomplete_table(self.filtered_incomplete_songs)

    def _on_search_unindexed_changed(self, text: str):
        q = text.strip().lower()
        if not q:
            self.filtered_unindexed = list(self.unindexed_files)
        else:
            self.filtered_unindexed = [
                u for u in self.unindexed_files
                if q in u.file_name.lower() or q in u.reason.lower()
                or (u.error_details and q in u.error_details.lower())
                or q in u.file_path.lower()
            ]
        self.populate_unindexed_table(self.filtered_unindexed)

    # ------------------------------------------------------------------
    # Row Double Clicks & Playback
    # ------------------------------------------------------------------
    def _on_all_row_double_clicked(self, row: int, col: int):
        self.current_active_list = self.filtered_all_songs
        self.play_index(row)

    def _on_incomplete_row_double_clicked(self, row: int, col: int):
        self.current_active_list = self.filtered_incomplete_songs
        self.play_index(row)

    def play_index(self, index: int):
        if not (0 <= index < len(self.current_active_list)):
            return

        self.current_song_index = index
        song = self.current_active_list[index]
        self.song_selected.emit(song)

        loaded = self.player.load(song.file_path)
        if loaded:
            self.player.play()
            self.btn_play.setText("⏸ Pause")
            
            # Update Album Art Thumbnail in Player Bar
            if song.has_album_art and song.album_art_path and os.path.isfile(song.album_art_path):
                pm = QPixmap(song.album_art_path)
                if not pm.isNull():
                    scaled_pm = pm.scaled(42, 42, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    self.lbl_now_playing_art.setPixmap(scaled_pm)
                    self.lbl_now_playing_art.setText("")
                else:
                    self.lbl_now_playing_art.setPixmap(QPixmap())
                    self.lbl_now_playing_art.setText("🎵")
            else:
                self.lbl_now_playing_art.setPixmap(QPixmap())
                self.lbl_now_playing_art.setText("🎵")

            self.lbl_now_playing.setText(f"🎵  {song.title} — {song.artist} ({song.format})")
            self.lbl_total_time.setText(song.duration_formatted)
        else:
            self.lbl_now_playing.setText(f"⚠️ Failed to open: {song.file_name}")

    def toggle_play_pause(self):
        if self.player.is_playing():
            self.player.pause()
            self.btn_play.setText("▶ Play")
        else:
            if self.current_song_index is None and self.current_active_list:
                self.play_index(0)
            else:
                self.player.play()
                self.btn_play.setText("⏸ Pause")

    def stop_playback(self):
        self.player.stop()
        self.btn_play.setText("▶ Play")
        self.lbl_current_time.setText("00:00")
        self.seek_slider.setValue(0)

    def play_next(self):
        if not self.current_active_list:
            return
        if self.current_song_index is None:
            self.play_index(0)
        else:
            next_idx = (self.current_song_index + 1) % len(self.current_active_list)
            self.play_index(next_idx)

    def play_previous(self):
        if not self.current_active_list:
            return
        if self.current_song_index is None:
            self.play_index(0)
        else:
            prev_idx = (self.current_song_index - 1) % len(self.current_active_list)
            self.play_index(prev_idx)

    def _on_seek_started(self):
        self._is_seeking = True

    def _on_seek_released(self):
        dur = self.player.get_duration()
        if dur > 0:
            target_sec = (self.seek_slider.value() / 1000.0) * dur
            self.player.seek(target_sec)
        self._is_seeking = False

    def _on_volume_changed(self, value: int):
        self.player.set_volume(value)

    def _on_engine_changed(self, index: int):
        cur_file = self.player.current_file
        is_playing = self.player.is_playing()
        cur_pos = self.player.get_position()
        self.player.cleanup()

        if index == 0:
            try:
                self.player = VLCPlayer()
            except Exception as e:
                self.combo_engine.setCurrentIndex(1)
                self.lbl_now_playing.setText(f"VLC unavailable: {e}")
                self.player = QtAudioPlayer()
        else:
            self.player = QtAudioPlayer()

        self.player.set_volume(self.vol_slider.value())
        if cur_file:
            self.player.load(cur_file)
            self.player.seek(cur_pos)
            if is_playing:
                self.player.play()

    def _sync_playback_progress(self):
        if not self._is_seeking and self.player.is_playing():
            pos = self.player.get_position()
            dur = self.player.get_duration()
            self.lbl_current_time.setText(format_seconds(pos))
            if dur > 0:
                self.lbl_total_time.setText(format_seconds(dur))
                slider_val = int((pos / dur) * 1000)
                self.seek_slider.setValue(slider_val)

    # ------------------------------------------------------------------
    # Asynchronous VLC Live Fingerprinting Action
    # ------------------------------------------------------------------
    def _fingerprint_all_incomplete(self):
        targets = self.filtered_incomplete_songs if self.filtered_incomplete_songs else self.incomplete_songs
        if not targets:
            QMessageBox.information(
                self,
                "No Tracks to Fingerprint",
                "There are no incomplete tracks matching your current filter!"
            )
            return

        dialog = VLCProgressDialog(
            songs_to_process=targets,
            all_library_songs=self.all_songs,
            songs_json_path=self.songs_json_path,
            parent=self,
        )
        dialog.exec()

        self._recalculate_incomplete_list()
        self._on_search_incomplete_changed(self.search_inc.text())
        self._on_search_all_changed(self.search_all.text())
        self._update_tab_headers()

    # ------------------------------------------------------------------
    # Asynchronous Album Artwork Search & Fetcher Action
    # ------------------------------------------------------------------
    def _on_fetch_artwork_clicked(self):
        """Batch searches and downloads album artwork for tracks missing artwork."""
        missing_art_tracks = [s for s in self.filtered_incomplete_songs if not s.has_album_art]
        if not missing_art_tracks:
            missing_art_tracks = [s for s in self.all_songs if not s.has_album_art]

        if not missing_art_tracks:
            QMessageBox.information(self, "All Tracks Have Artwork", "All tracks in this view already have album artwork!")
            return

        dialog = AlbumArtFetchProgressDialog(
            songs_to_fetch=missing_art_tracks,
            all_library_songs=self.all_songs,
            songs_json_path=self.songs_json_path,
            parent=self
        )
        dialog.exec()

        self._recalculate_incomplete_list()
        self._on_search_incomplete_changed(self.search_inc.text())
        self._on_search_all_changed(self.search_all.text())
        self._update_tab_headers()

    # ------------------------------------------------------------------
    # Write Metadata & Embed Cover Art to Audio Files
    # ------------------------------------------------------------------
    def _on_write_tags_clicked(self):
        enriched_tracks = [s for s in self.all_songs if "Enriched" in s.vlc_status or s.has_album_art]
        visible_tracks = self.filtered_incomplete_songs

        if not visible_tracks and not enriched_tracks:
            QMessageBox.information(self, "No Tracks to Write", "No modified or filtered tracks found to write.")
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Write Metadata & Embed Cover Art")
        msg.setText("Do you want to write metadata and embed cover artwork directly into audio files?")
        msg.setInformativeText(
            "This will permanently update the physical files on your drive:\n"
            "- MP3 files: Updates ID3v2.3 tags and embeds APIC front cover artwork\n"
            "- WAV files: Updates RIFF INFO chunks\n"
            "- FLAC files: Updates Vorbis comments and embeds picture blocks\n\n"
            "Select which tracks you would like to write:"
        )

        btn_filtered = msg.addButton(f"Write to Visible Tracks ({len(visible_tracks):,})", QMessageBox.ButtonRole.AcceptRole)
        btn_enriched = None
        if enriched_tracks:
            btn_enriched = msg.addButton(f"Write to Enriched / Artwork Tracks ({len(enriched_tracks):,})", QMessageBox.ButtonRole.AcceptRole)
        btn_cancel = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)

        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_cancel or clicked is None:
            return

        if clicked == btn_filtered:
            targets = visible_tracks
        elif btn_enriched and clicked == btn_enriched:
            targets = enriched_tracks
        else:
            return

        dialog = FileTagWriterProgressDialog(
            songs_to_write=targets,
            all_library_songs=self.all_songs,
            songs_json_path=self.songs_json_path,
            parent=self
        )
        dialog.exec()

        self.populate_all_songs_table(self.filtered_all_songs)
        self.populate_incomplete_table(self.filtered_incomplete_songs)

    # ------------------------------------------------------------------
    # Context Menus
    # ------------------------------------------------------------------
    def _show_song_context_menu(self, pos, table: QTableWidget, song_list: List[AudioMetadata]):
        item = table.itemAt(pos)
        if not item:
            return
        row = item.row()
        if not (0 <= row < len(song_list)):
            return

        song = song_list[row]
        menu = QMenu(self)

        act_play = menu.addAction("▶  Play Track")
        act_details = menu.addAction("ℹ️  View Extended Details & Web Links")
        act_fingerprint = menu.addAction("⚡  Fingerprint with LibVLC")
        act_fetch_art = menu.addAction("🖼️  Search & Fetch Album Art")
        act_write_tag = menu.addAction("💾  Write Metadata & Artwork into This File")
        menu.addSeparator()
        act_explorer = menu.addAction("📁  Show in File Explorer")
        act_copy = menu.addAction("📋  Copy Path")

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == act_play:
            self.current_active_list = song_list
            self.play_index(row)
        elif action == act_details:
            self._show_extended_details_dialog(song)
        elif action == act_fingerprint:
            VLCMetadataEnricher.enrich(song)
            try:
                StorageManager.update_songs_catalog(self.all_songs, self.songs_json_path)
            except Exception:
                pass
            self._recalculate_incomplete_list()
            self.populate_all_songs_table(self.filtered_all_songs)
            self.populate_incomplete_table(self.filtered_incomplete_songs)
            self._update_tab_headers()
        elif action == act_fetch_art:
            found = AlbumArtManager.resolve_artwork(song, enable_online_download=True)
            if found:
                try:
                    StorageManager.update_songs_catalog(self.all_songs, self.songs_json_path)
                except Exception:
                    pass
                self._recalculate_incomplete_list()
                self.populate_all_songs_table(self.filtered_all_songs)
                self.populate_incomplete_table(self.filtered_incomplete_songs)
                self._update_tab_headers()
                QMessageBox.information(self, "Artwork Found", f"Cover art located and linked for:\n{song.title} - {song.artist}")
            else:
                QMessageBox.warning(self, "Artwork Not Found", f"Could not locate album cover art for:\n{song.artist} - {song.album}")
        elif action == act_write_tag:
            ok, err = AudioMetadataWriter.write_metadata(song)
            if ok:
                try:
                    StorageManager.update_songs_catalog(self.all_songs, self.songs_json_path)
                except Exception:
                    pass
                QMessageBox.information(self, "Tag Saved", f"Successfully wrote metadata & cover art into:\n{song.file_name}")
            else:
                QMessageBox.warning(self, "Write Failed", f"Could not write metadata to {song.file_name}:\n{err}")
        elif action == act_explorer:
            if os.path.exists(song.file_path):
                subprocess.Popen(f'explorer /select,"{os.path.abspath(song.file_path)}"')
        elif action == act_copy:
            QApplication.clipboard().setText(song.file_path)

    def _show_extended_details_dialog(self, song: AudioMetadata):
        dlg = ExtendedTrackDetailsDialog(song, parent=self)
        dlg.exec()

    def _show_unindexed_context_menu(self, pos):
        item = self.table_unindexed.itemAt(pos)
        if not item:
            return
        row = item.row()
        if not (0 <= row < len(self.filtered_unindexed)):
            return

        un_item = self.filtered_unindexed[row]
        menu = QMenu(self)

        act_explorer = menu.addAction("📁  Show in File Explorer")
        act_copy = menu.addAction("📋  Copy Path")

        action = menu.exec(self.table_unindexed.viewport().mapToGlobal(pos))
        if action == act_explorer:
            if os.path.exists(un_item.file_path):
                subprocess.Popen(f'explorer /select,"{os.path.abspath(un_item.file_path)}"')
        elif action == act_copy:
            QApplication.clipboard().setText(un_item.file_path)

    def closeEvent(self, event):
        self.update_timer.stop()
        self.player.cleanup()
        event.accept()


def launch_gui(
    songs: List[AudioMetadata],
    unindexed: Optional[List[FileScanStatus]] = None,
    preferred_engine: str = "vlc",
    songs_json_path: str = DEFAULT_SONGS_JSON,
):
    """Standalone entrypoint to launch the GUI music player with all 3 tabs."""
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    window = MusicPlayerWindow(
        songs=songs,
        unindexed=unindexed,
        player_engine=preferred_engine,
        songs_json_path=songs_json_path,
    )
    window.show()
    app.exec()
