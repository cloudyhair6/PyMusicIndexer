"""
Audio Metadata Writer Module
============================
Writes updated audio tags (Title, Artist, Album, Genre, Year, Track)
AND embeds album cover artwork directly into physical audio files on disk (MP3, WAV, FLAC).
Pure-Python implementations with optional mutagen integration.
"""

from __future__ import annotations

import os
import sys
import shutil
import struct
import datetime
from typing import Optional, List, Dict, Any, Tuple

from .metadata import AudioMetadata

_MUTAGEN_AVAILABLE = False
try:
    import mutagen
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TDRC, TRCK, APIC
    _MUTAGEN_AVAILABLE = True
except ImportError:
    pass


class AudioMetadataWriter:
    """Writes metadata tags and embeds album artwork directly into audio files."""

    @classmethod
    def write_metadata(cls, meta: AudioMetadata) -> Tuple[bool, Optional[str]]:
        """
        Writes the current metadata and album artwork in `meta` directly into the physical audio file on disk.
        Returns (success: bool, error_message: Optional[str]).
        """
        file_path = os.path.abspath(meta.file_path)
        if not os.path.isfile(file_path):
            return False, f"File not found: {file_path}"

        ext = meta.extension.lower()

        # If mutagen is available, attempt to use it
        if _MUTAGEN_AVAILABLE:
            try:
                cls._write_with_mutagen(file_path, meta)
                cls._refresh_meta_stat(meta)
                return True, None
            except Exception:
                pass

        try:
            if ext == ".mp3":
                cls._write_mp3_pure_python(file_path, meta)
            elif ext == ".wav":
                cls._write_wav_pure_python(file_path, meta)
            elif ext == ".flac":
                cls._write_flac_pure_python(file_path, meta)
            else:
                return False, f"Format {ext.upper()} does not support pure-Python tag writing without mutagen."

            cls._refresh_meta_stat(meta)
            return True, None
        except Exception as err:
            return False, str(err)

    @classmethod
    def _refresh_meta_stat(cls, meta: AudioMetadata) -> None:
        """Update stat size and mtime on the AudioMetadata object after file write."""
        try:
            st = os.stat(meta.file_path)
            meta.file_size_bytes = st.st_size
            meta.mtime_timestamp = st.st_mtime
            meta.last_modified = datetime.datetime.fromtimestamp(st.st_mtime).isoformat()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Mutagen Writer
    # ------------------------------------------------------------------
    @classmethod
    def _write_with_mutagen(cls, file_path: str, meta: AudioMetadata) -> None:
        audio = mutagen.File(file_path)
        if audio is None:
            raise ValueError("Mutagen could not open audio stream for writing")

        # Handle ID3 tags (MP3 / AIFF)
        if hasattr(audio, "tags") and hasattr(audio.tags, "add"):
            if meta.title: audio.tags.add(TIT2(encoding=3, text=meta.title))
            if meta.artist: audio.tags.add(TPE1(encoding=3, text=meta.artist))
            if meta.album: audio.tags.add(TALB(encoding=3, text=meta.album))
            if meta.genre: audio.tags.add(TCON(encoding=3, text=meta.genre))
            if meta.year: audio.tags.add(TDRC(encoding=3, text=str(meta.year)))
            if meta.track_number: audio.tags.add(TRCK(encoding=3, text=str(meta.track_number)))

            # Embed cover art if available
            if meta.album_art_path and os.path.isfile(meta.album_art_path):
                try:
                    with open(meta.album_art_path, "rb") as img_f:
                        img_data = img_f.read()
                    mime = "image/png" if meta.album_art_path.lower().endswith(".png") else "image/jpeg"
                    audio.tags.add(APIC(
                        encoding=3,
                        mime=mime,
                        type=3,  # Cover (front)
                        desc="Cover",
                        data=img_data
                    ))
                except Exception:
                    pass

        audio.save()

    # ------------------------------------------------------------------
    # Pure-Python MP3 ID3v2.3 Writer with APIC Cover Art Embedding
    # ------------------------------------------------------------------
    @classmethod
    def _write_mp3_pure_python(cls, file_path: str, meta: AudioMetadata) -> None:
        """Writes ID3v2.3 frames and embeds APIC album artwork to an MP3 file."""
        def make_frame(frame_id: bytes, text: Optional[str]) -> bytes:
            if not text:
                return b""
            encoded = b"\x03" + str(text).encode("utf-8")
            size = len(encoded)
            return frame_id + struct.pack(">I", size) + b"\x00\x00" + encoded

        frames = bytearray()
        if meta.title: frames.extend(make_frame(b"TIT2", meta.title))
        if meta.subtitle: frames.extend(make_frame(b"TIT3", meta.subtitle))
        if meta.artist: frames.extend(make_frame(b"TPE1", meta.artist))
        if meta.album_artist: frames.extend(make_frame(b"TPE2", meta.album_artist))
        if meta.album: frames.extend(make_frame(b"TALB", meta.album))
        if meta.genre: frames.extend(make_frame(b"TCON", meta.genre))
        if meta.year: frames.extend(make_frame(b"TYER", meta.year))
        if meta.track_number: frames.extend(make_frame(b"TRCK", str(meta.track_number)))
        if meta.disc_number: frames.extend(make_frame(b"TPOS", str(meta.disc_number)))
        if meta.composer: frames.extend(make_frame(b"TCOM", meta.composer))
        if meta.conductor: frames.extend(make_frame(b"TPE3", meta.conductor))
        if meta.publisher: frames.extend(make_frame(b"TPUB", meta.publisher))
        if meta.encoded_by: frames.extend(make_frame(b"TENC", meta.encoded_by))
        if meta.copyright: frames.extend(make_frame(b"TCOP", meta.copyright))
        if meta.grouping: frames.extend(make_frame(b"TIT1", meta.grouping))
        if meta.mood: frames.extend(make_frame(b"TMOO", meta.mood))
        if meta.initial_key: frames.extend(make_frame(b"TKEY", meta.initial_key))
        if meta.bpm: frames.extend(make_frame(b"TBPM", str(meta.bpm)))
        if meta.is_compilation: frames.extend(make_frame(b"TCMP", "1"))

        # Comments (COMM frame)
        if meta.comments:
            comm_payload = b"\x03eng\x00" + meta.comments.encode("utf-8")
            comm_frame = b"COMM" + struct.pack(">I", len(comm_payload)) + b"\x00\x00" + comm_payload
            frames.extend(comm_frame)

        # Rating (POPM frame)
        if meta.rating and 1 <= meta.rating <= 5:
            popm_map = {1: 1, 2: 64, 3: 128, 4: 196, 5: 255}
            popm_val = popm_map.get(meta.rating, 128)
            popm_payload = b"Windows Media Player\x00" + bytes([popm_val]) + b"\x00\x00\x00\x00"
            popm_frame = b"POPM" + struct.pack(">I", len(popm_payload)) + b"\x00\x00" + popm_payload
            frames.extend(popm_frame)

        # Embed APIC Cover Art frame if available
        if meta.album_art_path and os.path.isfile(meta.album_art_path):
            try:
                with open(meta.album_art_path, "rb") as img_f:
                    img_bytes = img_f.read()
                if len(img_bytes) > 100:
                    mime = b"image/png" if meta.album_art_path.lower().endswith(".png") else b"image/jpeg"
                    # APIC format: encoding (0x00) + mime + 0x00 + type (0x03) + desc (0x00) + bytes
                    apic_payload = b"\x00" + mime + b"\x00\x03\x00" + img_bytes
                    apic_frame = b"APIC" + struct.pack(">I", len(apic_payload)) + b"\x00\x00" + apic_payload
                    frames.extend(apic_frame)
            except Exception:
                pass

        tag_len = len(frames)
        b0 = (tag_len >> 21) & 0x7F
        b1 = (tag_len >> 14) & 0x7F
        b2 = (tag_len >> 7) & 0x7F
        b3 = tag_len & 0x7F

        id3_header = b"ID3\x03\x00\x00" + bytes([b0, b1, b2, b3])
        full_tag = id3_header + frames

        # Read existing MP3 data and locate start of audio frames
        with open(file_path, "rb") as f:
            header = f.read(10)
            if len(header) >= 10 and header[:3] == b"ID3":
                flags = header[5]
                existing_size = ((header[6] & 0x7F) << 21) | ((header[7] & 0x7F) << 14) | ((header[8] & 0x7F) << 7) | (header[9] & 0x7F)
                audio_start = 10 + existing_size
                if flags & 0x10:
                    audio_start += 10
                f.seek(audio_start)
            else:
                f.seek(0)

            audio_data = f.read()

        tmp_file = file_path + ".tmp_tag"
        with open(tmp_file, "wb") as f:
            f.write(full_tag)
            f.write(audio_data)

        os.replace(tmp_file, file_path)

    # ------------------------------------------------------------------
    # Pure-Python WAV RIFF INFO Chunk Writer
    # ------------------------------------------------------------------
    @classmethod
    def _write_wav_pure_python(cls, file_path: str, meta: AudioMetadata) -> None:
        def make_subchunk(fourcc: bytes, text: Optional[str]) -> bytes:
            if not text:
                return b""
            data = text.encode("utf-8") + b"\x00"
            if len(data) % 2 == 1:
                data += b"\x00"
            return fourcc + struct.pack("<I", len(data)) + data

        info_subchunks = bytearray()
        if meta.title: info_subchunks.extend(make_subchunk(b"INAM", meta.title))
        if meta.artist: info_subchunks.extend(make_subchunk(b"IART", meta.artist))
        if meta.album: info_subchunks.extend(make_subchunk(b"IPRD", meta.album))
        if meta.genre: info_subchunks.extend(make_subchunk(b"IGNR", meta.genre))
        if meta.year: info_subchunks.extend(make_subchunk(b"ICRD", str(meta.year)))
        if meta.track_number: info_subchunks.extend(make_subchunk(b"ITRK", str(meta.track_number)))

        # Also copy cover.jpg to directory if available
        if meta.album_art_path and os.path.isfile(meta.album_art_path):
            try:
                parent_dir = os.path.dirname(file_path)
                folder_cover = os.path.join(parent_dir, "cover.jpg")
                if not os.path.isfile(folder_cover):
                    shutil.copyfile(meta.album_art_path, folder_cover)
            except Exception:
                pass

        if not info_subchunks:
            return

        list_payload = b"INFO" + info_subchunks
        list_chunk = b"LIST" + struct.pack("<I", len(list_payload)) + list_payload

        with open(file_path, "rb") as f:
            riff_hdr = f.read(12)
            if len(riff_hdr) < 12 or riff_hdr[:4] != b"RIFF" or riff_hdr[8:12] != b"WAVE":
                raise ValueError("Not a valid RIFF WAVE file")

            clean_chunks = bytearray()
            while True:
                ch_hdr = f.read(8)
                if len(ch_hdr) < 8:
                    break
                cid, csize = struct.unpack("<4sI", ch_hdr)
                pad = 1 if (csize % 2 == 1) else 0

                if cid == b"LIST":
                    list_type = f.read(4)
                    if list_type == b"INFO":
                        f.seek(csize - 4 + pad, 1)
                        continue
                    else:
                        f.seek(-4, 1)

                cdata = f.read(csize + pad)
                clean_chunks.extend(ch_hdr + cdata)

        new_total_size = 4 + len(clean_chunks) + len(list_chunk)
        new_header = b"RIFF" + struct.pack("<I", new_total_size) + b"WAVE"

        tmp_file = file_path + ".tmp_tag"
        with open(tmp_file, "wb") as f:
            f.write(new_header)
            f.write(clean_chunks)
            f.write(list_chunk)

        os.replace(tmp_file, file_path)

    # ------------------------------------------------------------------
    # Pure-Python FLAC Writer with Embedded Picture Block
    # ------------------------------------------------------------------
    @classmethod
    def _write_flac_pure_python(cls, file_path: str, meta: AudioMetadata) -> None:
        comments = []
        if meta.title: comments.append(f"TITLE={meta.title}")
        if meta.subtitle: comments.append(f"SUBTITLE={meta.subtitle}")
        if meta.artist: comments.append(f"ARTIST={meta.artist}")
        if meta.album_artist: comments.append(f"ALBUMARTIST={meta.album_artist}")
        if meta.album: comments.append(f"ALBUM={meta.album}")
        if meta.genre: comments.append(f"GENRE={meta.genre}")
        if meta.year: comments.append(f"DATE={meta.year}")
        if meta.track_number: comments.append(f"TRACKNUMBER={meta.track_number}")
        if meta.disc_number: comments.append(f"DISCNUMBER={meta.disc_number}")
        if meta.composer: comments.append(f"COMPOSER={meta.composer}")
        if meta.conductor: comments.append(f"CONDUCTOR={meta.conductor}")
        if meta.publisher: comments.append(f"ORGANIZATION={meta.publisher}")
        if meta.encoded_by: comments.append(f"ENCODER={meta.encoded_by}")
        if meta.copyright: comments.append(f"COPYRIGHT={meta.copyright}")
        if meta.grouping: comments.append(f"GROUPING={meta.grouping}")
        if meta.mood: comments.append(f"MOOD={meta.mood}")
        if meta.initial_key: comments.append(f"KEY={meta.initial_key}")
        if meta.bpm: comments.append(f"BPM={meta.bpm}")
        if meta.is_compilation: comments.append("COMPILATION=1")
        if meta.comments: comments.append(f"COMMENT={meta.comments}")
        if meta.rating: comments.append(f"RATING={meta.rating}")

        vendor = b"Antigravity Music Engine"
        vorbis_block = bytearray()
        vorbis_block.extend(struct.pack("<I", len(vendor)))
        vorbis_block.extend(vendor)
        vorbis_block.extend(struct.pack("<I", len(comments)))

        for c in comments:
            c_bytes = c.encode("utf-8")
            vorbis_block.extend(struct.pack("<I", len(c_bytes)))
            vorbis_block.extend(c_bytes)

        # Picture Block (Type 6)
        picture_block = None
        if meta.album_art_path and os.path.isfile(meta.album_art_path):
            try:
                with open(meta.album_art_path, "rb") as img_f:
                    img_data = img_f.read()
                if len(img_data) > 100:
                    mime = b"image/png" if meta.album_art_path.lower().endswith(".png") else b"image/jpeg"
                    desc = b"Front Cover"
                    pic_b = bytearray()
                    pic_b.extend(struct.pack(">I", 3))  # 3 = Front Cover
                    pic_b.extend(struct.pack(">I", len(mime)))
                    pic_b.extend(mime)
                    pic_b.extend(struct.pack(">I", len(desc)))
                    pic_b.extend(desc)
                    pic_b.extend(struct.pack(">IIII", 600, 600, 24, 0))
                    pic_b.extend(struct.pack(">I", len(img_data)))
                    pic_b.extend(img_data)
                    picture_block = bytes(pic_b)
            except Exception:
                pass

        with open(file_path, "rb") as f:
            magic = f.read(4)
            if magic != b"fLaC":
                raise ValueError("Not a valid FLAC file")

            blocks = []
            has_vorbis = False
            has_pic = False
            while True:
                hdr = f.read(4)
                if len(hdr) < 4:
                    break
                is_last = (hdr[0] & 0x80) != 0
                btype = hdr[0] & 0x7F
                blen = (hdr[1] << 16) | (hdr[2] << 8) | hdr[3]
                bdata = f.read(blen)

                if btype == 4:
                    has_vorbis = True
                    blocks.append((4, bytes(vorbis_block)))
                elif btype == 6 and picture_block:
                    has_pic = True
                    blocks.append((6, picture_block))
                else:
                    blocks.append((btype, bdata))

                if is_last:
                    break

            if not has_vorbis:
                blocks.append((4, bytes(vorbis_block)))
            if picture_block and not has_pic:
                blocks.append((6, picture_block))

            audio_frames = f.read()

        tmp_file = file_path + ".tmp_tag"
        with open(tmp_file, "wb") as f:
            f.write(b"fLaC")
            for i, (btype, bdata) in enumerate(blocks):
                is_last_block = 0x80 if (i == len(blocks) - 1) else 0x00
                hdr0 = is_last_block | (btype & 0x7F)
                blen = len(bdata)
                f.write(bytes([hdr0, (blen >> 16) & 0xFF, (blen >> 8) & 0xFF, blen & 0xFF]))
                f.write(bdata)
            f.write(audio_frames)

        os.replace(tmp_file, file_path)
