"""
Sample Data Generator
=====================
Creates a mock audio library containing valid songs (WAV, MP3 tags),
corrupted audio files, and non-audio files (txt, images) to test
the media scanner and verify all requirements.
"""

import os
import math
import wave
import struct


def create_sine_wave(filepath: str, duration_sec: float = 2.0, freq: float = 440.0, sample_rate: int = 44100):
    """Generate a clean PCM WAV audio file with a sine tone."""
    n_samples = int(sample_rate * duration_sec)
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

    with wave.open(filepath, "w") as wf:
        wf.setnchannels(2)  # Stereo
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)

        frames = bytearray()
        for i in range(n_samples):
            val = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * freq * (i / sample_rate)))
            packed = struct.pack("<hh", val, val)
            frames.extend(packed)

        wf.writeframes(frames)


def append_riff_info_chunk(filepath: str, title: str, artist: str, album: str, genre: str, year: str):
    """Appends a RIFF INFO list chunk to a WAV file."""
    def make_subchunk(fourcc: bytes, text: str) -> bytes:
        data = text.encode("utf-8") + b"\x00"
        if len(data) % 2 == 1:
            data += b"\x00"
        return fourcc + struct.pack("<I", len(data)) + data

    info_data = (
        make_subchunk(b"INAM", title) +
        make_subchunk(b"IART", artist) +
        make_subchunk(b"IPRD", album) +
        make_subchunk(b"IGNR", genre) +
        make_subchunk(b"ICRD", year)
    )

    list_chunk = b"LIST" + struct.pack("<I", len(info_data) + 4) + b"INFO" + info_data

    with open(filepath, "r+b") as f:
        # Read current RIFF size
        f.seek(4)
        old_riff_size = struct.unpack("<I", f.read(4))[0]
        # Append LIST chunk at the end
        f.seek(0, 2)
        f.write(list_chunk)
        # Update RIFF size
        new_riff_size = old_riff_size + len(list_chunk)
        f.seek(4)
        f.write(struct.pack("<I", new_riff_size))


def create_mock_mp3_with_id3v2(filepath: str, title: str, artist: str, album: str, genre: str, year: str):
    """Creates a mock MP3 file with valid ID3v2.3 tags and a minimal MPEG audio frame."""
    def make_id3_frame(frame_id: bytes, text: str) -> bytes:
        encoded = b"\x03" + text.encode("utf-8")  # UTF-8 encoding descriptor
        size = len(encoded)
        return frame_id + struct.pack(">I", size) + b"\x00\x00" + encoded

    frames = (
        make_id3_frame(b"TIT2", title) +
        make_id3_frame(b"TPE1", artist) +
        make_id3_frame(b"TALB", album) +
        make_id3_frame(b"TCON", genre) +
        make_id3_frame(b"TYER", year)
    )

    # Encode syncsafe integer for tag length
    tag_len = len(frames)
    b0 = (tag_len >> 21) & 0x7F
    b1 = (tag_len >> 14) & 0x7F
    b2 = (tag_len >> 7) & 0x7F
    b3 = tag_len & 0x7F

    header = b"ID3\x03\x00\x00" + bytes([b0, b1, b2, b3])
    
    # 4-byte MPEG 1 Layer 3 audio header: 128 kbps, 44100 Hz, Stereo
    # 0xFF 0xFB (sync 11 bits + MPEG1 + Layer3 + no protection)
    # 0x90 (128 kbps + 44100 Hz + no padding + private)
    # 0x64 (Stereo)
    mpeg_frame = b"\xFF\xFB\x90\x64" + (b"\x55" * 413)

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(header + frames + (mpeg_frame * 50))  # ~20KB audio


def generate_sample_library(base_dir: str = "sample_music_library"):
    """Populate sample directory with audio tracks, corrupted tracks, and non-audio files."""
    os.makedirs(base_dir, exist_ok=True)
    pop_dir = os.path.join(base_dir, "Pop")
    rock_dir = os.path.join(base_dir, "Rock")
    docs_dir = os.path.join(base_dir, "Documents")

    os.makedirs(pop_dir, exist_ok=True)
    os.makedirs(rock_dir, exist_ok=True)
    os.makedirs(docs_dir, exist_ok=True)

    # 1. Valid WAV tracks
    track1 = os.path.join(pop_dir, "summer_vibes.wav")
    create_sine_wave(track1, duration_sec=3.0, freq=523.25)
    append_riff_info_chunk(track1, title="Summer Vibes", artist="Solar Beats", album="Sunny Days", genre="Pop", year="2025")

    track2 = os.path.join(rock_dir, "midnight_guitar.wav")
    create_sine_wave(track2, duration_sec=2.5, freq=329.63)
    append_riff_info_chunk(track2, title="Midnight Guitar", artist="Neon Shadows", album="Echoes", genre="Rock", year="2024")

    # 2. Valid MP3 tracks
    track3 = os.path.join(rock_dir, "electric_pulse.mp3")
    create_mock_mp3_with_id3v2(track3, title="Electric Pulse", artist="Volt Riders", album="High Voltage", genre="Electronic Rock", year="2026")

    track4 = os.path.join(pop_dir, "dreamland.mp3")
    create_mock_mp3_with_id3v2(track4, title="Dreamland Melody", artist="Luna Sky", album="Cloud Walker", genre="Synthpop", year="2025")

    # 3. Corrupted audio file
    corrupt_file = os.path.join(rock_dir, "broken_recording.mp3")
    with open(corrupt_file, "wb") as f:
        f.write(b"NOT_A_VALID_MP3_STREAM_CORRUPT_BYTES_XYZ_1234567890")

    # 4. Non-audio files
    with open(os.path.join(docs_dir, "tracklist.txt"), "w") as f:
        f.write("1. Summer Vibes\n2. Midnight Guitar\n3. Electric Pulse\n")

    with open(os.path.join(base_dir, "album_cover.jpg"), "wb") as f:
        f.write(b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00\x60\x00\x60\x00\x00\xFF\xDB")

    with open(os.path.join(pop_dir, "lyrics.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 Mock lyrics document")

    return base_dir


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out_dir = generate_sample_library()
    print(f"[+] Sample library generated at: {os.path.abspath(out_dir)}")
