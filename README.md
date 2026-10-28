# Audio Media Scanner & Player

A fast, modular Python application that indexes music collections from the command line, extracts rich audio metadata, exports detailed JSON catalogs, and launches a modern PyQt6 GUI music player powered by LibVLC or QtMultimedia.

---

## Features

- **Interactive CMD Workflow**: Runs directly in the command prompt with no initial GUI. Prompts you to enter one or multiple folders with real-time directory validation.
- **Folder Review**: Formats and displays the chosen target folders before indexing begins.
- **Dynamic Terminal Progress Bar**: Pre-discovers file counts and displays an in-place progress bar showing percentage, file counts, and the current file being scanned without wrapping lines.
- **Dual JSON Output**:
  - `indexed_songs.json`: Stores complete metadata for all valid songs (Title, Artist, Album, Genre, Year, Track, Duration, Bitrate, Sample Rate, Channels, File Size, Path, Format).
  - `unindexed_files.json`: Records all non-song files (txt, jpg, pdf, etc.) and failed/corrupted audio files with detailed explanations of why they were skipped.
- **Console Failure Reporting**: Automatically prints a clear terminal breakdown of any files that could not be indexed.
- **GUI Music Browser & Player**: Once cmd indexing finishes, automatically launches a dark-themed PyQt6 GUI featuring:
  - Real-time search across Title, Artist, Album, Genre, and Path.
  - Sortable track table with metadata columns.
  - Audio playback with Play, Pause, Stop, Previous, Next, Seek slider, and Volume controls.
  - **VLC Playback Engine**: Automatically loads and controls system VLC (`libvlc.dll`) with seamless fallback to QtMultimedia.
- **Extensible & Modular**: Designed from the ground up as a standalone package (`media_scanner`) ready to be imported into larger projects, web backends, or desktop applications.

---

## Project Structure

```
python media scanning/
│
├── media_scanner/
│   ├── __init__.py           # Package exports and public API
│   ├── metadata.py           # Pure Python & Mutagen audio metadata extractors
│   ├── scanner.py            # Recursive directory crawler & batch indexer
│   ├── storage.py            # Dual JSON persistence manager
│   ├── player.py             # LibVLC and QtAudioPlayer abstraction layers
│   ├── gui.py                # Modern PyQt6 GUI player and search table
│   └── cli.py                # Command-line interface and progress bar
│
├── main.py                   # Main CLI entrypoint
├── sample_data_gen.py        # Mock audio library generator for testing
├── requirements.txt          # Package requirements
├── tests/
│   └── test_scanner.py       # Unit & integration test suite
└── README.md                 # Documentation
```

---

## Quick Start

### 1. Interactive Command-Line Mode
Run the script in `cmd` or PowerShell:
```bash
python main.py
```
You will be prompted to enter folder paths:
```
=================================================================
           AUDIO DIRECTORY SELECTION (CMD INTERFACE)           
=================================================================
Enter the full path to each folder you want to index.
Tips:
  - You can enter multiple directories one by one.
  - Press [Enter] on an empty line when you have finished adding folders.
-----------------------------------------------------------------
Enter folder #1: C:\Users\Will\Music
  [+] Added: C:\Users\Will\Music
Enter folder #2: 
```

### 2. Pass Folders via CLI Arguments
You can specify one or more target folders directly:
```bash
python main.py --folders "C:\Music" "D:\Soundtracks"
```

### 3. Headless / CLI-Only Mode (No GUI)
To run automated indexing without opening the GUI player window:
```bash
python main.py -f "C:\Music" --no-gui
```

### 4. Custom JSON Output Paths
```bash
python main.py -f "C:\Music" --songs-out "my_library.json" --unindexed-out "skipped.json"
```

---

## Integrating Into Bigger Projects

The application is structured as an independent, decoupled library (`media_scanner`). You can import any component directly into your own projects:

### 1. Headless Indexing Backend
```python
from media_scanner import AudioIndexer, StorageManager

# 1. Initialize indexer
indexer = AudioIndexer()

# 2. Define an optional progress hook
def progress_listener(current: int, total: int, filename: str):
    print(f"Indexing [{current}/{total}]: {filename}")

# 3. Scan directories
result = indexer.scan_folders(
    folder_paths=["C:/Music", "D:/Albums"],
    recursive=True,
    progress_callback=progress_listener,
)

print(f"Indexed {result.song_count} songs ({result.unindexed_count} skipped).")

# 4. Save to JSON or database
StorageManager.save_scan_result(result, "songs.json", "other.json")

# Or iterate songs directly
for song in result.songs:
    print(f"{song.title} by {song.artist} ({song.duration_formatted})")
```

### 2. Extracting Metadata from Single Files
```python
from media_scanner import MetadataExtractor

meta = MetadataExtractor.extract("C:/Music/song.mp3")
print("Title:", meta.title)
print("Artist:", meta.artist)
print("Album:", meta.album)
print("Duration:", meta.duration_formatted)
print("Bitrate:", meta.bitrate_kbps, "kbps")
```

### 3. Audio Playback Engine (VLC / Qt)
```python
from media_scanner import get_best_player

# Instantiates VLCPlayer if libvlc is available, otherwise QtAudioPlayer
player = get_best_player(preferred_backend="vlc")
player.load("C:/Music/track.mp3")
player.set_volume(85)
player.play()

# Query status
print("Is playing:", player.is_playing())
print("Position:", player.get_position(), "seconds")
```

### 4. Embedding the Music Browser in an Existing PyQt App
```python
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from media_scanner import StorageManager, MusicPlayerWindow

app = QApplication([])
songs = StorageManager.load_songs("indexed_songs.json")

# Open as a standalone window or embed as a widget
player_win = MusicPlayerWindow(songs=songs)
player_win.show()
app.exec()
```

---

## Running Tests
Run the included test suite to verify indexing, extraction, and player backends:
```bash
python -m unittest discover tests
```
