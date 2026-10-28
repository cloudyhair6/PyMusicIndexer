"""
GUI Music Browser & Player
==========================
PyQt6 graphical interface providing instant multi-field search,
detailed song list table, and integrated audio playback via LibVLC or Qt.
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
    QSlider, QLabel, QComboBox, QMenu, QAbstractItemView, QFrame
)

from .metadata import AudioMetadata, format_seconds
from .player import BaseAudioPlayer, VLCPlayer, QtAudioPlayer, get_best_player


class MusicPlayerWindow(QMainWindow):
    """
    Polished Music Player and Search Interface.
    Can be used standalone or embedded in larger PyQt6 applications.
    """

    song_selected = pyqtSignal(AudioMetadata)

    def __init__(
        self,
        songs: Optional[List[AudioMetadata]] = None,
        parent: Optional[QWidget] = None,
        player_engine: str = "vlc",
    ):
        super().__init__(parent)
        self.setWindowTitle("Antigravity Music Library & Player")
        self.resize(1100, 700)
        self.setMinimumSize(800, 500)

        self.all_songs: List[AudioMetadata] = songs or []
        self.filtered_songs: List[AudioMetadata] = list(self.all_songs)
        self.current_song_index: Optional[int] = None
        self._is_seeking = False

        # Initialize audio engine
        try:
            self.player: BaseAudioPlayer = get_best_player(preferred_backend=player_engine)
        except Exception:
            self.player = QtAudioPlayer()

        self._setup_ui()
        self._apply_theme()
        self.populate_table(self.filtered_songs)

        # Timer for polling playback position
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(250)
        self.update_timer.timeout.connect(self._sync_playback_progress)
        self.update_timer.start()

    def _setup_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # 1. Search Bar & Summary
        search_layout = QHBoxLayout()
        search_layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍  Search by title, artist, album, genre, or path...")
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.setFixedHeight(36)
        search_layout.addWidget(self.search_input)

        self.btn_clear_search = QPushButton("Clear")
        self.btn_clear_search.setFixedHeight(36)
        self.btn_clear_search.clicked.connect(lambda: self.search_input.clear())
        search_layout.addWidget(self.btn_clear_search)

        self.lbl_stats = QLabel(f"Songs: {len(self.all_songs)}")
        self.lbl_stats.setStyleSheet("font-weight: bold; color: #88c0d0; padding: 0 8px;")
        search_layout.addWidget(self.lbl_stats)

        main_layout.addLayout(search_layout)

        # 2. Songs Table View
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "#", "Title", "Artist", "Album", "Duration", "Format", "Bitrate", "Path"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        main_layout.addWidget(self.table)

        # 3. Playback Controls Card
        controls_frame = QFrame()
        controls_frame.setObjectName("controlsFrame")
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setContentsMargins(15, 10, 15, 12)
        controls_layout.setSpacing(8)

        # Progress / Seek Bar
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

        # Buttons and Now-Playing Status
        btn_bar_layout = QHBoxLayout()
        btn_bar_layout.setSpacing(12)

        # Prev / Play / Stop / Next
        self.btn_prev = QPushButton("⏮ Prev")
        self.btn_prev.setFixedWidth(80)
        self.btn_prev.clicked.connect(self.play_previous)
        btn_bar_layout.addWidget(self.btn_prev)

        self.btn_play = QPushButton("▶ Play")
        self.btn_play.setFixedWidth(90)
        self.btn_play.setStyleSheet("font-weight: bold;")
        self.btn_play.clicked.connect(self.toggle_play_pause)
        btn_bar_layout.addWidget(self.btn_play)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setFixedWidth(80)
        self.btn_stop.clicked.connect(self.stop_playback)
        btn_bar_layout.addWidget(self.btn_stop)

        self.btn_next = QPushButton("⏭ Next")
        self.btn_next.setFixedWidth(80)
        self.btn_next.clicked.connect(self.play_next)
        btn_bar_layout.addWidget(self.btn_next)

        # Now Playing Meta Info
        self.lbl_now_playing = QLabel("No track loaded")
        self.lbl_now_playing.setStyleSheet("font-size: 13px; font-weight: bold; color: #eceff4; padding-left: 10px;")
        btn_bar_layout.addWidget(self.lbl_now_playing, stretch=1)

        # Engine selector
        self.combo_engine = QComboBox()
        self.combo_engine.addItems(["Engine: VLC", "Engine: QtMultimedia"])
        if isinstance(self.player, QtAudioPlayer):
            self.combo_engine.setCurrentIndex(1)
        self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        btn_bar_layout.addWidget(self.combo_engine)

        # Volume Controls
        lbl_vol = QLabel("🔊")
        btn_bar_layout.addWidget(lbl_vol)

        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(self.player.get_volume())
        self.vol_slider.setFixedWidth(110)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        btn_bar_layout.addWidget(self.vol_slider)

        controls_layout.addLayout(btn_bar_layout)
        main_layout.addWidget(controls_frame)

    def _apply_theme(self):
        """Apply modern dark mode stylesheet."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QWidget {
                color: #cdd6f4;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                font-size: 12px;
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
                border: 1px solid #313244;
                border-radius: 8px;
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

    def set_songs(self, songs: List[AudioMetadata]):
        """Update the song catalog."""
        self.all_songs = songs
        self.filtered_songs = list(songs)
        self.populate_table(self.filtered_songs)

    def populate_table(self, songs: List[AudioMetadata]):
        """Render song rows into the QTableWidget."""
        self.table.setRowCount(len(songs))
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

            item_path = QTableWidgetItem(song.file_path)

            self.table.setItem(row, 0, item_num)
            self.table.setItem(row, 1, item_title)
            self.table.setItem(row, 2, item_artist)
            self.table.setItem(row, 3, item_album)
            self.table.setItem(row, 4, item_duration)
            self.table.setItem(row, 5, item_fmt)
            self.table.setItem(row, 6, item_bitrate)
            self.table.setItem(row, 7, item_path)

        self.lbl_stats.setText(f"Showing: {len(songs)} of {len(self.all_songs)}")

    def _on_search_text_changed(self, text: str):
        query = text.strip().lower()
        if not query:
            self.filtered_songs = list(self.all_songs)
        else:
            self.filtered_songs = [
                s for s in self.all_songs
                if query in s.title.lower()
                or query in s.artist.lower()
                or query in s.album.lower()
                or query in s.genre.lower()
                or query in s.file_path.lower()
            ]
        self.populate_table(self.filtered_songs)

    def _on_row_double_clicked(self, row: int, column: int):
        self.play_index(row)

    def play_index(self, index: int):
        """Play song at given index in the filtered songs list."""
        if 0 <= index < len(self.filtered_songs):
            self.current_song_index = index
            song = self.filtered_songs[index]
            self.table.selectRow(index)
            self.song_selected.emit(song)

            loaded = self.player.load(song.file_path)
            if loaded:
                self.player.play()
                self.btn_play.setText("⏸ Pause")
                self.lbl_now_playing.setText(f"🎵  {song.title} — {song.artist} ({song.format})")
                self.lbl_total_time.setText(song.duration_formatted)
            else:
                self.lbl_now_playing.setText(f"⚠️ Failed to open: {song.file_name}")

    def toggle_play_pause(self):
        if self.player.is_playing():
            self.player.pause()
            self.btn_play.setText("▶ Play")
        else:
            if self.current_song_index is None and self.filtered_songs:
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
        if not self.filtered_songs:
            return
        if self.current_song_index is None:
            self.play_index(0)
        else:
            next_idx = (self.current_song_index + 1) % len(self.filtered_songs)
            self.play_index(next_idx)

    def play_previous(self):
        if not self.filtered_songs:
            return
        if self.current_song_index is None:
            self.play_index(0)
        else:
            prev_idx = (self.current_song_index - 1) % len(self.filtered_songs)
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

    def _show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        row = item.row()
        if not (0 <= row < len(self.filtered_songs)):
            return

        song = self.filtered_songs[row]
        menu = QMenu(self)

        act_play = menu.addAction("▶  Play Track")
        act_explorer = menu.addAction("📁  Show in File Explorer")
        act_copy = menu.addAction("📋  Copy Path")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == act_play:
            self.play_index(row)
        elif action == act_explorer:
            if os.path.exists(song.file_path):
                subprocess.Popen(f'explorer /select,"{os.path.abspath(song.file_path)}"')
        elif action == act_copy:
            QApplication.clipboard().setText(song.file_path)

    def closeEvent(self, event):
        self.update_timer.stop()
        self.player.cleanup()
        event.accept()


def launch_gui(songs: List[AudioMetadata], preferred_engine: str = "vlc"):
    """Standalone entrypoint to launch the GUI music player."""
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    window = MusicPlayerWindow(songs=songs, player_engine=preferred_engine)
    window.show()
    app.exec()
