"""
Command-Line Interface Module
=============================
Interactive console workflow that prompts for folders, displays selections,
renders a terminal progress bar during indexing, outputs dual JSON files,
lists unindexed/failed files in the console, and launches the player GUI.
"""

from __future__ import annotations

import os
import sys
import shutil
from typing import List, Optional

# Ensure standard output can handle Unicode without crashing on Windows cmd cp1252
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
    
    # Get terminal width safely
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

    # Pad with spaces to clear previous line characters
    padded = msg.ljust(term_width - 1)
    sys.stdout.write(padded)
    sys.stdout.flush()


def prompt_folder_selection() -> List[str]:
    """
    Interactive terminal prompt allowing the user to select one or multiple folders.
    """
    print("\n" + "=" * 65)
    print("           AUDIO DIRECTORY SELECTION (CMD INTERFACE)           ")
    print("=" * 65)
    print("Enter the full path to each folder you want to index.")
    print("Tips:")
    print("  - You can enter multiple directories one by one.")
    print("  - Quotes around paths (e.g. \"C:\\My Music\") will be automatically handled.")
    print("  - Press [Enter] on an empty line when you have finished adding folders.")
    print("-" * 65)

    selected_folders: List[str] = []

    while True:
        prompt_num = len(selected_folders) + 1
        raw_input_path = input(f"Enter folder #{prompt_num} (or press Enter to finish): ").strip()

        # Check for finish signal
        if not raw_input_path:
            if selected_folders:
                break
            else:
                print("  [!] Please specify at least one folder before continuing.")
                continue

        # Strip surrounding quotes if dragged-and-dropped into cmd
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

    return selected_folders


def display_selected_folders(folders: List[str]):
    """Print the chosen folders clearly in the terminal."""
    print("\n" + "=" * 65)
    print("                     SELECTED FOLDERS                          ")
    print("=" * 65)
    for idx, folder in enumerate(folders, start=1):
        try:
            items_count = len(os.listdir(folder))
            info = f"({items_count} items in folder)"
        except Exception:
            info = "(inaccessible)"
        print(f"  [{idx}] {folder} {info}")
    print("=" * 65 + "\n")


def print_failed_files_report(unindexed_files: List[FileScanStatus], max_display: int = 30):
    """Display non-songs and files that could not be indexed in cmd."""
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
        print(f"  ... and {remainder} more files (see unindexed JSON for complete list).")

    print("-" * 65)


def run_cli_flow(
    input_folders: Optional[List[str]] = None,
    songs_json_path: str = DEFAULT_SONGS_JSON,
    unindexed_json_path: str = DEFAULT_UNINDEXED_JSON,
    launch_gui_after_scan: bool = True,
    preferred_player_engine: str = "vlc",
) -> ScanResult:
    """
    Main CLI execution pipeline:
    1. Select folders
    2. Show folders
    3. Index files with progress bar
    4. Save to 2 separate JSON files
    5. Show unindexed / failed files
    6. Launch the GUI player
    """
    # Step 1 & 2: Folder selection and display
    if not input_folders:
        folders = prompt_folder_selection()
    else:
        folders = [os.path.abspath(f.strip('\"\'')) for f in input_folders if os.path.isdir(f.strip('\"\''))]
        if not folders:
            print("[!] None of the provided folder paths are valid directories.")
            folders = prompt_folder_selection()

    display_selected_folders(folders)

    # Step 3: Indexing with cmd progress bar
    print("Starting indexing...")
    indexer = AudioIndexer()

    def on_progress(current: int, total: int, filename: str):
        render_progress_bar(current, total, filename)

    result = indexer.scan_folders(folders, recursive=True, progress_callback=on_progress)
    print("\n")  # Newline after progress bar completes

    # Step 4: Save JSON files
    songs_file, unindexed_file = StorageManager.save_scan_result(
        result=result,
        songs_filepath=songs_json_path,
        unindexed_filepath=unindexed_json_path,
    )

    print("=" * 65)
    print("                     SCAN RESULTS                              ")
    print("=" * 65)
    print(f"  Total files examined:    {result.total_files_examined}")
    print(f"  Songs indexed:           {result.song_count}")
    print(f"  Unindexed / other files: {result.unindexed_count}")
    print(f"  Duration:                {result.elapsed_time_seconds:.2f} seconds")
    print("-" * 65)
    print(f"  [+] Songs JSON saved to:     {songs_file}")
    print(f"  [+] Unindexed JSON saved to: {unindexed_file}")
    print("=" * 65)

    # Step 5: Show any files that couldn't be got
    print_failed_files_report(result.unindexed_files)

    # Step 6: Launch GUI player
    if launch_gui_after_scan:
        print("\n[+] Launching GUI Music Player & Search...")
        print("    (Close the GUI window when finished)")
        launch_gui(result.songs, preferred_engine=preferred_player_engine)

    return result
