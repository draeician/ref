#!/usr/bin/env python3
import os
from datetime import datetime

"""
Script: ref-merger-1.5.py
Author: draeician
Date: Release 1.5

Description:
    This script merges two markdown files, `links.md` and `youtube_references.md`,
    into a single unified markdown file, `references.md`. The unified file includes
    a header and combines data from both sources into a consistent format.

    The script handles two different date/time formats found in the old files:
    - 'Wed Mar 8 20:33:06 UTC 2023'
    - '2024-05-05'

    If any line cannot be parsed correctly, the script marks the data as "MISSING"
    and includes the problematic line with a "DEBUGDEBUG" prefix for easier debugging.

Purpose:
    We created this script to streamline the process of consolidating reference links
    from multiple sources into a single, unified file. This ensures consistency and
    makes it easier to manage and query the reference data.
"""

BASE = os.path.expanduser("~/")
LINKS = os.path.join(BASE, "references", "links.md")
YOUTUBE = os.path.join(BASE, "references", "youtube_references.md")
UNIFIED = os.path.join(BASE, "references", "references.md")

def ensure_path_exists(file_path: str):
    directory = os.path.dirname(file_path)
    if not os.path.exists(directory):
        os.makedirs(directory)
    if not os.path.exists(file_path):
        open(file_path, 'w').close()

def parse_date(date_str: str) -> str:
    for fmt in ("%a %b %d %H:%M:%S %Z %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(microsecond=0).isoformat()
        except ValueError:
            pass
    return "MISSING"

def merge_files():
    ensure_path_exists(UNIFIED)

    header = "Date|URL|Title|Source|Type\n"

    with open(UNIFIED, 'w') as unified_file:
        unified_file.write(header)

        if os.path.exists(LINKS):
            with open(LINKS, 'r') as links_file:
                for line in links_file:
                    if line.strip():
                        try:
                            date_str, url, title = line.split('|')
                            date_str = parse_date(date_str)
                            unified_line = f"{date_str}|{url.strip()}|{title.strip()}|General|General\n"
                        except ValueError:
                            unified_line = f"MISSING|MISSING|MISSING|General|General\nDEBUGDEBUG {line.strip()}\n"
                        unified_file.write(unified_line)

        if os.path.exists(YOUTUBE):
            with open(YOUTUBE, 'r') as youtube_file:
                for line in youtube_file:
                    if line.strip():
                        try:
                            date_str, url, title, uploader = line.split('|')
                            date_str = parse_date(date_str)
                            unified_line = f"{date_str}|{url.strip()}|{title.strip()}|{uploader.strip()}|YouTube\n"
                        except ValueError:
                            unified_line = f"MISSING|MISSING|MISSING|MISSING|YouTube\nDEBUGDEBUG {line.strip()}\n"
                        unified_file.write(unified_line)

if __name__ == "__main__":
    merge_files()
