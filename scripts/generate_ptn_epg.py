#!/usr/bin/env python3
"""
Standalone PTN EPG generator from Tockify ICS feed.
Outputs: output/epg-ptn.xml
"""

import requests
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from ics import Calendar
from lxml import etree

# Config
ICS_URL = "https://tockify.com/api/feeds/ics/ptn.schedule"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
CHANNEL_ID = "ptn"
CHANNEL_NAME = "Pioneer Network"
MAX_DAYS = 14

OUTPUT_DIR.mkdir(exist_ok=True)

def fetch_ics():
    print(f"Fetching Pioneer Network ICS...")
    headers = {"User-Agent": "ZipWave-EPG/1.0"}
    try:
        r = requests.get(ICS_URL, timeout=30, headers=headers)
        r.raise_for_status()
        return Calendar(r.text)
    except Exception as e:
        print(f"❌ Failed to fetch ICS: {e}")
        sys.exit(1)

def convert_to_xmltv(cal):
    print(f"Converting {len(cal.events)} events...")

    tv = etree.Element("tv")
    tv.set("generator-info-name", "ZipWave PTN EPG Generator")
    tv.set("generator-info-url", "https://github.com/benevenstanciano/zip-epg")

    # Channel definition
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

            if hasattr(event, 'categories') and event.categories:
                cat = etree.SubElement(prog, "category")
                cat.text = ", ".join(event.categories)

            count += 1

        except Exception:
            continue

    print(f"✅ Generated {count} programme entries for Pioneer Network")
    return tv

def save_xml(tv):
    xml_path = OUTPUT_DIR / "epg-ptn.xml"
    tree = etree.ElementTree(tv)
    tree.write(str(xml_path), encoding="utf-8", pretty_print=True, xml_declaration=True)
    print(f"✅ Saved: {xml_path}")

if __name__ == "__main__":
    cal = fetch_ics()
    tv = convert_to_xmltv(cal)
    save_xml(tv)
