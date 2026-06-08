#!/usr/bin/env python3
"""
Standalone Best Coach TV EPG generator from Viloud XMLTV feed.
Outputs: output/epg-bestcoachtv.xml
"""

import requests
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from lxml import etree
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("Add 'lxml' and 'requests' to requirements.txt")
    sys.exit(0)

# Configuration
EPG_URL = "https://deliver.viloud.tv/channel/2e49fcd9cf8aae5dd382c8b97e959921/epg?format=xmltv&days_backward=1&days_forward=7"
OUTPUT_DIR = Path("output")
CHANNEL_ID = "bestcoachtv"
CHANNEL_NAME = "Best Coach TV"

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"📁 Working dir: {Path.cwd()}")
    print(f"📁 Output dir: {OUTPUT_DIR.absolute()}")

    # Fetch
    print("🌐 Fetching Best Coach TV EPG...")
    headers = {"User-Agent": "ZipWave-EPG/1.0"}
    try:
        r = requests.get(EPG_URL, timeout=60, headers=headers)
        r.raise_for_status()
        print(f"✅ Downloaded {len(r.text):,} characters")
    except Exception as e:
        print(f"❌ Fetch failed: {e}")
        return

    # Parse source XMLTV
    try:
        source_tv = etree.fromstring(r.content)
        print("✅ Parsed source XMLTV")
    except Exception as e:
        print(f"❌ XML parsing failed: {e}")
        return

    # Build clean output
    tv = build_clean_epg(source_tv)
    save_xml(tv)

def build_clean_epg(source_tv):
    print("🔄 Reformatting to ZipWave style...")

    tv = etree.Element("tv")
    tv.set("generator-info-name", "ZipWave Best Coach TV EPG Generator")
    tv.set("generator-info-url", "https://github.com/benevenstanciano/zip-epg")

    # Channel definition (matching ptn style)
    channel = etree.SubElement(tv, "channel", id=CHANNEL_ID)
    etree.SubElement(channel, "display-name").text = CHANNEL_NAME

    now = datetime.now()
    cutoff = now + timedelta(days=8)  # Safety buffer

    count = 0
    for prog in source_tv.findall("programme"):
        try:
            start_str = prog.get("start")
            stop_str = prog.get("stop")
            channel_id = prog.get("channel")

            # Parse times (XMLTV format is usually already UTC or convertible)
            start = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
            stop = datetime.strptime(stop_str[:14], "%Y%m%d%H%M%S")

            if stop < now or start > cutoff:
                continue

            # Create new programme element
            new_prog = etree.SubElement(tv, "programme", {
                "start": start.strftime("%Y%m%d%H%M%S +0000"),
                "stop": stop.strftime("%Y%m%d%H%M%S +0000"),
                "channel": CHANNEL_ID
            })

            # Title
            title_elem = prog.find("title")
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else CHANNEL_NAME
            etree.SubElement(new_prog, "title").text = title

            # Description
            desc_elem = prog.find("desc")
            if desc_elem is not None and desc_elem.text:
                clean_desc = " ".join(desc_elem.text.split())
                etree.SubElement(new_prog, "desc").text = clean_desc[:1500]

            # Optional: Category
            for cat in prog.findall("category"):
                if cat.text:
                    etree.SubElement(new_prog, "category").text = cat.text
                    break

            count += 1

        except Exception:
            continue

    print(f"✅ Generated {count} programme entries for Best Coach TV")
    return tv

def save_xml(tv):
    xml_path = OUTPUT_DIR / "epg-bestcoachtv.xml"
    tree = etree.ElementTree(tv)
    tree.write(str(xml_path), encoding="utf-8", pretty_print=True, xml_declaration=True)
    print(f"✅ Saved {xml_path} ({xml_path.stat().st_size:,} bytes)")

if __name__ == "__main__":
    main()
