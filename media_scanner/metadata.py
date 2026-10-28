"""
Metadata Extraction & VLC Fingerprinting Module
===============================================
Extracts full audio tags, stream properties, and extended Windows Details metadata:
- Description: Title, Subtitle, Rating, Comments
- Media: Contributing Artists, Album Artist, Album, Year, Track #, Genre, Duration
- Origin: Publisher, Encoded by, Author URL, Copyright
- Content: Composers, Conductors, Group description, Mood, Part of set (Disc #),
  Initial key, Beats-per-minute (BPM), Part of a compilation
- Web Artwork: album_art_web_url, album_art_html_link
Includes pure-Python parsers for MP3, WAV, FLAC, OGG, and M4A,
artwork detection, incomplete metadata classification, and LibVLC integration.
"""

from __future__ import annotations

import os
import sys
import struct
import datetime
import ctypes
import urllib.parse
from dataclasses import dataclass, asdict, field
from typing import Dict, Any, Optional, Tuple, List

_MUTAGEN_AVAILABLE = False
_TINYTAG_AVAILABLE = False

try:
    import mutagen
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

COVER_FILENAMES = {
    "cover.jpg", "cover.png", "cover.jpeg",
    "folder.jpg", "folder.png",
    "album.jpg", "album.png",
    "front.jpg", "front.png"
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
    """Encapsulates all extracted metadata for an audio track, matching Windows Details properties."""
    # Basic identification & file info
    file_path: str
    file_name: str
    file_size_bytes: int
    file_size_human: str
    extension: str
    format: str

    # Description
    title: str
    subtitle: Optional[str] = None
    rating: Optional[int] = None  # 1 to 5 stars
    comments: Optional[str] = None

    # Media
    artist: str = "Unknown Artist"  # Contributing artists
    album_artist: str = ""
    album: str = "Unknown Album"
    year: Optional[str] = None
    track_number: Optional[str] = None  # #
    disc_number: Optional[str] = None   # Part of set
    genre: str = "Unknown Genre"
    duration_seconds: float = 0.0
    duration_formatted: str = "00:00"

    # Audio technical properties
    bitrate_kbps: Optional[int] = None
    sample_rate_hz: Optional[int] = None
    channels: Optional[int] = None
    bits_per_sample: Optional[int] = None

    # Origin
    publisher: Optional[str] = None
    encoded_by: Optional[str] = None
    author_url: Optional[str] = None
    copyright: Optional[str] = None

    # Content
    composer: Optional[str] = None
    conductor: Optional[str] = None
    grouping: Optional[str] = None      # Group description
    mood: Optional[str] = None
    initial_key: Optional[str] = None
    bpm: Optional[int] = None           # Beats-per-minute
    is_compilation: bool = False        # Part of a compilation

    # File system timestamps
    last_modified: str = ""
    mtime_timestamp: float = 0.0

    # Album artwork (Local & Web URL links)
    has_album_art: bool = False
    album_art_path: Optional[str] = None
    album_art_web_url: Optional[str] = None   # Direct web link to download image from CDN
    album_art_html_link: Optional[str] = None # HTML anchor link for browsers/JSON consumers

    # Incomplete metadata tracking
    has_incomplete_metadata: bool = False
    missing_fields: List[str] = field(default_factory=list)
    vlc_fingerprinted: bool = False
    vlc_status: str = ""

    @property
    def is_missing_tags(self) -> bool:
        """True if core text tags (title, artist, album) are missing."""
        return any(m in ("title", "artist", "album") for m in self.missing_fields)

    @property
    def is_missing_art_only(self) -> bool:
        """True if core text tags are complete, but album artwork is missing."""
        return not self.is_missing_tags and ("album_art" in self.missing_fields)

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to a serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioMetadata":
        """Reconstruct AudioMetadata instance with backwards compatibility."""
        safe_data = dict(data)
        safe_data.setdefault("subtitle", None)
        safe_data.setdefault("rating", None)
        safe_data.setdefault("comments", None)
        safe_data.setdefault("disc_number", None)
        safe_data.setdefault("bits_per_sample", None)
        safe_data.setdefault("publisher", None)
        safe_data.setdefault("encoded_by", None)
        safe_data.setdefault("author_url", None)
        safe_data.setdefault("copyright", None)
        safe_data.setdefault("composer", None)
        safe_data.setdefault("conductor", None)
        safe_data.setdefault("grouping", None)
        safe_data.setdefault("mood", None)
        safe_data.setdefault("initial_key", None)
        safe_data.setdefault("bpm", None)
        safe_data.setdefault("is_compilation", False)
        safe_data.setdefault("mtime_timestamp", 0.0)
        safe_data.setdefault("has_album_art", False)
        safe_data.setdefault("album_art_path", None)
        safe_data.setdefault("album_art_web_url", None)
        safe_data.setdefault("album_art_html_link", None)
        safe_data.setdefault("has_incomplete_metadata", False)
        safe_data.setdefault("missing_fields", [])
        safe_data.setdefault("vlc_fingerprinted", False)
        safe_data.setdefault("vlc_status", "")
        return cls(**safe_data)


class MetadataExtractor:
    """Universal audio metadata extractor with zero-dependency fallback."""

    @classmethod
    def is_audio_file(cls, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        return ext in AUDIO_EXTENSIONS

    @classmethod
    def find_folder_art(cls, file_path: str) -> Optional[str]:
        """Check if folder contains common album cover images."""
        try:
            folder = os.path.dirname(os.path.abspath(file_path))
            for item in os.listdir(folder):
                if item.lower() in COVER_FILENAMES:
                    art_path = os.path.join(folder, item)
                    if os.path.isfile(art_path):
                        return art_path
        except Exception:
            pass
        return None

    @classmethod
    def evaluate_completeness(cls, meta: AudioMetadata, require_artwork: bool = True) -> None:
        """Determines if the song has missing/incomplete metadata."""
        missing = []
        stem = os.path.splitext(meta.file_name)[0]

        # Check title
        if not meta.title or meta.title.strip() == "" or meta.title.strip().lower() == stem.lower():
            missing.append("title")

        # Check artist
        if not meta.artist or meta.artist.strip() == "" or meta.artist.strip().lower() in ("unknown", "unknown artist", "various"):
            missing.append("artist")

        # Check album
        if not meta.album or meta.album.strip() == "" or meta.album.strip().lower() in ("unknown", "unknown album"):
            missing.append("album")

        # Check album artwork
        if not meta.has_album_art:
            missing.append("album_art")

        meta.missing_fields = missing
        if require_artwork:
            meta.has_incomplete_metadata = len(missing) > 0
        else:
            meta.has_incomplete_metadata = any(m in ("title", "artist", "album") for m in missing)

    @classmethod
    def extract(cls, file_path: str) -> AudioMetadata:
        """Extract metadata and extended Windows Details properties."""
        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"File not found: {abs_path}")

        file_stat = os.stat(abs_path)
        mtime = file_stat.st_mtime
        _, ext = os.path.splitext(os.path.basename(abs_path))
        ext_lower = ext.lower()

        if not cls.is_audio_file(abs_path):
            raise ValueError(f"Unsupported audio format extension: {ext_lower}")

        meta = None
        if _MUTAGEN_AVAILABLE:
            try:
                meta = cls._extract_with_mutagen(abs_path, file_stat, ext_lower)
            except Exception:
                meta = None

        if meta is None and _TINYTAG_AVAILABLE:
            try:
                meta = cls._extract_with_tinytag(abs_path, file_stat, ext_lower)
            except Exception:
                meta = None

        if meta is None:
            meta = cls._extract_pure_python(abs_path, file_stat, ext_lower)

        meta.mtime_timestamp = mtime

        # Check for album art in the directory if not embedded
        if not meta.has_album_art:
            folder_art = cls.find_folder_art(abs_path)
            if folder_art:
                meta.has_album_art = True
                meta.album_art_path = folder_art

        # If local album art exists, create direct link to the image file
        if meta.has_album_art and meta.album_art_path and os.path.isfile(meta.album_art_path):
            file_uri = f"file:///{os.path.abspath(meta.album_art_path).replace(os.sep, '/')}"
            meta.album_art_html_link = f'<a href="{file_uri}" target="_blank" download="cover.jpg">Download Album Art Image</a>'

        cls.evaluate_completeness(meta)
        return meta

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
        bits = getattr(info, "bits_per_sample", None)

        tags = getattr(audio, "tags", None) or {}

        def get_tag(keys):
            for k in keys:
                if k in tags:
                    val = tags[k]
                    if isinstance(val, list) and len(val) > 0:
                        return str(val[0]).strip()
                    elif isinstance(val, str):
                        return val.strip()
            return None

        title = get_tag(["title", "TIT2"]) or os.path.splitext(os.path.basename(path))[0]
        artist = get_tag(["artist", "TPE1"]) or "Unknown Artist"
        album = get_tag(["album", "TALB"]) or "Unknown Album"
        album_artist = get_tag(["albumartist", "TPE2"]) or artist
        genre = get_tag(["genre", "TCON"]) or "Unknown Genre"
        year = get_tag(["date", "year", "TDRC", "TYER"]) or None
        track = get_tag(["tracknumber", "TRCK"]) or None
        disc = get_tag(["discnumber", "TPOS"]) or None
        subtitle = get_tag(["subtitle", "TIT3"])
        composer = get_tag(["composer", "TCOM"])
        conductor = get_tag(["conductor", "TPE3"])
        publisher = get_tag(["publisher", "organization", "TPUB"])
        encoded_by = get_tag(["encodedby", "encoder", "TENC"])
        copyright_txt = get_tag(["copyright", "TCOP"])
        comments = get_tag(["comment", "description", "COMM"])
        grouping = get_tag(["grouping", "contentgroup", "TIT1"])
        mood = get_tag(["mood", "TMOO"])
        key = get_tag(["initialkey", "TKEY"])
        bpm_val = None
        bpm_str = get_tag(["bpm", "TBPM"])
        if bpm_str:
            try:
                bpm_val = int(float(bpm_str))
            except Exception:
                pass
        is_comp = bool(get_tag(["compilation", "TCMP"]))

        has_art = False
        if hasattr(audio, "pictures") and len(audio.pictures) > 0:
            has_art = True
        elif any(k.startswith("APIC") for k in tags.keys()):
            has_art = True

        return AudioMetadata(
            file_path=path,
            file_name=os.path.basename(path),
            file_size_bytes=stat_res.st_size,
            file_size_human=format_file_size(stat_res.st_size),
            extension=ext,
            format=ext.lstrip(".").upper(),
            title=title,
            subtitle=subtitle,
            artist=artist,
            album_artist=album_artist,
            album=album,
            year=str(year) if year else None,
            track_number=str(track) if track else None,
            disc_number=str(disc) if disc else None,
            genre=genre,
            duration_seconds=float(duration),
            duration_formatted=format_seconds(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=sample_rate,
            channels=channels,
            bits_per_sample=bits,
            publisher=publisher,
            encoded_by=encoded_by,
            copyright=copyright_txt,
            comments=comments,
            composer=composer,
            conductor=conductor,
            grouping=grouping,
            mood=mood,
            initial_key=key,
            bpm=bpm_val,
            is_compilation=is_comp,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
            mtime_timestamp=stat_res.st_mtime,
            has_album_art=has_art,
        )

    @classmethod
    def _extract_with_tinytag(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        tag = tinytag.TinyTag.get(path, image=True)
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
            disc_number=str(tag.disc) if getattr(tag, "disc", None) else None,
            composer=getattr(tag, "composer", None),
            comments=getattr(tag, "comment", None),
            duration_seconds=float(duration),
            duration_formatted=format_seconds(duration),
            bitrate_kbps=int(tag.bitrate) if tag.bitrate else None,
            sample_rate_hz=tag.samplerate,
            channels=tag.channels,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
            mtime_timestamp=stat_res.st_mtime,
            has_album_art=bool(tag.get_image()),
        )

    # ------------------------------------------------------------------
    # Built-in Pure-Python Parsers
    # ------------------------------------------------------------------
    @classmethod
    def _extract_pure_python(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
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
        bits_per_sample = None

        try:
            with wave.open(path, "rb") as wf:
                channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()
                sampwidth = wf.getsampwidth()
                bits_per_sample = sampwidth * 8
                if sample_rate > 0:
                    duration = n_frames / float(sample_rate)
                if duration > 0:
                    bitrate = int((stat_res.st_size * 8) / (duration * 1000))
        except Exception as e:
            riff_info = cls._parse_riff_info_tags(path)
            if riff_info.get("duration"):
                duration = riff_info["duration"]
                channels = riff_info.get("channels")
                sample_rate = riff_info.get("sample_rate")
                bits_per_sample = riff_info.get("bits_per_sample")
            else:
                raise ValueError(f"Corrupted or invalid WAV file: {e}")

        tags = cls._parse_riff_info_tags(path)
        title = tags.get("INAM") or title
        artist = tags.get("IART") or artist
        album = tags.get("IPRD") or album
        genre = tags.get("IGNR") or genre
        year = tags.get("ICRD") or year
        track = tags.get("ITRK") or track
        comments = tags.get("ICMT")
        copyright_txt = tags.get("ICOP")
        encoded_by = tags.get("IENG") or tags.get("ISFT")

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
            bits_per_sample=bits_per_sample,
            encoded_by=encoded_by,
            copyright=copyright_txt,
            comments=comments,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
            mtime_timestamp=stat_res.st_mtime,
        )

    @classmethod
    def _parse_riff_info_tags(cls, path: str) -> Dict[str, Any]:
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
                            _, channels, sample_rate, byte_rate, _, bits = struct.unpack("<HHIIHH", fmt_data[:16])
                            tags["channels"] = channels
                            tags["sample_rate"] = sample_rate
                            tags["bitrate"] = int((byte_rate * 8) // 1000)
                            tags["bits_per_sample"] = bits
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
        title = os.path.splitext(os.path.basename(path))[0]
        artist = "Unknown Artist"
        album = "Unknown Album"
        album_artist = ""
        genre = "Unknown Genre"
        year = None
        track = None
        disc = None
        subtitle = None
        composer = None
        conductor = None
        publisher = None
        encoded_by = None
        copyright_txt = None
        comments = None
        grouping = None
        mood = None
        key = None
        bpm_val = None
        is_comp = False
        rating = None
        author_url = None
        bitrate = None
        sample_rate = None
        channels = None
        duration = 0.0
        has_art = False

        id3v2_tags, audio_offset, has_apic = cls._parse_id3v2(path)
        has_art = has_apic

        if id3v2_tags:
            title = id3v2_tags.get("TIT2") or id3v2_tags.get("TT2") or title
            subtitle = id3v2_tags.get("TIT3") or id3v2_tags.get("TT3")
            artist = id3v2_tags.get("TPE1") or id3v2_tags.get("TP1") or artist
            album_artist = id3v2_tags.get("TPE2") or id3v2_tags.get("TP2") or ""
            conductor = id3v2_tags.get("TPE3")
            composer = id3v2_tags.get("TCOM") or id3v2_tags.get("TCM")
            album = id3v2_tags.get("TALB") or id3v2_tags.get("TAL") or album
            genre = id3v2_tags.get("TCON") or id3v2_tags.get("TCO") or genre
            year = id3v2_tags.get("TDRC") or id3v2_tags.get("TYER") or id3v2_tags.get("TYE") or None
            track = id3v2_tags.get("TRCK") or id3v2_tags.get("TRK") or None
            disc = id3v2_tags.get("TPOS") or id3v2_tags.get("TPA") or None
            publisher = id3v2_tags.get("TPUB") or id3v2_tags.get("TPB")
            encoded_by = id3v2_tags.get("TENC") or id3v2_tags.get("TEN")
            copyright_txt = id3v2_tags.get("TCOP") or id3v2_tags.get("TCR")
            comments = id3v2_tags.get("COMM") or id3v2_tags.get("COM")
            grouping = id3v2_tags.get("TIT1")
            mood = id3v2_tags.get("TMOO")
            key = id3v2_tags.get("TKEY")
            bpm_str = id3v2_tags.get("TBPM")
            if bpm_str:
                try:
                    bpm_val = int(float(bpm_str))
                except Exception:
                    pass
            is_comp = id3v2_tags.get("TCMP") == "1"
            if "RATING" in id3v2_tags:
                try:
                    rating = int(id3v2_tags["RATING"])
                except Exception:
                    pass
            author_url = id3v2_tags.get("WXXX") or id3v2_tags.get("WOAR")

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
            if not comments and id3v1_tags.get("comment"):
                comments = id3v1_tags["comment"]

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
            subtitle=subtitle,
            rating=rating,
            comments=comments,
            artist=artist,
            album_artist=album_artist or artist,
            album=album,
            year=year,
            track_number=track,
            disc_number=disc,
            genre=genre,
            duration_seconds=duration,
            duration_formatted=format_seconds(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=sample_rate,
            channels=channels,
            publisher=publisher,
            encoded_by=encoded_by,
            author_url=author_url,
            copyright=copyright_txt,
            composer=composer,
            conductor=conductor,
            grouping=grouping,
            mood=mood,
            initial_key=key,
            bpm=bpm_val,
            is_compilation=is_comp,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
            mtime_timestamp=stat_res.st_mtime,
            has_album_art=has_art,
        )

    @classmethod
    def _parse_id3v2(cls, path: str) -> Tuple[Dict[str, str], int, bool]:
        tags = {}
        audio_offset = 0
        has_apic = False
        try:
            with open(path, "rb") as f:
                header = f.read(10)
                if len(header) < 10 or header[:3] != b"ID3":
                    return tags, 0, False

                version_major = header[3]
                flags = header[5]
                tag_size = ((header[6] & 0x7F) << 21) | ((header[7] & 0x7F) << 14) | ((header[8] & 0x7F) << 7) | (header[9] & 0x7F)
                audio_offset = 10 + tag_size
                if flags & 0x10:
                    audio_offset += 10

                tag_data = f.read(tag_size)
                pos = 0

                if flags & 0x20 and len(tag_data) >= 4:
                    ext_size = struct.unpack(">I", tag_data[:4])[0]
                    pos += ext_size

                while pos < len(tag_data) - 10:
                    if tag_data[pos] == 0:
                        break

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

                    if frame_id in ("APIC", "PIC"):
                        has_apic = True

                    # Text frames (starts with T or W for URLs)
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
                            else:
                                val = data.decode("utf-8", errors="ignore")
                            tags[frame_id] = val.strip("\x00").strip()
                        except Exception:
                            pass

                    # Comments frame (COMM / COM)
                    elif frame_id in ("COMM", "COM") and len(raw_content) > 4:
                        try:
                            encoding = raw_content[0]
                            # skip 3 bytes language
                            c_body = raw_content[4:]
                            if encoding == 0:
                                parts = c_body.split(b"\x00", 1)
                                text_val = parts[1].decode("iso-8859-1", errors="ignore") if len(parts) > 1 else parts[0].decode("iso-8859-1", errors="ignore")
                            else:
                                text_val = c_body.decode("utf-16", errors="ignore")
                            tags["COMM"] = text_val.strip("\x00").strip()
                        except Exception:
                            pass

                    # Popularimeter / Rating frame (POPM)
                    elif frame_id == "POPM" and len(raw_content) > 2:
                        try:
                            # format: email null-terminated, rating (1 byte), counter
                            null_idx = raw_content.find(b"\x00")
                            if null_idx != -1 and null_idx + 1 < len(raw_content):
                                r_val = raw_content[null_idx + 1]
                                if r_val >= 255: stars = 5
                                elif r_val >= 196: stars = 4
                                elif r_val >= 128: stars = 3
                                elif r_val >= 64: stars = 2
                                elif r_val >= 1: stars = 1
                                else: stars = 0
                                tags["RATING"] = str(stars)
                        except Exception:
                            pass
        except Exception:
            pass

        return tags, audio_offset, has_apic

    @classmethod
    def _parse_id3v1(cls, path: str) -> Dict[str, str]:
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
                    tags["comment"] = buf[97:125].decode("iso-8859-1", errors="ignore").strip("\x00").strip()
                    if buf[125] == 0:
                        tags["track"] = str(buf[126])
        except Exception:
            pass
        return tags

    @classmethod
    def _parse_mpeg_frame_headers(cls, path: str, start_offset: int, file_size: int) -> Optional[Dict[str, Any]]:
        bitrate_map_v1_l3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
        samplerate_map_v1 = [44100, 48000, 32000, 0]

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
                        version_id = (header[1] >> 3) & 0x03
                        layer_id = (header[1] >> 1) & 0x03
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
        title = os.path.splitext(os.path.basename(path))[0]
        artist = "Unknown Artist"
        album = "Unknown Album"
        album_artist = ""
        genre = "Unknown Genre"
        year = None
        track = None
        disc = None
        subtitle = None
        composer = None
        conductor = None
        publisher = None
        encoded_by = None
        copyright_txt = None
        comments = None
        bpm_val = None
        key = None
        mood = None
        is_comp = False
        duration = 0.0
        sample_rate = 44100
        channels = 2
        bits_per_sample = 16
        bitrate = None
        has_art = False

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
                        bits_per_sample = ((block_data[12] & 0x01) << 4) | (block_data[13] >> 4) + 1
                        total_samples = ((block_data[13] & 0x0F) << 32) | struct.unpack(">I", block_data[14:18])[0]
                        if sample_rate > 0:
                            duration = total_samples / float(sample_rate)
                            if duration > 0:
                                bitrate = int((stat_res.st_size * 8) / (duration * 1000))
                elif block_type == 4:  # VORBIS_COMMENT
                    c = cls._parse_vorbis_comment_block(block_data)
                    title = c.get("TITLE") or title
                    subtitle = c.get("SUBTITLE")
                    artist = c.get("ARTIST") or artist
                    album = c.get("ALBUM") or album
                    album_artist = c.get("ALBUMARTIST") or ""
                    genre = c.get("GENRE") or genre
                    year = c.get("DATE") or c.get("YEAR") or None
                    track = c.get("TRACKNUMBER") or None
                    disc = c.get("DISCNUMBER") or None
                    composer = c.get("COMPOSER")
                    conductor = c.get("CONDUCTOR")
                    publisher = c.get("PUBLISHER") or c.get("ORGANIZATION")
                    encoded_by = c.get("ENCODER") or c.get("ENCODEDBY")
                    copyright_txt = c.get("COPYRIGHT")
                    comments = c.get("COMMENT") or c.get("DESCRIPTION")
                    key = c.get("KEY")
                    mood = c.get("MOOD")
                    is_comp = c.get("COMPILATION") == "1"
                    if c.get("BPM"):
                        try: bpm_val = int(float(c["BPM"]))
                        except Exception: pass
                elif block_type == 6:  # PICTURE
                    has_art = True

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
            subtitle=subtitle,
            artist=artist,
            album=album,
            album_artist=album_artist or artist,
            genre=genre,
            year=year,
            track_number=track,
            disc_number=disc,
            composer=composer,
            conductor=conductor,
            publisher=publisher,
            encoded_by=encoded_by,
            copyright=copyright_txt,
            comments=comments,
            initial_key=key,
            mood=mood,
            bpm=bpm_val,
            is_compilation=is_comp,
            duration_seconds=duration,
            duration_formatted=format_seconds(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=sample_rate,
            channels=channels,
            bits_per_sample=bits_per_sample,
            last_modified=datetime.datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
            mtime_timestamp=stat_res.st_mtime,
            has_album_art=has_art,
        )

    @classmethod
    def _parse_vorbis_comment_block(cls, data: bytes) -> Dict[str, str]:
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
            mtime_timestamp=stat_res.st_mtime,
        )

    @classmethod
    def _parse_m4a(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
        title = os.path.splitext(os.path.basename(path))[0]
        artist = "Unknown Artist"
        album = "Unknown Album"
        album_artist = ""
        genre = "Unknown Genre"
        year = None
        track = None
        duration = 0.0
        has_art = False

        with open(path, "rb") as f:
            data = f.read(min(stat_res.st_size, 262144))
            if b"ftyp" not in data[:32]:
                raise ValueError("Not a valid MP4/M4A file (missing ftyp atom)")

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
            if b"covr" in data:
                has_art = True

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
            mtime_timestamp=stat_res.st_mtime,
            has_album_art=has_art,
        )

    @classmethod
    def _parse_generic_audio(cls, path: str, stat_res: os.stat_result, ext: str) -> AudioMetadata:
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
            mtime_timestamp=stat_res.st_mtime,
        )


class VLCMetadataEnricher:
    """
    Leverages LibVLC's deep media parsing, fingerprinting, and artwork cache
    to identify missing metadata and retrieve cover artwork.
    """

    _instance = None
    _vlc_dll = None

    @classmethod
    def get_vlc_instance(cls):
        if cls._instance is not None:
            return cls._vlc_dll, cls._instance

        search_dirs = [
            r"C:\Program Files\VideoLAN\VLC",
            r"C:\Program Files (x86)\VideoLAN\VLC",
        ]
        dll_path = None
        for d in search_dirs:
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
            return None, None

        try:
            dll = ctypes.CDLL(dll_path)
            dll.libvlc_new.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
            dll.libvlc_new.restype = ctypes.c_void_p

            dll.libvlc_media_new_path.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            dll.libvlc_media_new_path.restype = ctypes.c_void_p

            dll.libvlc_media_parse.argtypes = [ctypes.c_void_p]
            dll.libvlc_media_parse.restype = None

            dll.libvlc_media_get_meta.argtypes = [ctypes.c_void_p, ctypes.c_int]
            dll.libvlc_media_get_meta.restype = ctypes.c_char_p

            dll.libvlc_media_release.argtypes = [ctypes.c_void_p]
            dll.libvlc_media_release.restype = None

            inst = dll.libvlc_new(0, None)
            cls._vlc_dll = dll
            cls._instance = inst
            return dll, inst
        except Exception:
            return None, None

    @classmethod
    def enrich(cls, meta: AudioMetadata) -> bool:
        dll, inst = cls.get_vlc_instance()
        if not dll or not inst:
            meta.vlc_fingerprinted = False
            meta.vlc_status = "LibVLC unavailable"
            return False

        enriched = False
        try:
            path_bytes = os.path.abspath(meta.file_path).encode(sys.getfilesystemencoding())
            media = dll.libvlc_media_new_path(inst, path_bytes)
            if not media:
                return False

            dll.libvlc_media_parse(media)

            def get_vlc_meta(meta_id: int) -> Optional[str]:
                raw = dll.libvlc_media_get_meta(media, meta_id)
                if raw:
                    text = raw.decode("utf-8", errors="ignore").strip()
                    return text if text else None
                return None

            vlc_title = get_vlc_meta(0)
            vlc_artist = get_vlc_meta(1)
            vlc_genre = get_vlc_meta(2)
            vlc_copyright = get_vlc_meta(3)
            vlc_album = get_vlc_meta(4)
            vlc_track = get_vlc_meta(5)
            vlc_description = get_vlc_meta(6)
            vlc_date = get_vlc_meta(8)
            vlc_art = get_vlc_meta(15)  # ArtworkURL
            vlc_publisher = get_vlc_meta(13)
            vlc_encoded = get_vlc_meta(14)
            vlc_album_artist = get_vlc_meta(23)
            vlc_disc = get_vlc_meta(24)

            stem = os.path.splitext(meta.file_name)[0]

            # Enrich Title
            if ("title" in meta.missing_fields or meta.title == stem) and vlc_title and vlc_title != stem:
                meta.title = vlc_title
                enriched = True

            # Enrich Artist
            if ("artist" in meta.missing_fields or meta.artist.lower().startswith("unknown")) and vlc_artist:
                meta.artist = vlc_artist
                enriched = True

            # Enrich Album
            if ("album" in meta.missing_fields or meta.album.lower().startswith("unknown")) and vlc_album:
                meta.album = vlc_album
                enriched = True

            # Enrich Genre
            if (not meta.genre or meta.genre.lower().startswith("unknown")) and vlc_genre:
                meta.genre = vlc_genre
                enriched = True

            # Enrich Year
            if not meta.year and vlc_date:
                meta.year = vlc_date[:4]
                enriched = True

            # Enrich Track #
            if not meta.track_number and vlc_track:
                meta.track_number = vlc_track
                enriched = True

            # Enrich Disc #
            if not meta.disc_number and vlc_disc:
                meta.disc_number = vlc_disc
                enriched = True

            # Enrich Album Artist
            if not meta.album_artist and vlc_album_artist:
                meta.album_artist = vlc_album_artist
                enriched = True

            # Enrich Publisher, Copyright, EncodedBy
            if not meta.publisher and vlc_publisher: meta.publisher = vlc_publisher; enriched = True
            if not meta.copyright and vlc_copyright: meta.copyright = vlc_copyright; enriched = True
            if not meta.encoded_by and vlc_encoded: meta.encoded_by = vlc_encoded; enriched = True
            if not meta.comments and vlc_description: meta.comments = vlc_description; enriched = True

            # Enrich Artwork via VLC ArtworkURL
            if not meta.has_album_art and vlc_art:
                meta.has_album_art = True
                meta.album_art_path = vlc_art
                enriched = True

            dll.libvlc_media_release(media)

            # Resolve album artwork & web URL link
            try:
                from .artwork import AlbumArtManager
                art_resolved = AlbumArtManager.resolve_artwork(meta, enable_online_download=True)
                if art_resolved:
                    enriched = True
            except Exception:
                pass

            meta.vlc_fingerprinted = True
            meta.vlc_status = "VLC Enriched" if enriched else "VLC Parsed (No new tags)"
            MetadataExtractor.evaluate_completeness(meta)
        except Exception as e:
            meta.vlc_fingerprinted = False
            meta.vlc_status = f"VLC Error: {e}"

        return enriched
