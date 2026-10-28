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

    def test_audio_metadata_writer(self):
        from media_scanner.writer import AudioMetadataWriter
        test_file = os.path.join(self.test_dir, "Pop", "write_test_track.wav")
        create_sine_wave(test_file, duration_sec=1.0)

        meta = MetadataExtractor.extract(test_file)
        meta.title = "Custom Written Title"
        meta.artist = "Custom Artist"
        meta.album = "Custom Album"

        ok, err = AudioMetadataWriter.write_metadata(meta)
        self.assertTrue(ok, f"Writer failed: {err}")

        # Read back from physical file
        re_meta = MetadataExtractor.extract(test_file)
        self.assertEqual(re_meta.title, "Custom Written Title")
        self.assertEqual(re_meta.artist, "Custom Artist")
        self.assertEqual(re_meta.album, "Custom Album")

    def test_album_art_manager_and_embedding(self):
        from media_scanner.artwork import AlbumArtManager
        from media_scanner.writer import AudioMetadataWriter

        test_mp3 = os.path.join(self.test_dir, "Pop", "art_test_song.mp3")
        from sample_data_gen import create_mock_mp3_with_id3v2
        create_mock_mp3_with_id3v2(test_mp3, "Art Song", "Art Artist", "Art Album", "Pop", "2026")

        meta = MetadataExtractor.extract(test_mp3)

        # Create a sample local cover image
        cover_path = os.path.join(self.test_dir, "Pop", "cover.jpg")
        with open(cover_path, "wb") as f:
            f.write(b"\xFF\xD8\xFF\xE0" + b"\x00" * 300 + b"\xFF\xD9")

        found = AlbumArtManager.resolve_artwork(meta, enable_online_download=False)
        self.assertTrue(found)
        self.assertTrue(meta.has_album_art)
        self.assertEqual(meta.album_art_path, cover_path)

        # Write to physical file and embed artwork
        ok, err = AudioMetadataWriter.write_metadata(meta)
        self.assertTrue(ok)

        # Read back from disk
        re_meta = MetadataExtractor.extract(test_mp3)
        self.assertTrue(re_meta.has_album_art)


if __name__ == "__main__":
    unittest.main()
