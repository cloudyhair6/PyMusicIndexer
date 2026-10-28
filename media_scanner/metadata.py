"""
Metadata Extraction Module
==========================
Extracts audio tags and stream properties from various audio formats.
Includes built-in pure-Python parsers for MP3, WAV, FLAC, OGG, and M4A,
with optional automatic escalation to `mutagen` or `tinytag` if installed.
"""

from __future__ import annotations

import os
import struct
import datetime
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, Tuple

# Check for optional third-party libraries
_MUTAGEN_AVAILABLE = False
_TINYTAG_AVAILABLE = False

try:
    import mutagen
    from mutagen.easyid3 import EasyID3
    _MUTAGEN_AVAILABLE = True
except ImportError:
    pass

try:
    import tinytag
    _TINYTAG_AVAILABLE = True
except ImportError:
    pass


AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".ogg", ".oga",
    ".m4a", ".aac", ".wma", ".aiff", ".aif",
    ".opus", ".alac", ".ape", ".mid", ".midi"
}


def format_seconds(seconds: float) -> str:
    """Format duration in seconds to MM:SS or HH:MM:SS."""
    if seconds is None or seconds < 0:
        return "00:00"
    total_seconds = int(round(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable bytes (KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


@dataclass
class AudioMetadata:
    """Encapsulates all extracted metadata for an audio track."""
    file_path: str
    file_name: str
    file_size_bytes: int
    file_size_human: str
    extension: str
    format: str
    title: str
    artist: str
    album: str
    album_artist: str
    genre: str
    year: Optional[str]
    track_number: Optional[str]
    duration_seconds: float
    duration_formatted: str
    bitrate_kbps: Optional[int]
    sample_rate_hz: Optional[int]
    channels: Optional[int]
    last_modified: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to a serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioMetadata":
        """Reconstruct AudioMetadata instance from dictionary."""
        return cls(**data)


class MetadataExtractor:
    """Universal audio metadata extractor with zero-dependency fallback."""

    @classmethod
    def is_audio_file(cls, file_path: str) -> bool:
        """Check if file extension is considered an audio format."""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in AUDIO_EXTENSIONS

    @classmethod
    def extract(cls, file_path: str) -> AudioMetadata:
        """
        Extract metadata from given audio file.
        Uses mutagen/tinytag if available, otherwise pure Python parser.
        Raises ValueError or IOError if file is corrupted or not a valid song.
        """
        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"File not found: {abs_path}")

        file_stat = os.stat(abs_path)
        file_size = file_stat.st_size
        mod_time = datetime.datetime.fromtimestamp(file_stat.st_mtime).isoformat()
        file_name = os.path.basename(abs_path)
        stem, ext = os.path.splitext(file_name)
        ext_lower = ext.lower()

        if not cls.is_audio_file(abs_path):
            raise ValueError(f"Unsupported audio format extension: {ext_lower}")

        # Try mutagen if available
        if _MUTAGEN_AVAILABLE:
            try:
                return cls._extract_with_mutagen(abs_path, file_stat, ext_lower)
            except Exception:
                pass  # Fallback to pure Python

        # Try tinytag if available
        if _TINYTAG_AVAILABLE:
            try:
                return cls._extract_with_tinytag(abs_path, file_stat, ext_lower)
            except Exception:
                pass  # Fallback to pure Python

        # Built-in pure Python extractors
        return cls._extract_pure_python(abs_path, file_stat, ext_lower)

    # ------------------------------------------------------------------
    # Optional Third-Party Adapters
    # ------------------------------------------------------------------
    @classmethod
    def _extract_with_mutagen(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        audio = mutagen.File(path)
        if audio is None:
            raise ValueError("Mutagen could not recognize audio stream")

        info = getattr(audio, "info", None)
        duration = getattr(info, "length", 0.0) or 0.0
        bitrate = getattr(info, "bitrate", None)
        if bitrate:
            bitrate = int(bitrate // 1000)
        sample_rate = getattr(info, "sample_rate", None)
        channels = getattr(info, "channels", None)

        tags = getattr(audio, "tags", None) or {}

        def get_tag(keys):
            for k in keys:
                if k in tags:
                    val = tags[k]
                    if isinstance(val, list) and len(val) > 0:
                        return str(val[0])
                    elif isinstance(val, str):
                        return val
            return ""

        title = get_tag(["title", "TIT2"]) or os.path.splitext(os.path.basename(path))[0]
        artist = get_tag(["artist", "TPE1"]) or "Unknown Artist"
        album = get_tag(["album", "TALB"]) or "Unknown Album"
        album_artist = get_tag(["albumartist", "TPE2"]) or artist
        genre = get_tag(["genre", "TCON"]) or "Unknown Genre"
        year = get_tag(["date", "year", "TDRC", "TYER"]) or None
        track = get_tag(["tracknumber", "TRCK"]) or None

        return AudioMetadata(
            file_path=path,
            file_name=os.path.basename(path),
            file_size_bytes=stat_res.st_size,
            file_size_human=format_file_size(stat_res.st_size),
            extension=ext,
            format=ext.lstrip(".").upper(),
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist,
            genre=genre,
            year=str(year) if year else None,
            track_number=str(track) if track else None,
            duration_seconds=float(duration),
            duration_formatted=format_seconds(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=sample_rate,
            channels=channels,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
        )

    @classmethod
    def _extract_with_tinytag(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        tag = tinytag.TinyTag.get(path)
        title = tag.title or os.path.splitext(os.path.basename(path))[0]
        artist = tag.artist or "Unknown Artist"
        album = tag.album or "Unknown Album"
        duration = tag.duration or 0.0

        return AudioMetadata(
            file_path=path,
            file_name=os.path.basename(path),
            file_size_bytes=stat_res.st_size,
            file_size_human=format_file_size(stat_res.st_size),
            extension=ext,
            format=ext.lstrip(".").upper(),
            title=title,
            artist=artist,
            album=album,
            album_artist=tag.albumartist or artist,
            genre=tag.genre or "Unknown Genre",
            year=str(tag.year) if tag.year else None,
            track_number=str(tag.track) if tag.track else None,
            duration_seconds=float(duration),
            duration_formatted=format_seconds(duration),
            bitrate_kbps=int(tag.bitrate) if tag.bitrate else None,
            sample_rate_hz=tag.samplerate,
            channels=tag.channels,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
        )

    # ------------------------------------------------------------------
    # Built-in Pure-Python Parsers
    # ------------------------------------------------------------------
    @classmethod
    def _extract_pure_python(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        """Route to format-specific pure-Python parser."""
        if ext == ".wav":
            return cls._parse_wav(path, stat_res, ext)
        elif ext == ".mp3":
            return cls._parse_mp3(path, stat_res, ext)
        elif ext == ".flac":
            return cls._parse_flac(path, stat_res, ext)
        elif ext in (".ogg", ".oga"):
            return cls._parse_ogg(path, stat_res, ext)
        elif ext in (".m4a", ".aac"):
            return cls._parse_m4a(path, stat_res, ext)
        else:
            return cls._parse_generic_audio(path, stat_res, ext)

    @classmethod
    def _parse_wav(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        """Parse standard WAV / RIFF header and optional INFO chunk."""
        import wave

        title = os.path.splitext(os.path.basename(path))[0]
        artist = "Unknown Artist"
        album = "Unknown Album"
        genre = "Unknown Genre"
        year = None
        track = None
        duration = 0.0
        sample_rate = None
        channels = None
        bitrate = None

        try:
            with wave.open(path, "rb") as wf:
                channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()
                sampwidth = wf.getsampwidth()
                if sample_rate > 0:
                    duration = n_frames / float(sample_rate)
                if duration > 0:
                    bitrate = int((stat_res.st_size * 8) / (duration * 1000))
        except Exception as e:
            # Try manual RIFF parse
            riff_info = cls._parse_riff_info_tags(path)
            if riff_info.get("duration"):
                duration = riff_info["duration"]
                channels = riff_info.get("channels")
                sample_rate = riff_info.get("sample_rate")
            else:
                raise ValueError(f"Corrupted or invalid WAV file: {e}")

        # Check for RIFF INFO tags
        tags = cls._parse_riff_info_tags(path)
        title = tags.get("INAM") or title
        artist = tags.get("IART") or artist
        album = tags.get("IPRD") or album
        genre = tags.get("IGNR") or genre
        year = tags.get("ICRD") or year
        track = tags.get("ITRK") or track

        return AudioMetadata(
            file_path=path,
            file_name=os.path.basename(path),
            file_size_bytes=stat_res.st_size,
            file_size_human=format_file_size(stat_res.st_size),
            extension=ext,
            format="WAV",
            title=title,
            artist=artist,
            album=album,
            album_artist=artist,
            genre=genre,
            year=year,
            track_number=track,
            duration_seconds=duration,
            duration_formatted=format_seconds(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=sample_rate,
            channels=channels,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
        )

    @classmethod
    def _parse_riff_info_tags(cls, path: str) -> Dict[str, Any]:
        """Extract INFO list chunk tags from RIFF file."""
        tags = {}
        try:
            with open(path, "rb") as f:
                header = f.read(12)
                if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                    return tags

                while True:
                    chunk_hdr = f.read(8)
                    if len(chunk_hdr) < 8:
                        break
                    chunk_id, chunk_size = struct.unpack("<4sI", chunk_hdr)
                    if chunk_id == b"fmt ":
                        fmt_data = f.read(chunk_size)
                        if len(fmt_data) >= 16:
                            audio_format, channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack("<HHIIHH", fmt_data[:16])
                            tags["channels"] = channels
                            tags["sample_rate"] = sample_rate
                            tags["bitrate"] = int((byte_rate * 8) // 1000)
                    elif chunk_id == b"data":
                        if "sample_rate" in tags and "channels" in tags and tags.get("bitrate"):
                            tags["duration"] = chunk_size / (tags["sample_rate"] * tags["channels"] * 2)
                        f.seek(chunk_size, 1)
                    elif chunk_id == b"LIST":
                        list_type = f.read(4)
                        if list_type == b"INFO":
                            bytes_left = chunk_size - 4
                            while bytes_left > 8:
                                sub_hdr = f.read(8)
                                bytes_left -= 8
                                if len(sub_hdr) < 8:
                                    break
                                sub_id, sub_size = struct.unpack("<4sI", sub_hdr)
                                tag_val = f.read(sub_size).decode("utf-8", errors="ignore").rstrip("\x00").strip()
                                bytes_left -= sub_size
                                if sub_size % 2 == 1:
                                    f.read(1)
                                    bytes_left -= 1
                                sub_name = sub_id.decode("ascii", errors="ignore")
                                tags[sub_name] = tag_val
                        else:
                            f.seek(chunk_size - 4, 1)
                    else:
                        f.seek(chunk_size, 1)
                    if chunk_size % 2 == 1:
                        f.read(1)
        except Exception:
            pass
        return tags

    @classmethod
    def _parse_mp3(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        """Parse MP3 ID3v2, ID3v1, and MPEG frame headers."""
        title = os.path.splitext(os.path.basename(path))[0]
        artist = "Unknown Artist"
        album = "Unknown Album"
        album_artist = ""
        genre = "Unknown Genre"
        year = None
        track = None
        bitrate = None
        sample_rate = None
        channels = None
        duration = 0.0

        id3v2_tags, audio_offset = cls._parse_id3v2(path)
        if id3v2_tags:
            title = id3v2_tags.get("TIT2") or id3v2_tags.get("TT2") or title
            artist = id3v2_tags.get("TPE1") or id3v2_tags.get("TP1") or artist
            album = id3v2_tags.get("TALB") or id3v2_tags.get("TAL") or album
            album_artist = id3v2_tags.get("TPE2") or ""
            genre = id3v2_tags.get("TCON") or id3v2_tags.get("TCO") or genre
            year = id3v2_tags.get("TDRC") or id3v2_tags.get("TYER") or id3v2_tags.get("TYE") or None
            track = id3v2_tags.get("TRCK") or id3v2_tags.get("TRK") or None

        # Check ID3v1 fallback if fields are empty
        if artist == "Unknown Artist" or album == "Unknown Album":
            id3v1_tags = cls._parse_id3v1(path)
            if id3v1_tags:
                if title == os.path.splitext(os.path.basename(path))[0] and id3v1_tags.get("title"):
                    title = id3v1_tags["title"]
                if artist == "Unknown Artist" and id3v1_tags.get("artist"):
                    artist = id3v1_tags["artist"]
                if album == "Unknown Album" and id3v1_tags.get("album"):
                    album = id3v1_tags["album"]
                if not year and id3v1_tags.get("year"):
                    year = id3v1_tags["year"]
                if not track and id3v1_tags.get("track"):
                    track = id3v1_tags["track"]

        # Parse MPEG Audio Frame Header to compute duration, bitrate, sample rate
        mp3_props = cls._parse_mpeg_frame_headers(path, audio_offset, stat_res.st_size)
        if mp3_props:
            duration = mp3_props.get("duration", 0.0)
            bitrate = mp3_props.get("bitrate")
            sample_rate = mp3_props.get("sample_rate")
            channels = mp3_props.get("channels")

        has_tags = bool(id3v2_tags or id3v1_tags)
        has_frames = bool(mp3_props and mp3_props.get("found"))

        if not has_tags and not has_frames:
            raise ValueError("Corrupted or invalid MP3 file: No valid ID3 tags or MPEG audio frames found.")

        return AudioMetadata(
            file_path=path,
            file_name=os.path.basename(path),
            file_size_bytes=stat_res.st_size,
            file_size_human=format_file_size(stat_res.st_size),
            extension=ext,
            format="MP3",
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist or artist,
            genre=genre,
            year=year,
            track_number=track,
            duration_seconds=duration,
            duration_formatted=format_seconds(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=sample_rate,
            channels=channels,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
        )

    @classmethod
    def _parse_id3v2(cls, path: str) -> Tuple[Dict[str, str], int]:
        """Extract ID3v2 tags and return tag dictionary and audio data start offset."""
        tags = {}
        audio_offset = 0
        try:
            with open(path, "rb") as f:
                header = f.read(10)
                if len(header) < 10 or header[:3] != b"ID3":
                    return tags, 0

                version_major = header[3]
                flags = header[5]
                # Syncsafe integer for ID3v2 size
                tag_size = ((header[6] & 0x7F) << 21) | ((header[7] & 0x7F) << 14) | ((header[8] & 0x7F) << 7) | (header[9] & 0x7F)
                audio_offset = 10 + tag_size
                if flags & 0x10:  # Footer present
                    audio_offset += 10

                tag_data = f.read(tag_size)
                pos = 0

                # Extended header check
                if flags & 0x20 and len(tag_data) >= 4:
                    ext_size = struct.unpack(">I", tag_data[:4])[0]
                    pos += ext_size

                while pos < len(tag_data) - 10:
                    if tag_data[pos] == 0:
                        break  # Padding reached

                    if version_major == 2:
                        frame_id = tag_data[pos:pos+3].decode("ascii", errors="ignore")
                        frame_size = struct.unpack(">I", b"\x00" + tag_data[pos+3:pos+6])[0]
                        header_size = 6
                    elif version_major == 3:
                        frame_id = tag_data[pos:pos+4].decode("ascii", errors="ignore")
                        frame_size = struct.unpack(">I", tag_data[pos+4:pos+8])[0]
                        header_size = 10
                    elif version_major >= 4:
                        frame_id = tag_data[pos:pos+4].decode("ascii", errors="ignore")
                        sb = tag_data[pos+4:pos+8]
                        frame_size = ((sb[0] & 0x7F) << 21) | ((sb[1] & 0x7F) << 14) | ((sb[2] & 0x7F) << 7) | (sb[3] & 0x7F)
                        header_size = 10
                    else:
                        break

                    pos += header_size
                    if pos + frame_size > len(tag_data):
                        break

                    raw_content = tag_data[pos:pos+frame_size]
                    pos += frame_size

                    # Text frame parsing
                    if frame_id.startswith("T") and frame_id not in ("TXXX", "TX") and len(raw_content) > 1:
                        encoding = raw_content[0]
                        data = raw_content[1:]
                        try:
                            if encoding == 0:
                                val = data.decode("iso-8859-1", errors="ignore")
                            elif encoding == 1:
                                val = data.decode("utf-16", errors="ignore")
                            elif encoding == 2:
                                val = data.decode("utf-16-be", errors="ignore")
                            elif encoding == 3:
                                val = data.decode("utf-8", errors="ignore")
                            else:
                                val = data.decode("utf-8", errors="ignore")
                            tags[frame_id] = val.strip("\x00").strip()
                        except Exception:
                            pass
        except Exception:
            pass

        return tags, audio_offset

    @classmethod
    def _parse_id3v1(cls, path: str) -> Dict[str, str]:
        """Extract ID3v1 trailer tags (last 128 bytes)."""
        tags = {}
        try:
            with open(path, "rb") as f:
                f.seek(-128, 2)
                buf = f.read(128)
                if len(buf) == 128 and buf[:3] == b"TAG":
                    tags["title"] = buf[3:33].decode("iso-8859-1", errors="ignore").strip("\x00").strip()
                    tags["artist"] = buf[33:63].decode("iso-8859-1", errors="ignore").strip("\x00").strip()
                    tags["album"] = buf[63:93].decode("iso-8859-1", errors="ignore").strip("\x00").strip()
                    tags["year"] = buf[93:97].decode("iso-8859-1", errors="ignore").strip("\x00").strip()
                    if buf[125] == 0:
                        tags["track"] = str(buf[126])
        except Exception:
            pass
        return tags

    @classmethod
    def _parse_mpeg_frame_headers(cls, path: str, start_offset: int, file_size: int) -> Optional[Dict[str, Any]]:
        """Scan for first valid MPEG audio syncword and calculate properties."""
        bitrate_map_v1_l3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
        samplerate_map_v1 = [44100, 48000, 32000, 0]
        samplerate_map_v2 = [22050, 24000, 16000, 0]

        res = {"found": False, "duration": 0.0, "bitrate": 128, "sample_rate": 44100, "channels": 2}
        found_sync = False
        try:
            with open(path, "rb") as f:
                f.seek(start_offset)
                chunk = f.read(8192)
                idx = 0
                while idx < len(chunk) - 4:
                    if chunk[idx] == 0xFF and (chunk[idx+1] & 0xE0) == 0xE0:
                        header = chunk[idx:idx+4]
                        version_id = (header[1] >> 3) & 0x03  # 3=MPEG1, 2=MPEG2, 0=MPEG2.5
                        layer_id = (header[1] >> 1) & 0x03    # 1=Layer3
                        bitrate_idx = (header[2] >> 4) & 0x0F
                        sr_idx = (header[2] >> 2) & 0x03
                        channel_mode = (header[3] >> 6) & 0x03

                        if version_id == 3 and layer_id == 1 and bitrate_idx < 15 and sr_idx < 3:
                            kbps = bitrate_map_v1_l3[bitrate_idx]
                            sr = samplerate_map_v1[sr_idx]
                            ch = 1 if channel_mode == 3 else 2
                            if kbps > 0 and sr > 0:
                                res["found"] = True
                                res["bitrate"] = kbps
                                res["sample_rate"] = sr
                                res["channels"] = ch
                                audio_bytes = max(0, file_size - start_offset)
                                res["duration"] = (audio_bytes * 8) / (kbps * 1000)
                                found_sync = True
                                break
                    idx += 1
        except Exception:
            pass

        return res if found_sync else None

    @classmethod
    def _parse_flac(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        """Parse native FLAC streaminfo and Vorbis comment block."""
        title = os.path.splitext(os.path.basename(path))[0]
        artist = "Unknown Artist"
        album = "Unknown Album"
        album_artist = ""
        genre = "Unknown Genre"
        year = None
        track = None
        duration = 0.0
        sample_rate = 44100
        channels = 2
        bitrate = None

        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != b"fLaC":
                raise ValueError("Not a valid FLAC file (missing fLaC signature)")

            while True:
                hdr = f.read(4)
                if len(hdr) < 4:
                    break
                is_last = (hdr[0] & 0x80) != 0
                block_type = hdr[0] & 0x7F
                block_len = (hdr[1] << 16) | (hdr[2] << 8) | hdr[3]
                block_data = f.read(block_len)

                if block_type == 0:  # STREAMINFO
                    if len(block_data) >= 18:
                        sample_rate = (block_data[10] << 12) | (block_data[11] << 4) | (block_data[12] >> 4)
                        channels = ((block_data[12] >> 1) & 0x07) + 1
                        total_samples = ((block_data[13] & 0x0F) << 32) | struct.unpack(">I", block_data[14:18])[0]
                        if sample_rate > 0:
                            duration = total_samples / float(sample_rate)
                            if duration > 0:
                                bitrate = int((stat_res.st_size * 8) / (duration * 1000))
                elif block_type == 4:  # VORBIS_COMMENT
                    comments = cls._parse_vorbis_comment_block(block_data)
                    title = comments.get("TITLE") or title
                    artist = comments.get("ARTIST") or artist
                    album = comments.get("ALBUM") or album
                    album_artist = comments.get("ALBUMARTIST") or ""
                    genre = comments.get("GENRE") or genre
                    year = comments.get("DATE") or comments.get("YEAR") or None
                    track = comments.get("TRACKNUMBER") or None

                if is_last:
                    break

        return AudioMetadata(
            file_path=path,
            file_name=os.path.basename(path),
            file_size_bytes=stat_res.st_size,
            file_size_human=format_file_size(stat_res.st_size),
            extension=ext,
            format="FLAC",
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist or artist,
            genre=genre,
            year=year,
            track_number=track,
            duration_seconds=duration,
            duration_formatted=format_seconds(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=sample_rate,
            channels=channels,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
        )

    @classmethod
    def _parse_vorbis_comment_block(cls, data: bytes) -> Dict[str, str]:
        """Parse standard Vorbis Comment block."""
        tags = {}
        try:
            pos = 0
            vendor_len = struct.unpack("<I", data[pos:pos+4])[0]
            pos += 4 + vendor_len
            num_comments = struct.unpack("<I", data[pos:pos+4])[0]
            pos += 4
            for _ in range(num_comments):
                if pos + 4 > len(data):
                    break
                c_len = struct.unpack("<I", data[pos:pos+4])[0]
                pos += 4
                comment_str = data[pos:pos+c_len].decode("utf-8", errors="ignore")
                pos += c_len
                if "=" in comment_str:
                    k, v = comment_str.split("=", 1)
                    tags[k.upper()] = v.strip()
        except Exception:
            pass
        return tags

    @classmethod
    def _parse_ogg(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        """Parse OGG file header and vorbis comments."""
        title = os.path.splitext(os.path.basename(path))[0]
        artist = "Unknown Artist"
        album = "Unknown Album"
        album_artist = ""
        genre = "Unknown Genre"
        year = None
        track = None
        duration = 0.0

        with open(path, "rb") as f:
            chunk = f.read(16384)
            if not chunk.startswith(b"OggS"):
                raise ValueError("Not a valid Ogg file (missing OggS signature)")

            # Scan for vorbis comment header (b"\x03vorbis")
            pos = chunk.find(b"\x03vorbis")
            if pos != -1:
                comment_data = chunk[pos+7:]
                comments = cls._parse_vorbis_comment_block(comment_data)
                title = comments.get("TITLE") or title
                artist = comments.get("ARTIST") or artist
                album = comments.get("ALBUM") or album
                album_artist = comments.get("ALBUMARTIST") or ""
                genre = comments.get("GENRE") or genre
                year = comments.get("DATE") or comments.get("YEAR") or None
                track = comments.get("TRACKNUMBER") or None

        return AudioMetadata(
            file_path=path,
            file_name=os.path.basename(path),
            file_size_bytes=stat_res.st_size,
            file_size_human=format_file_size(stat_res.st_size),
            extension=ext,
            format="OGG",
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist or artist,
            genre=genre,
            year=year,
            track_number=track,
            duration_seconds=duration,
            duration_formatted=format_seconds(duration),
            bitrate_kbps=None,
            sample_rate_hz=44100,
            channels=2,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
        )

    @classmethod
    def _parse_m4a(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        """Parse M4A / MP4 ISO base media atoms for metadata."""
        title = os.path.splitext(os.path.basename(path))[0]
        artist = "Unknown Artist"
        album = "Unknown Album"
        album_artist = ""
        genre = "Unknown Genre"
        year = None
        track = None
        duration = 0.0

        with open(path, "rb") as f:
            data = f.read(min(stat_res.st_size, 262144))
            if b"ftyp" not in data[:32]:
                raise ValueError("Not a valid MP4/M4A file (missing ftyp atom)")

            # Check for mvhd atom to extract duration
            mvhd_idx = data.find(b"mvhd")
            if mvhd_idx != -1 and mvhd_idx + 24 <= len(data):
                version = data[mvhd_idx+4]
                if version == 0 and mvhd_idx + 24 <= len(data):
                    timescale = struct.unpack(">I", data[mvhd_idx+16:mvhd_idx+20])[0]
                    dur_units = struct.unpack(">I", data[mvhd_idx+20:mvhd_idx+24])[0]
                    if timescale > 0:
                        duration = dur_units / float(timescale)

            def get_atom_str(atom_tag: bytes) -> Optional[str]:
                idx = data.find(atom_tag)
                if idx != -1 and idx + 24 < len(data):
                    data_box = data[idx:idx+80]
                    d_idx = data_box.find(b"data")
                    if d_idx != -1 and d_idx + 12 < len(data_box):
                        val_bytes = data_box[d_idx+8:]
                        return val_bytes.decode("utf-8", errors="ignore").rstrip("\x00").strip()
                return None

            title = get_atom_str(b"\xa9nam") or title
            artist = get_atom_str(b"\xa9ART") or artist
            album = get_atom_str(b"\xa9alb") or album
            year = get_atom_str(b"\xa9day") or None
            genre = get_atom_str(b"\xa9gen") or genre

        return AudioMetadata(
            file_path=path,
            file_name=os.path.basename(path),
            file_size_bytes=stat_res.st_size,
            file_size_human=format_file_size(stat_res.st_size),
            extension=ext,
            format="M4A",
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist or artist,
            genre=genre,
            year=year,
            track_number=track,
            duration_seconds=duration,
            duration_formatted=format_seconds(duration),
            bitrate_kbps=None,
            sample_rate_hz=44100,
            channels=2,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
        )

    @classmethod
    def _parse_generic_audio(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        """Fallback for other audio formats."""
        title = os.path.splitext(os.path.basename(path))[0]
        return AudioMetadata(
            file_path=path,
            file_name=os.path.basename(path),
            file_size_bytes=stat_res.st_size,
            file_size_human=format_file_size(stat_res.st_size),
            extension=ext,
            format=ext.lstrip(".").upper(),
            title=title,
            artist="Unknown Artist",
            album="Unknown Album",
            album_artist="Unknown Artist",
            genre="Unknown Genre",
            year=None,
            track_number=None,
            duration_seconds=0.0,
            duration_formatted="00:00",
            bitrate_kbps=None,
            sample_rate_hz=None,
            channels=None,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
        )
