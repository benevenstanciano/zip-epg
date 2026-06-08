#!/usr/bin/env python3
"""
Standalone PTN EPG generator - robust for GitHub Actions
"""

import requests
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import pytz
    from ics import Calendar
    from lxml import etree
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("Run: pip install ics pytz lxml")
    sys.exit(1)

# Config
ICS_URL = "https://tockify.com/api/feeds/ics/ptn.schedule"
OUTPUT_DIR = Path("output")
CHANNEL_ID = "ptn"
CHANNEL_NAME = "Pioneer Network"
MAX_DAYS = 14

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"Working directory: {Path.cwd()}")
    print(f"Output dir: {OUTPUT_DIR.absolute()}")

    # Fetch
    print("Fetching ICS...")
    headers = {"User-Agent": "ZipWave-EPG/1.0"}
    try:
        r = requests.get(ICS_URL, timeout=45, headers=headers)
        r.raise_for_status()
        print(f"✅ Fetched {len(r.text)} characters")
    except Exception as e:
        print(f"❌ Fetch failed: {e}")
        sys.exit(1)

    # Parse
    try:
        cal = Calendar(r.text)
        print(f"✅ Parsed calendar with {len(cal.events)} events")
    except Exception as e:
        print(f"❌ ICS parsing failed: {e}")
        sys.exit(1)

    # Convert
    tv = convert_to_xmltv(cal)
    save_xml(tv)

def convert_to_xmltv(cal):
    print("Converting to XMLTV...")

    tv = etree.Element("tv")
    tv.set("generator-info-name", "ZipWave PTN EPG Generator")
    tv.set("generator-info-url", "https://github.com/benevenstanciano/zip-epg")

    channel = etree.SubElement(tv, "channel", id=CHANNEL_ID)
    etree.SubElement(channel, "display-name").text = CHANNEL_NAME

    now = datetime.now(pytz.utc)
    cutoff = now + timedelta(days=MAX_DAYS)

    count = 0
    for event in sorted(cal.events, key=lambda e: e.begin):
        try:
            start = event.begin.to("utc").datetime
            end = event.end.to("utc").datetime

            if end < now or start > cutoff:
                continue

            prog = etree.SubElement(tv, "programme", {
                "start": start.strftime("%Y%m%d%H%M%S +0000"),
                "stop": end.strftime("%Y%m%d%H%M%S +0000"),
                "channel": CHANNEL_ID
            })

            title_el = etree.SubElement(prog, "title")
            title_el.text = (event.name or CHANNEL_NAME).strip()

            if event.description:
                desc = etree.SubElement(prog, "desc")
                clean_desc = " ".join(str(event.description).split())
                desc.text = clean_desc[:1200]

            count += 1
        except Exception as e:
            continue

    print(f"✅ Generated {count} programme entries")
    return tv

def save_xml(tv):
    xml_path = OUTPUT_DIR / "epg-ptn.xml"
    try:
        tree = etree.ElementTree(tv)
        tree.write(str(xml_path), encoding="utf-8", pretty_print=True, xml_declaration=True)
        print(f"✅ Saved {xml_path} ({xml_path.stat().st_size} bytes)")
    except Exception as e:
        print(f"❌ Save failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
