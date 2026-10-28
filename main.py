#!/usr/bin/env python3
"""
Audio Library Scanner & Music Player
====================================
Main entrypoint for command-line indexing and GUI playback.

Usage:
    python main.py
    python main.py --folders "C:\\Music" "D:\\Audio"
    python main.py -f "C:\\Music" --no-gui
    python main.py --engine qt
"""

import sys
import argparse
from media_scanner.cli import run_cli_flow
from media_scanner.storage import DEFAULT_SONGS_JSON, DEFAULT_UNINDEXED_JSON


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Scan directories for songs, extract audio metadata, generate JSON catalogs, and browse/play tracks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-f", "--folders",
        nargs="+",
        help="One or more folder paths to search (if omitted, prompts interactively in cmd).",
        default=None,
    )
    parser.add_argument(
        "--songs-out",
        help=f"Output file path for indexed songs JSON (default: {DEFAULT_SONGS_JSON}).",
        default=DEFAULT_SONGS_JSON,
    )
    parser.add_argument(
        "--unindexed-out",
        help=f"Output file path for unindexed/failed files JSON (default: {DEFAULT_UNINDEXED_JSON}).",
        default=DEFAULT_UNINDEXED_JSON,
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run only in CMD mode and skip launching the GUI window after indexing.",
    )
    parser.add_argument(
        "--engine",
        choices=["vlc", "qt"],
        default="vlc",
        help="Preferred audio player engine for GUI (default: vlc).",
    )

    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Ignore cached metadata and force full re-indexing of all files.",
    )

    return parser.parse_args()


def main():
    args = parse_arguments()
    try:
        run_cli_flow(
            input_folders=args.folders,
            songs_json_path=args.songs_out,
            unindexed_json_path=args.unindexed_out,
            launch_gui_after_scan=not args.no_gui,
            preferred_player_engine=args.engine,
            force_full_scan=args.full_scan,
        )
    except KeyboardInterrupt:
        print("\n\n[!] Operation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[X] Fatal Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
