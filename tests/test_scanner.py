"""
Unit and Integration Tests for Media Scanner
============================================
Tests metadata extraction, smart incremental HDD refresh,
VLC fingerprinting/enrichment, incomplete metadata detection,
dual JSON persistence, and multi-tab GUI interfaces.
"""

import os
import sys
import unittest
import tempfile
import shutil

from media_scanner.metadata import MetadataExtractor, AudioMetadata, VLCMetadataEnricher
from media_scanner.scanner import AudioIndexer, ScanResult, FileScanStatus
from media_scanner.storage import StorageManager
from media_scanner.player import VLCPlayer, QtAudioPlayer
from sample_data_gen import generate_sample_library, create_sine_wave


class TestMediaScanner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="audio_test_lib_")
        generate_sample_library(cls.test_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_wav_metadata_extraction(self):
        wav_path = os.path.join(self.test_dir, "Pop", "summer_vibes.wav")
        self.assertTrue(os.path.isfile(wav_path))

        meta = MetadataExtractor.extract(wav_path)
        self.assertEqual(meta.format, "WAV")
        self.assertEqual(meta.title, "Summer Vibes")
        self.assertEqual(meta.artist, "Solar Beats")
        self.assertEqual(meta.album, "Sunny Days")
        self.assertEqual(meta.genre, "Pop")
        self.assertEqual(meta.year, "2025")
        self.assertGreater(meta.duration_seconds, 2.0)
        self.assertGreater(meta.file_size_bytes, 1000)

    def test_incomplete_metadata_detection(self):
        # Create a track with no ID3 tags or album art
        untagged_path = os.path.join(self.test_dir, "Pop", "untagged_track.wav")
        create_sine_wave(untagged_path, duration_sec=1.5)

        meta = MetadataExtractor.extract(untagged_path)
        self.assertTrue(meta.has_incomplete_metadata)
        self.assertTrue(any(f in meta.missing_fields for f in ["artist", "album", "album_art"]))

    def test_vlc_enrichment(self):
        wav_path = os.path.join(self.test_dir, "Pop", "summer_vibes.wav")
        meta = MetadataExtractor.extract(wav_path)
        # Attempt enrichment with LibVLC
        VLCMetadataEnricher.enrich(meta)
        self.assertTrue(meta.vlc_fingerprinted or meta.vlc_status != "")

    def test_corrupted_file_handling(self):
        corrupt_path = os.path.join(self.test_dir, "Rock", "broken_recording.mp3")
        with self.assertRaises(Exception):
            MetadataExtractor.extract(corrupt_path)

    def test_smart_incremental_refresh(self):
        indexer = AudioIndexer()

        # 1. Initial scan
        res1 = indexer.scan_folders([self.test_dir], recursive=True)
        self.assertGreater(res1.song_count, 0)
        initial_song_count = res1.song_count

        out_songs = os.path.join(tempfile.gettempdir(), "test_songs_cache.json")
        out_unindexed = os.path.join(tempfile.gettempdir(), "test_unindexed_cache.json")
        StorageManager.save_scan_result(res1, out_songs, out_unindexed)

        # 2. Load cache
        cached_songs, cached_unindexed, folders = StorageManager.load_cached_library(out_songs, out_unindexed)
        self.assertEqual(len(cached_songs), initial_song_count)

        # 3. Second scan with cache (no changes on disk)
        res2 = indexer.scan_folders(
            [self.test_dir],
            recursive=True,
            cached_songs=cached_songs,
            cached_unindexed=cached_unindexed,
        )
        # Verify 0 files needed to be re-indexed!
        self.assertEqual(res2.new_files_count, 0)
        self.assertEqual(res2.modified_files_count, 0)
        self.assertEqual(res2.cached_files_count, res2.total_files_examined)

        # 4. Add a new file and test incremental detection
        new_track = os.path.join(self.test_dir, "Pop", "new_bonus_track.wav")
        create_sine_wave(new_track, duration_sec=1.0)

        res3 = indexer.scan_folders(
            [self.test_dir],
            recursive=True,
            cached_songs=cached_songs,
            cached_unindexed=cached_unindexed,
        )
        self.assertEqual(res3.new_files_count, 1)
        self.assertEqual(res3.song_count, initial_song_count + 1)

    def test_gui_offscreen_multi_tabs(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        from media_scanner.gui import MusicPlayerWindow

        app = QApplication.instance() or QApplication([])

        songs = [
            MetadataExtractor.extract(os.path.join(self.test_dir, "Pop", "summer_vibes.wav")),
            MetadataExtractor.extract(os.path.join(self.test_dir, "Rock", "electric_pulse.mp3")),
        ]
        unindexed = [
            FileScanStatus(
                file_path="dummy.txt",
                file_name="dummy.txt",
                file_size_bytes=10,
                file_size_human="10 B",
                extension=".txt",
                is_song=False,
                reason="Non-audio file",
            )
        ]

        win = MusicPlayerWindow(songs=songs, unindexed=unindexed)
        self.assertEqual(win.tabs.count(), 3)

        # Switch to Incomplete Tab
        win.tabs.setCurrentIndex(1)
        self.assertEqual(win.tabs.currentIndex(), 1)

        # Switch to Unindexed Tab
        win.tabs.setCurrentIndex(2)
        self.assertEqual(win.tabs.currentIndex(), 2)
        self.assertEqual(win.table_unindexed.rowCount(), 1)

        win.close()
        win.update_timer.stop()
        win.player.cleanup()


if __name__ == "__main__":
    unittest.main()
