"""
GUI Music Browser, Inspector & Player
=====================================
Multi-tab PyQt6 graphical interface providing:
- Tab 1: All Songs (Instant search, table, play)
- Tab 2: Incomplete Metadata (VLC fingerprinted tracks, missing art/tags)
- Tab 3: Unindexed & Failed Files (Corrupt audio, non-music files, errors)
- Persistent audio player powered by LibVLC or QtMultimedia
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QFont, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton,
    QSlider, QLabel, QComboBox, QMenu, QAbstractItemView, QFrame,
    QTabWidget, QMessageBox
)

from .metadata import AudioMetadata, VLCMetadataEnricher, format_seconds
from .scanner import FileScanStatus
from .player import BaseAudioPlayer, VLCPlayer, QtAudioPlayer, get_best_player


class MusicPlayerWindow(QMainWindow):
    """
    Polished Multi-Page Music Library Browser & Player.
    Features:
    - All Songs Tab
    - Incomplete Metadata & VLC Fingerprint Tab
    - Unindexed & Failed Files Tab
    - Unified Persistent Audio Player
    """

    song_selected = pyqtSignal(AudioMetadata)

    def __init__(
        self,
        songs: Optional[List[AudioMetadata]] = None,
        unindexed: Optional[List[FileScanStatus]] = None,
        parent: Optional[QWidget] = None,
        player_engine: str = "vlc",
    ):
        super().__init__(parent)
        self.setWindowTitle("Antigravity Music Library & Player (VLC Fingerprint Enabled)")
        self.resize(1180, 750)
        self.setMinimumSize(850, 550)

        self.all_songs: List[AudioMetadata] = songs or []
        self.unindexed_files: List[FileScanStatus] = unindexed or []
        
        self.filtered_all_songs: List[AudioMetadata] = list(self.all_songs)
        self.incomplete_songs: List[AudioMetadata] = [s for s in self.all_songs if s.has_incomplete_metadata]
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

        self.lbl_stats_all = QLabel(f"Songs: {len(self.all_songs)}")
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

        top_inc_layout = QHBoxLayout()
        self.search_inc = QLineEdit()
        self.search_inc.setPlaceholderText("🔍  Filter incomplete songs...")
        self.search_inc.textChanged.connect(self._on_search_incomplete_changed)
        self.search_inc.setFixedHeight(34)
        top_inc_layout.addWidget(self.search_inc)

        self.btn_vlc_fingerprint_all = QPushButton("⚡ Fingerprint All with VLC")
        self.btn_vlc_fingerprint_all.setFixedHeight(34)
        self.btn_vlc_fingerprint_all.setToolTip("Parse and enrich incomplete tracks using LibVLC")
        self.btn_vlc_fingerprint_all.clicked.connect(self._fingerprint_all_incomplete)
        top_inc_layout.addWidget(self.btn_vlc_fingerprint_all)

        self.lbl_stats_inc = QLabel(f"Incomplete: {len(self.incomplete_songs)}")
        self.lbl_stats_inc.setStyleSheet("font-weight: bold; color: #fab387; padding: 0 8px;")
        top_inc_layout.addWidget(self.lbl_stats_inc)
        layout_incomplete.addLayout(top_inc_layout)

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

        self.lbl_stats_un = QLabel(f"Unindexed: {len(self.unindexed_files)}")
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

        # Button Bar
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

        # Now Playing info
        self.lbl_now_playing = QLabel("No track loaded")
        self.lbl_now_playing.setStyleSheet("font-size: 13px; font-weight: bold; color: #eceff4; padding-left: 8px;")
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
        self.tabs.setTabText(0, f"🎵 All Songs ({len(self.all_songs)})")
        self.tabs.setTabText(1, f"⚠️ Incomplete Metadata ({len(self.incomplete_songs)})")
        self.tabs.setTabText(2, f"❌ Unindexed & Failed ({len(self.unindexed_files)})")

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

        self.lbl_stats_all.setText(f"Showing: {len(songs)} of {len(self.all_songs)}")

    def populate_incomplete_table(self, songs: List[AudioMetadata]):
        self.table_incomplete.setRowCount(len(songs))
        for row, song in enumerate(songs):
            item_num = QTableWidgetItem(str(row + 1))
            item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_title = QTableWidgetItem(song.title or song.file_name)
            item_artist = QTableWidgetItem(song.artist or "Unknown")
            item_album = QTableWidgetItem(song.album or "Unknown")

            missing_str = ", ".join(song.missing_fields) if song.missing_fields else "Incomplete"
            item_missing = QTableWidgetItem(missing_str)
            item_missing.setForeground(QColor("#fab387"))

            vlc_st = song.vlc_status or ("VLC Parsed" if song.vlc_fingerprinted else "Not run")
            item_vlc = QTableWidgetItem(vlc_st)
            item_vlc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

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

        self.lbl_stats_inc.setText(f"Showing: {len(songs)} of {len(self.incomplete_songs)}")

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

        self.lbl_stats_un.setText(f"Showing: {len(unindexed)} of {len(self.unindexed_files)}")

    # ------------------------------------------------------------------
    # Search Filters
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

    def _on_search_incomplete_changed(self, text: str):
        q = text.strip().lower()
        if not q:
            self.filtered_incomplete_songs = list(self.incomplete_songs)
        else:
            self.filtered_incomplete_songs = [
                s for s in self.incomplete_songs
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
            art_status = "🖼" if song.has_album_art else ""
            self.lbl_now_playing.setText(f"🎵  {song.title} — {song.artist} ({song.format}) {art_status}")
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
    # VLC Live Fingerprinting Actions
    # ------------------------------------------------------------------
    def _fingerprint_all_incomplete(self):
        """Run VLC fingerprinting / parsing over all incomplete tracks."""
        if not self.incomplete_songs:
            QMessageBox.information(self, "No Incomplete Tracks", "All tracks currently have complete metadata and artwork!")
            return

        enriched_count = 0
        for song in self.incomplete_songs:
            changed = VLCMetadataEnricher.enrich(song)
            if changed:
                enriched_count += 1

        # Re-evaluate
        self.incomplete_songs = [s for s in self.all_songs if s.has_incomplete_metadata]
        self.filtered_incomplete_songs = list(self.incomplete_songs)
        self.populate_incomplete_table(self.filtered_incomplete_songs)
        self.populate_all_songs_table(self.filtered_all_songs)
        self._update_tab_headers()

        QMessageBox.information(
            self,
            "VLC Fingerprinting Complete",
            f"VLC deep parsing examined {len(self.incomplete_songs)} tracks.\nEnriched: {enriched_count} tracks."
        )

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
        act_fingerprint = menu.addAction("⚡  Fingerprint with LibVLC")
        act_explorer = menu.addAction("📁  Show in File Explorer")
        act_copy = menu.addAction("📋  Copy Path")

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == act_play:
            self.current_active_list = song_list
            self.play_index(row)
        elif action == act_fingerprint:
            VLCMetadataEnricher.enrich(song)
            self.populate_all_songs_table(self.filtered_all_songs)
            self.populate_incomplete_table(self.filtered_incomplete_songs)
            self._update_tab_headers()
        elif action == act_explorer:
            if os.path.exists(song.file_path):
                subprocess.Popen(f'explorer /select,"{os.path.abspath(song.file_path)}"')
        elif action == act_copy:
            QApplication.clipboard().setText(song.file_path)

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
    preferred_engine: str = "vlc"
):
    """Standalone entrypoint to launch the GUI music player with all 3 tabs."""
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    window = MusicPlayerWindow(songs=songs, unindexed=unindexed, player_engine=preferred_engine)
    window.show()
    app.exec()
