# Audio Media Scanner, Inspector & Player

A fast, modular Python application that indexes music collections from the command line, extracts rich audio metadata, exports detailed JSON catalogs, and launches a multi-tab PyQt6 GUI music player powered by LibVLC or QtMultimedia.

Engineered with a **Smart Incremental HDD Refresh Engine** that prevents unnecessary mechanical drive seeks on slow HDDs, plus **LibVLC media parsing and fingerprinting** to identify and enrich incomplete metadata.

---

## What's New in v1.1

- ⚡ **Smart Refresh Engine (Slow HDD Optimized)**: Remembers previous scan results and uses ultra-fast filesystem timestamp comparisons (`os.scandir` without opening audio files). Unchanged tracks are loaded from the JSON cache in milliseconds with **zero disk reads**, indexing *only* new or modified files.
- 🔍 **LibVLC Fingerprinting & Media Parsing**: Automatically parses incomplete tracks (missing artwork, missing artist, missing title, or missing album) using system LibVLC (`libvlc.dll`) to enrich missing fields and detect album covers.
- 📑 **Multi-Page GUI Interface**:
  - **Tab 1: 🎵 All Songs**: Full searchable catalog with metadata columns and instant playback.
  - **Tab 2: ⚠️ Incomplete Metadata**: Surfaces tracks missing album covers or tags, displays VLC fingerprinting status, and offers a live "⚡ Fingerprint with VLC" button.
  - **Tab 3: ❌ Unindexed & Failed Files**: Displays non-audio files (txt, jpg, pdf) and corrupted audio files with clear explanations of why they were skipped, plus right-click to open in File Explorer.
- 💾 **Folder Memory & Persistent JSON Store**: Remembers configured target folders on startup so you don't have to re-enter them each time.

---

## Project Structure

```
python media scanning/
│
├── media_scanner/
│   ├── __init__.py           # Package exports & public API
│   ├── metadata.py           # Universal tag extraction, artwork & LibVLC enrichment
│   ├── scanner.py            # Recursive crawler & Smart HDD refresh engine
│   ├── storage.py            # Dual JSON persistence & cache manager
│   ├── player.py             # LibVLC and QtAudioPlayer abstraction layers
│   ├── gui.py                # Multi-tab PyQt6 GUI player and inspector
│   └── cli.py                # Command-line interface with dynamic progress bar
│
├── main.py                   # Main executable CLI entrypoint
├── sample_data_gen.py        # Mock audio library generator for testing
├── requirements.txt          # Package requirements
├── tests/
│   └── test_scanner.py       # Unit & integration test suite
└── README.md                 # Documentation
```

---

## How It Works on Slow Mechanical Drives (Smart Refresh)

Reading thousands of audio files from a slow mechanical hard drive to parse headers can take minutes or even hours.

1. **First Run**:
   Discovers all files, extracts tags, runs VLC fingerprinting on incomplete tracks, and writes two comprehensive JSON files:
   - `indexed_songs.json`
   - `unindexed_files.json`
2. **Subsequent Runs (Smart Refresh)**:
   - Reads the cached JSON catalogs into memory in milliseconds.
   - Crawls target directories using `os.scandir` to retrieve *only* filesystem timestamps (`mtime`) and file sizes (`size`).
   - If `(size, mtime)` matches the cached entry: **The audio file is never opened or read from disk!**
   - The CMD progress bar only runs for newly detected or modified files.
   - Any deleted files are automatically pruned from the cache.

---

## Quick Start

### 1. Interactive Command-Line Mode
```bash
python main.py
```
If an existing library cache is detected, it offers an instant one-press Smart Refresh:
```
=================================================================
           AUDIO DIRECTORY SELECTION (CMD INTERFACE)           
=================================================================
Previous folders were found in the library cache:
  [1] C:\Users\Will\Music
-----------------------------------------------------------------
Use these folders for a Smart Refresh? [Y/n]: Y

Initiating Smart Refresh (checking timestamps)...
[+] All files are up-to-date in cache. (Zero unnecessary disk I/O)

=================================================================
                     SCAN RESULTS                              
=================================================================
  Total files examined:    1,420
  Songs indexed:           1,385
    - Complete metadata:   1,210
    - Incomplete / VLC:    175 (see 'Incomplete' tab)
  Unindexed / other files: 35
  Smart HDD Optimization:
    - Unchanged cached:    1,420 files (Instant 0-seek)
    - New files indexed:   0
    - Modified re-indexed: 0
    - Removed / deleted:   0
  Scan duration:           0.15 seconds
=================================================================
```

### 2. Pass Folders via CLI
```bash
python main.py --folders "C:\Music" "D:\AudioTracks"
```

### 3. Force Full Re-Scan (Bypassing Cache)
```bash
python main.py -f "C:\Music" --full-scan
```

### 4. Headless Automation (No GUI)
```bash
python main.py -f "C:\Music" --no-gui
```

---

## Integrating Into Other Python Projects

The `media_scanner` package is completely decoupled and can be imported into your own web servers, background daemons, or custom GUIs:

### 1. Fast Incremental Indexing in Background Tasks
```python
from media_scanner import AudioIndexer, StorageManager

# 1. Load existing cache from JSON
cached_songs, cached_unindexed, folders = StorageManager.load_cached_library("indexed_songs.json", "unindexed.json")

# 2. Initialize indexer with VLC enrichment enabled
indexer = AudioIndexer(enable_vlc_enrichment=True)

# 3. Perform smart incremental scan
result = indexer.scan_folders(
    folder_paths=["C:/Music"],
    cached_songs=cached_songs,
    cached_unindexed=cached_unindexed,
    progress_callback=lambda cur, tot, name: print(f"[{cur}/{tot}] Indexing {name}"),
)

print(f"Smart Scan Complete: {result.cached_files_count} cached, {result.new_files_count} new.")

# 4. Save updated state
StorageManager.save_scan_result(result, "indexed_songs.json", "unindexed.json")
```

### 2. Inspecting Incomplete Tracks and LibVLC Fingerprinting
```python
from media_scanner import MetadataExtractor, VLCMetadataEnricher

meta = MetadataExtractor.extract("C:/Music/unknown_track.mp3")

if meta.has_incomplete_metadata:
    print("Missing fields:", meta.missing_fields)
    # Trigger LibVLC deep parsing & fingerprinting
    VLCMetadataEnricher.enrich(meta)
    print("After VLC enrichment:", meta.title, "by", meta.artist)
    print("Artwork detected:", meta.has_album_art)
```

### 3. Audio Playback Engine (LibVLC / Qt)
```python
from media_scanner import get_best_player

player = get_best_player("vlc")  # Uses libvlc.dll or falls back to QtMultimedia
player.load("C:/Music/track.mp3")
player.play()
```

### 4. Embedding the Multi-Tab GUI Window
```python
from PyQt6.QtWidgets import QApplication
from media_scanner import StorageManager, MusicPlayerWindow

app = QApplication([])
songs = StorageManager.load_songs("indexed_songs.json")
unindexed = StorageManager.load_unindexed("unindexed_files.json")

window = MusicPlayerWindow(songs=songs, unindexed=unindexed)
window.show()
app.exec()
```

---

## Testing
Run the comprehensive test suite verifying metadata extraction, incremental HDD refresh, VLC enrichment, and GUI tabs:
```bash
python -m unittest discover tests
```
