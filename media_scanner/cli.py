"""
Command-Line Interface Module
=============================
Interactive console workflow with:
- Smart HDD cache check and folder memory
- In-place terminal progress bar for newly discovered/modified files
- Dual JSON persistence
- Failure breakdown in cmd
- Multi-tab GUI launch with VLC fingerprint inspector and failed files page
"""

from __future__ import annotations

import os
import sys
import shutil
from typing import List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .metadata import AudioMetadata
from .scanner import AudioIndexer, ScanResult, FileScanStatus
from .storage import StorageManager, DEFAULT_SONGS_JSON, DEFAULT_UNINDEXED_JSON
from .gui import launch_gui


def render_progress_bar(current: int, total: int, current_filename: str, bar_length: int = 30):
    """
    Renders an in-place progress bar in the command line terminal.
    Truncates file names to avoid line wrapping in cmd.
    """
    if total <= 0:
        percent = 100.0
        filled = bar_length
    else:
        percent = (current / total) * 100.0
        filled = int(bar_length * current // total)

    bar = "█" * filled + "░" * (bar_length - filled)
    
    term_width = shutil.get_terminal_size((80, 24)).columns
    prefix = f"\rProgress: [{bar}] {percent:5.1f}% ({current}/{total})"
    space_left = term_width - len(prefix) - 10
    
    if space_left > 12:
        if len(current_filename) > space_left:
            disp_name = "..." + current_filename[-(space_left - 3):]
        else:
            disp_name = current_filename
        msg = f"{prefix} | {disp_name}"
    else:
        msg = prefix

    padded = msg.ljust(term_width - 1)
    sys.stdout.write(padded)
    sys.stdout.flush()


def prompt_folder_selection(
    remembered_folders: Optional[List[str]] = None,
    allow_skip_to_gui: bool = False
) -> Tuple[List[str], bool]:
    """
    Interactive terminal prompt allowing the user to select one or multiple folders,
    with smart recall of previously scanned directories.
    Returns (selected_folders, skip_scan_launch_gui).
    """
    print("\n" + "=" * 65)
    print("           AUDIO DIRECTORY SELECTION (CMD INTERFACE)           ")
    print("=" * 65)

    if remembered_folders:
        valid_remembered = [f for f in remembered_folders if os.path.isdir(f)]
        if valid_remembered:
            print("Previous music directory found in library catalog:")
            for idx, f in enumerate(valid_remembered, 1):
                try:
                    count = len(os.listdir(f))
                    info = f"({count} items in folder)"
                except Exception:
                    info = ""
                print(f"  [{idx}] {f} {info}")
            print("-" * 65)
            print("Options:")
            print("  [Y] Smart Refresh these folders (detects new/modified tracks)")
            if allow_skip_to_gui:
                print("  [G] Skip scan and open GUI Music Player directly")
            print("  [C] Choose different / additional folders")
            print("-" * 65)
            choice = input(f"Select an option [{'Y/g/c' if allow_skip_to_gui else 'Y/c'}] (default: Y): ").strip().lower()
            if choice in ("", "y", "yes"):
                return valid_remembered, False
            elif allow_skip_to_gui and choice in ("g", "gui", "play"):
                return valid_remembered, True

    print("Enter the full path to each folder you want to index.")
    print("Tips:")
    print("  - You can enter multiple directories one by one.")
    print("  - Quotes around paths (e.g. \"C:\\My Music\") will be handled automatically.")
    print("  - Press [Enter] on an empty line when finished adding folders.")
    print("-" * 65)

    selected_folders: List[str] = []

    while True:
        prompt_num = len(selected_folders) + 1
        raw_input_path = input(f"Enter folder #{prompt_num} (or press Enter to finish): ").strip()

        if not raw_input_path:
            if selected_folders:
                break
            else:
                print("  [!] Please specify at least one folder before continuing.")
                continue

        clean_path = raw_input_path.strip('\"\'')
        abs_path = os.path.abspath(clean_path)

        if not os.path.isdir(abs_path):
            print(f"  [X] Error: '{abs_path}' is not a valid directory. Please try again.")
            continue

        if abs_path in selected_folders:
            print(f"  [!] Folder '{abs_path}' has already been added.")
            continue

        selected_folders.append(abs_path)
        print(f"  [+] Added: {abs_path}")

    return selected_folders, False


def display_selected_folders(folders: List[str]):
    print("\n" + "=" * 65)
    print("                     TARGET FOLDERS                            ")
    print("=" * 65)
    for idx, folder in enumerate(folders, start=1):
        try:
            items_count = len(os.listdir(folder))
            info = f"({items_count} items in folder)"
        except Exception:
            info = "(inaccessible)"
        print(f"  [{idx}] {folder} {info}")
    print("=" * 65 + "\n")


def print_failed_files_report(unindexed_files: List[FileScanStatus], max_display: int = 25):
    if not unindexed_files:
        print("\n[+] All scanned files were successfully identified and indexed as songs!")
        return

    print("\n" + "=" * 65)
    print(f"       FILES THAT COULD NOT BE INDEXED AS SONGS ({len(unindexed_files)})        ")
    print("=" * 65)

    for idx, item in enumerate(unindexed_files[:max_display], start=1):
        print(f"  [{idx}] {item.file_name}")
        print(f"      Path:   {item.file_path}")
        print(f"      Reason: {item.reason}")
        if item.error_details:
            print(f"      Error:  {item.error_details}")
        print()

    if len(unindexed_files) > max_display:
        remainder = len(unindexed_files) - max_display
        print(f"  ... and {remainder} more files (see 'Unindexed & Failed' tab in GUI).")

    print("-" * 65)


def run_cli_flow(
    input_folders: Optional[List[str]] = None,
    songs_json_path: str = DEFAULT_SONGS_JSON,
    unindexed_json_path: str = DEFAULT_UNINDEXED_JSON,
    launch_gui_after_scan: bool = True,
    preferred_player_engine: str = "vlc",
    force_full_scan: bool = False,
) -> ScanResult:
    """
    Main CLI execution pipeline with Smart HDD Refresh:
    1. Loads cached library (remembers folders and prior metadata)
    2. Fast scandir compares timestamps without opening audio files
    3. Terminal progress bar indexes only new or modified files
    4. Saves updated JSON catalogs
    5. Shows console report
    6. Launches multi-page GUI
    """
    # 1. Load existing cache
    cached_songs, cached_unindexed, remembered_folders = StorageManager.load_cached_library(
        songs_filepath=songs_json_path,
        unindexed_filepath=unindexed_json_path,
    )

    if force_full_scan:
        cached_songs = {}
        cached_unindexed = {}

    # 2. Determine target folders
    skip_scan = False
    if not input_folders:
        folders, skip_scan = prompt_folder_selection(
            remembered_folders if cached_songs else None,
            allow_skip_to_gui=bool(cached_songs)
        )
    else:
        folders = [os.path.abspath(f.strip('\"\'')) for f in input_folders if os.path.isdir(f.strip('\"\''))]
        if not folders:
            print("[!] None of the provided folder paths are valid directories.")
            folders, skip_scan = prompt_folder_selection(
                remembered_folders,
                allow_skip_to_gui=bool(cached_songs)
            )

    # 3. Fast launch option if user opted to skip scanning
    if skip_scan and cached_songs:
        print("\n[+] Launching GUI music player directly with existing library catalog...")
        songs_list = list(cached_songs.values())
        unindexed_list = list(cached_unindexed.values())
        if launch_gui_after_scan:
            launch_gui(
                songs=songs_list,
                unindexed=unindexed_list,
                preferred_engine=preferred_player_engine,
                songs_json_path=songs_json_path,
            )
        return ScanResult(folders=folders, songs=songs_list, unindexed_files=unindexed_list)

    display_selected_folders(folders)

    # 3. Smart Indexing (HDD optimized)
    print("Initiating Smart Refresh (checking timestamps)...")
    indexer = AudioIndexer()

    def on_progress(current: int, total: int, filename: str):
        render_progress_bar(current, total, filename)

    result = indexer.scan_folders(
        folders,
        recursive=True,
        cached_songs=cached_songs,
        cached_unindexed=cached_unindexed,
        progress_callback=on_progress,
    )

    if result.new_files_count > 0 or result.modified_files_count > 0:
        print("\n")  # Newline after progress bar completes
    else:
        print("[+] All files are up-to-date in cache. (Zero unnecessary disk I/O)")

    # 4. Save JSON files
    songs_file, unindexed_file = StorageManager.save_scan_result(
        result=result,
        songs_filepath=songs_json_path,
        unindexed_filepath=unindexed_json_path,
    )

    print("\n" + "=" * 65)
    print("                     SCAN RESULTS                              ")
    print("=" * 65)
    print(f"  Total files examined:    {result.total_files_examined}")
    print(f"  Songs indexed:           {result.song_count}")
    print(f"    - Complete metadata:   {result.song_count - result.incomplete_count}")
    print(f"    - Incomplete / VLC:    {result.incomplete_count} (see 'Incomplete' tab)")
    print(f"  Unindexed / other files: {result.unindexed_count}")
    print(f"  Smart HDD Optimization:")
    print(f"    - Unchanged cached:    {result.cached_files_count} files (Instant 0-seek)")
    print(f"    - New files indexed:   {result.new_files_count}")
    print(f"    - Modified re-indexed: {result.modified_files_count}")
    print(f"    - Removed / deleted:   {result.deleted_files_count}")
    print(f"  Scan duration:           {result.elapsed_time_seconds:.2f} seconds")
    print("-" * 65)
    print(f"  [+] Songs JSON:     {songs_file}")
    print(f"  [+] Unindexed JSON: {unindexed_file}")
    print("=" * 65)

    # 5. Display failure list in CMD
    print_failed_files_report(result.unindexed_files)

    # 6. Launch GUI player with all 3 pages
    if launch_gui_after_scan:
        print("\n[+] Launching Multi-Tab Music Player & Inspector...")
        print("    (Close the GUI window when finished)")
        launch_gui(
            result.songs,
            unindexed=result.unindexed_files,
            preferred_engine=preferred_player_engine,
            songs_json_path=songs_json_path,
        )

    return result
