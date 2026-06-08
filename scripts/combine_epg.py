#!/usr/bin/env python3
"""
Merges existing EPG files from docs/ into one combined 36-hour EPG.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

from lxml import etree

# Updated paths - they are in docs/, not output/
SOURCES = [
    "docs/epg.xml",           # Main EPG
    "docs/epg-ptn.xml",
    "docs/epg-bestcoachtv.xml",   # Add others here later
]

OUTPUT_FILE = Path("docs/epg-combined.xml")
MAX_HOURS = 36

def main():
    print("🔄 Starting daily combined EPG creation...")

    combined = etree.Element("tv")
    combined.set("generator-info-name", "ZipWave Combined EPG")
    combined.set("generator-info-url", "https://github.com/benevenstanciano/zip-epg")

    now = datetime.now()
    cutoff = now + timedelta(hours=MAX_HOURS)

    total_programmes = 0
    channels_seen = set()

    for source_path in SOURCES:
        path = Path(source_path)
        if not path.exists():
            print(f"⚠️  File not found (skipping): {path}")
            continue

        try:
            tree = etree.parse(str(path))
            root = tree.getroot()

            # Copy unique channel definitions
            for ch in root.findall("channel"):
                ch_id = ch.get("id")
                if ch_id and ch_id not in channels_seen:
                    combined.append(ch)
                    channels_seen.add(ch_id)

            # Copy only programmes in the next 36 hours
            for prog in root.findall("programme"):
                try:
                    start_str = prog.get("start")
                    if not start_str:
                        continue

                    # Parse start time (handles both "20260608..." and timezone)
                    start = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")

                    if start > cutoff or start < now - timedelta(hours=6):
                        continue

                    # Copy the programme as-is
                    combined.append(prog)
                    total_programmes += 1
                except Exception as e:
                    continue

        except Exception as e:
            print(f"❌ Error reading {path}: {e}")

    # Save
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    tree = etree.ElementTree(combined)
    tree.write(str(OUTPUT_FILE), encoding="utf-8", pretty_print=True, xml_declaration=True)

    print(f"✅ Combined EPG created!")
    print(f"   • {total_programmes} programmes (next {MAX_HOURS} hours)")
    print(f"   • Channels included: {len(channels_seen)}")
    print(f"   • Saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
