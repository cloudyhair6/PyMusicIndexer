"""
Test suite for extended Windows Details metadata and Web Artwork Links.
"""

import os
import sys
import json
import unittest
import tempfile
import struct

from media_scanner.metadata import AudioMetadata, MetadataExtractor
from media_scanner.artwork import AlbumArtManager
from media_scanner.writer import AudioMetadataWriter
from media_scanner.storage import StorageManager


class TestExtendedMetadataAndWebLinks(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="ext_meta_test_")
        AlbumArtManager.set_cache_directory(os.path.join(self.temp_dir, "art_cache"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_audio_metadata_extended_fields_serialization(self):
        meta = AudioMetadata(
            file_path="C:/Music/test_track.mp3",
            file_name="test_track.mp3",
            file_size_bytes=4096000,
            file_size_human="3.91 MB",
            extension=".mp3",
            format="MP3",
            title="Electric Dreams",
            subtitle="Extended 12 Inch Mix",
            rating=5,
            comments="Remastered 2024",
            artist="Synth Wave",
            album_artist="Synth Wave Band",
            album="Neon Nights",
            year="1984",
            track_number="04/12",
            disc_number="1/2",
            genre="Synthwave",
            duration_seconds=245.5,
            duration_formatted="04:06",
            bitrate_kbps=320,
            sample_rate_hz=44100,
            channels=2,
            bits_per_sample=16,
            publisher="Retro Records",
            encoded_by="LAME 3.100",
            author_url="https://synthwave.example.com",
            copyright="(C) 1984 Retro Records",
            composer="Giorgio Moroder",
            conductor="John Williams",
            grouping="Electronic Soundtrack",
            mood="Nostalgic",
            initial_key="Am",
            bpm=120,
            is_compilation=True,
            has_album_art=True,
            album_art_path="C:/Music/cover.jpg",
            album_art_web_url="https://is1-ssl.mzstatic.com/image/thumb/v4/cover/600x600bb.jpg",
            album_art_html_link='<a href="https://is1-ssl.mzstatic.com/image/thumb/v4/cover/600x600bb.jpg" target="_blank" download="cover.jpg">Download Album Art</a>'
        )

        d = meta.to_dict()
        # Verify JSON serialization includes all Windows Details properties
        self.assertEqual(d["title"], "Electric Dreams")
        self.assertEqual(d["subtitle"], "Extended 12 Inch Mix")
        self.assertEqual(d["rating"], 5)
        self.assertEqual(d["comments"], "Remastered 2024")
        self.assertEqual(d["disc_number"], "1/2")
        self.assertEqual(d["publisher"], "Retro Records")
        self.assertEqual(d["composer"], "Giorgio Moroder")
        self.assertEqual(d["bpm"], 120)
        self.assertTrue(d["is_compilation"])
        self.assertIn("600x600bb.jpg", d["album_art_web_url"])
        self.assertIn('<a href="https://is1-ssl.mzstatic.com', d["album_art_html_link"])

        # Test round-trip serialization through StorageManager
        json_path = os.path.join(self.temp_dir, "test_catalog.json")
        StorageManager.update_songs_catalog([meta], json_path)

        loaded_songs = StorageManager.load_songs(json_path)
        self.assertEqual(len(loaded_songs), 1)
        loaded = loaded_songs[0]
        self.assertEqual(loaded.title, "Electric Dreams")
        self.assertEqual(loaded.subtitle, "Extended 12 Inch Mix")
        self.assertEqual(loaded.composer, "Giorgio Moroder")
        self.assertEqual(loaded.bpm, 120)
        self.assertEqual(loaded.rating, 5)
        self.assertEqual(loaded.album_art_web_url, meta.album_art_web_url)
        self.assertEqual(loaded.album_art_html_link, meta.album_art_html_link)

    def test_mp3_writer_and_extractor_roundtrip(self):
        # Create a mock MP3 with syncwords
        mp3_path = os.path.join(self.temp_dir, "roundtrip.mp3")
        with open(mp3_path, "wb") as f:
            for _ in range(20):
                # 4-byte MPEG audio header (MPEG-1 Layer 3, 128kbps, 44100Hz)
                f.write(b"\xff\xfb\x90\x00" + b"\x00" * 413)

        meta = MetadataExtractor.extract(mp3_path)
        meta.title = "Blue Sky"
        meta.artist = "Electric Light Orchestra"
        meta.album = "Out of the Blue"
        meta.year = "1977"
        meta.track_number = "7"
        meta.disc_number = "1"
        meta.genre = "Classic Rock"
        meta.composer = "Jeff Lynne"
        meta.publisher = "Jet Records"
        meta.comments = "Iconic track"
        meta.bpm = 128
        meta.rating = 5

        # Create dummy cover image
        art_path = os.path.join(self.temp_dir, "cover.jpg")
        with open(art_path, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 200 + b"\xff\xd9")
        meta.album_art_path = art_path
        meta.has_album_art = True

        # Write to physical MP3 file
        ok, err = AudioMetadataWriter.write_metadata(meta)
        self.assertTrue(ok, f"Write metadata failed: {err}")

        # Extract again from physical file
        re_extracted = MetadataExtractor.extract(mp3_path)
        self.assertEqual(re_extracted.title, "Blue Sky")
        self.assertEqual(re_extracted.artist, "Electric Light Orchestra")
        self.assertEqual(re_extracted.album, "Out of the Blue")
        self.assertEqual(re_extracted.year, "1977")
        self.assertEqual(re_extracted.composer, "Jeff Lynne")
        self.assertEqual(re_extracted.publisher, "Jet Records")
        self.assertEqual(re_extracted.rating, 5)
        self.assertEqual(re_extracted.bpm, 128)
        self.assertTrue(re_extracted.has_album_art)

    def test_direct_image_url_and_html_link(self):
        # Test 1: Direct CDN image URL
        meta = AudioMetadata(
            file_path="C:/Music/test.mp3",
            file_name="test.mp3",
            file_size_bytes=1024,
            file_size_human="1 KB",
            extension=".mp3",
            format="MP3",
            title="Come Together",
            artist="The Beatles",
            album="Abbey Road"
        )
        # Seed cache with direct image link
        AlbumArtManager._url_cache["the beatles__abbey road"] = "https://is1-ssl.mzstatic.com/image/thumb/Music/v4/abbeyroad/600x600bb.jpg"
        AlbumArtManager.resolve_artwork(meta, enable_online_download=False)

        self.assertIsNotNone(meta.album_art_web_url)
        self.assertTrue(meta.album_art_web_url.endswith(".jpg"))
        self.assertNotIn("google.com", meta.album_art_web_url)
        self.assertIn('<a href="https://is1-ssl.mzstatic.com', meta.album_art_html_link)
        self.assertIn('download="cover.jpg"', meta.album_art_html_link)

        # Test 2: Local artwork file links directly to the image file
        local_art = os.path.join(self.temp_dir, "local_cover.jpg")
        with open(local_art, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
        meta2 = AudioMetadata(
            file_path=os.path.join(self.temp_dir, "song.mp3"),
            file_name="song.mp3",
            file_size_bytes=1024,
            file_size_human="1 KB",
            extension=".mp3",
            format="MP3",
            title="Local Song",
            artist="Indie Artist",
            album="Indie Album",
            has_album_art=True,
            album_art_path=local_art
        )
        AlbumArtManager.resolve_artwork(meta2, enable_online_download=False)
        self.assertIn("local_cover.jpg", meta2.album_art_html_link)
        self.assertNotIn("google.com", meta2.album_art_html_link)


if __name__ == "__main__":
    unittest.main()
