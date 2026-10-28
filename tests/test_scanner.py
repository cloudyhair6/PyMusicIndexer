"""
Unit and Integration Tests for Media Scanner
============================================
Tests metadata extraction, folder traversal, progress reporting,
dual JSON serialization, and player backend initializations.
"""

import os
import unittest
import tempfile
import shutil

from media_scanner.metadata import MetadataExtractor, AudioMetadata
from media_scanner.scanner import AudioIndexer, ScanResult
from media_scanner.storage import StorageManager
from media_scanner.player import VLCPlayer, QtAudioPlayer, get_best_player
from sample_data_gen import generate_sample_library


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

    def test_mp3_metadata_extraction(self):
        mp3_path = os.path.join(self.test_dir, "Rock", "electric_pulse.mp3")
        self.assertTrue(os.path.isfile(mp3_path))

        meta = MetadataExtractor.extract(mp3_path)
        self.assertEqual(meta.format, "MP3")
        self.assertEqual(meta.title, "Electric Pulse")
        self.assertEqual(meta.artist, "Volt Riders")
        self.assertEqual(meta.album, "High Voltage")
        self.assertEqual(meta.genre, "Electronic Rock")
        self.assertEqual(meta.year, "2026")

    def test_corrupted_file_handling(self):
        corrupt_path = os.path.join(self.test_dir, "Rock", "broken_recording.mp3")
        with self.assertRaises(Exception):
            MetadataExtractor.extract(corrupt_path)

    def test_indexer_and_dual_json_output(self):
        indexer = AudioIndexer()
        progress_records = []

        def track_progress(cur, total, fn):
            progress_records.append((cur, total, fn))

        result = indexer.scan_folders([self.test_dir], recursive=True, progress_callback=track_progress)

        self.assertGreater(result.total_files_examined, 0)
        self.assertGreaterEqual(result.song_count, 4)  # 2 WAVs + 2 MP3s
        self.assertGreaterEqual(result.unindexed_count, 4)  # txt, jpg, pdf, corrupt mp3
        self.assertEqual(len(progress_records), result.total_files_examined)

        # Verify storage
        out_songs = os.path.join(self.test_dir, "test_songs.json")
        out_unindexed = os.path.join(self.test_dir, "test_unindexed.json")

        s_path, u_path = StorageManager.save_scan_result(
            result,
            songs_filepath=out_songs,
            unindexed_filepath=out_unindexed,
        )

        self.assertTrue(os.path.isfile(s_path))
        self.assertTrue(os.path.isfile(u_path))

        loaded_songs = StorageManager.load_songs(s_path)
        self.assertEqual(len(loaded_songs), result.song_count)
        self.assertEqual(loaded_songs[0].title, result.songs[0].title)

        loaded_unindexed = StorageManager.load_unindexed(u_path)
        self.assertEqual(len(loaded_unindexed), result.unindexed_count)

    def test_player_backend_loading(self):
        wav_path = os.path.join(self.test_dir, "Pop", "summer_vibes.wav")

        # Test VLC Player
        try:
            vlc_player = VLCPlayer()
            loaded = vlc_player.load(wav_path)
            self.assertTrue(loaded)
            vlc_player.set_volume(75)
            self.assertEqual(vlc_player.get_volume(), 75)
            vlc_player.cleanup()
        except RuntimeError:
            pass  # If VLC is unavailable in a test runner

        # Test Qt Audio Player
        try:
            qt_player = QtAudioPlayer()
            loaded_qt = qt_player.load(wav_path)
            self.assertTrue(loaded_qt)
            qt_player.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
