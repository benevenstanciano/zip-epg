import gzip
import json
import os
from pathlib import Path
from datetime import timedelta
from collections import defaultdict

import yaml
import requests

from lxml import etree

# Import utilities (with graceful fallback)
try:
    from xmltv_utils import (
        parse_xmltv_time,
        xmltv_time,
        now_utc
    )
except ImportError:
    print("WARNING: xmltv_utils.py not found. Using fallback implementations.")
    from datetime import datetime, timezone
    from dateutil import parser

    def parse_xmltv_time(value):
        dt = parser.parse(value)
        return dt.astimezone(timezone.utc)

    def xmltv_time(dt):
        return dt.strftime("%Y%m%d%H%M%S +0000")

    def now_utc():
        return datetime.now(timezone.utc)


ROOT = Path(__file__).resolve().parent.parent

CACHE_DIR = ROOT / "cache"
OUTPUT_DIR = ROOT / "output"

CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


sources = load_yaml(ROOT / "sources.yaml")["sources"]
channels = load_yaml(ROOT / "channels.yaml")["channels"]

now = now_utc()
future_limit = now + timedelta(days=3)
history_limit = now - timedelta(hours=12)

source_docs = {}

print("=== Loading EPG Sources ===")
for source_id, source in sources.items():
    cache_file = CACHE_DIR / f"{source_id}.xml"

    refresh = True

    if cache_file.exists():
        age_hours = (now.timestamp() - cache_file.stat().st_mtime) / 3600
        if age_hours < source.get("refresh_hours", 24):
            refresh = False

    if refresh:
        print(f"Refreshing source: {source_id}")
        try:
            r = requests.get(source["url"], timeout=120)
            r.raise_for_status()
            print(f"  ✓ Downloaded {source_id}")
        except Exception as e:
            print(f"  ✗ Failed to download {source_id}: {e}")
            if cache_file.exists():
                print(f"  → Using stale cache")
            else:
                print(f"  → No cache available - skipping source")
                continue

        # Decompress if needed
        if source["url"].endswith(".gz"):
            content = gzip.decompress(r.content)
        else:
            content = r.content

        cache_file.write_bytes(content)

    # Parse only if file exists
    if cache_file.exists():
        try:
            source_docs[source_id] = etree.parse(str(cache_file))
            print(f"  ✓ Loaded {source_id} into memory")
        except Exception as e:
            print(f"  ✗ Failed to parse {source_id}: {e}")
    else:
        print(f"  ✗ No data for {source_id}")

if not source_docs:
    print("ERROR: No EPG sources could be loaded!")
    exit(1)

print(f"\n=== Processing {len(channels)} channels ===\n")

tv = etree.Element("tv")
json_output = {}

for channel in channels:
    if not channel.get("enabled", True):
        continue

    cid = channel["id"]
    print(f"Processing channel: {channel['name']} ({cid})")

    channel_element = etree.SubElement(tv, "channel", id=cid)
    display = etree.SubElement(channel_element, "display-name")
    display.text = channel["name"]

    programmes = []
    found = False

    for source_ref in channel.get("epg_sources", []):
        source_id = source_ref["source"]
        if source_id not in source_docs:
            print(f"  → Source '{source_id}' not available, skipping")
            continue

        source_doc = source_docs[source_id]
        xmltv_id = source_ref["channel_id"]

        print(f"  → Looking for {xmltv_id} in {source_id}")

        # FIXED: Safer way to find programmes (avoids XPath dot issue)
        all_programmes = source_doc.findall(".//programme")
        for programme in all_programmes:
            if programme.get("channel") == xmltv_id:
                try:
                    start = parse_xmltv_time(programme.get("start"))
                    stop = parse_xmltv_time(programme.get("stop"))

                    if stop < history_limit or start > future_limit:
                        continue

                    programmes.append((start, stop, programme))
                except Exception as e:
                    print(f"    Warning: Could not parse time for a programme: {e}")
                    continue

        if programmes:
            found = True
            print(f"  ✓ Found programmes for {cid}")
            break

    if not found:
        print(f"  → No programmes found - using placeholder")
        placeholder = etree.SubElement(
            tv, "programme",
            channel=cid,
            start=xmltv_time(now),
            stop=xmltv_time(future_limit)
        )
        title = etree.SubElement(placeholder, "title")
        title.text = channel.get("placeholder", {}).get("title", "Programming")
        desc = etree.SubElement(placeholder, "desc")
        desc.text = channel.get("placeholder", {}).get("description", "No program information available.")
        json_output[cid] = {
            "name": channel["name"],
            "current": None,
            "next": None
        }
        continue

    # Sort and build output
    programmes.sort(key=lambda x: x[0])

    current_item = None
    next_item = None

    for idx, (start, stop, programme) in enumerate(programmes):
        new_prog = etree.SubElement(
            tv, "programme",
            channel=cid,
            start=xmltv_time(start),
            stop=xmltv_time(stop)
        )

        for child in list(programme):   # Use list() to avoid modification issues
            new_prog.append(child)

        # Track current + next for JSON
        if start <= now < stop:
            title = programme.findtext("title") or "Unknown"
            current_item = {
                "title": title,
                "start": start.isoformat(),
                "end": stop.isoformat()
            }
            if idx + 1 < len(programmes):
                ns, ne, np = programmes[idx + 1]
                next_item = {
                    "title": np.findtext("title") or "Unknown",
                    "start": ns.isoformat(),
                    "end": ne.isoformat()
                }

    json_output[cid] = {
        "name": channel["name"],
        "current": current_item,
        "next": next_item
    }

# Write outputs
tree = etree.ElementTree(tv)

xml_path = OUTPUT_DIR / "epg.xml"
tree.write(
    str(xml_path),
    encoding="utf-8",
    pretty_print=True,
    xml_declaration=True
)

with gzip.open(OUTPUT_DIR / "epg.xml.gz", "wb") as f:
    f.write(xml_path.read_bytes())

with open(OUTPUT_DIR / "current.json", "w", encoding="utf-8") as f:
    json.dump(json_output, f, indent=2, ensure_ascii=False)

print("\n=== Build completed successfully! ===")
print(f"EPG XML     → {xml_path}")
print(f"EPG GZ      → {OUTPUT_DIR / 'epg.xml.gz'}")
print(f"Current JSON→ {OUTPUT_DIR / 'current.json'}")
