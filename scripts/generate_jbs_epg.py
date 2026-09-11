#!/usr/bin/env python3
"""
Standalone JBS EPG generator from https://jbsdvr.tulix.tv/schedule/schedule.php
Outputs: output/epg-jbs.xml
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import requests
    from lxml import etree, html
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Add 'lxml' and 'requests' to requirements.txt")
    sys.exit(0)

SCHEDULE_URL = "https://jbsdvr.tulix.tv/schedule/schedule.php"
OUTPUT_DIR = Path("output")
CHANNEL_ID = "jbs"
CHANNEL_NAME = "JBS"
TZ = ZoneInfo("America/New_York")
MAX_DAYS = 14


def parse_end_from_span(span_text, start_dt):
    if not span_text:
        return None
    text = re.sub(r"\s+", " ", span_text).strip()
    match = re.search(
        r"(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        end_clock = datetime.strptime(match.group(2).upper(), "%I:%M %p").time()
        end_dt = datetime.combine(start_dt.date(), end_clock, tzinfo=TZ)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        return end_dt
    except ValueError:
        return None


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"Working dir: {Path.cwd()}")
    print(f"Output dir: {OUTPUT_DIR.absolute()}")

    print("Fetching JBS schedule...")
    headers = {"User-Agent": "ZipWave-EPG/1.0"}
    try:
        r = requests.get(SCHEDULE_URL, timeout=60, headers=headers)
        r.raise_for_status()
        print(f"Downloaded {len(r.text):,} characters")
    except Exception as e:
        print(f"Fetch failed: {e}")
        return

    try:
        root = html.fromstring(r.content)
        rows = root.xpath("//div[contains(@class,'epgs-row') and @data-tms]")
        print(f"Found {len(rows)} listings")
    except Exception as e:
        print(f"HTML parsing failed: {e}")
        return

    items = []
    seen = set()

    for row in rows:
        ts_raw = row.get("data-tms")
        if not ts_raw or ts_raw in seen:
            continue
        try:
            start = datetime.fromtimestamp(int(ts_raw), TZ)
        except (TypeError, ValueError, OSError):
            continue
        seen.add(ts_raw)

        detail = row.getnext()
        title = CHANNEL_NAME
        episode = ""
        desc = ""
        rating = ""

        if detail is not None and "detail" in (detail.get("class") or ""):
            title_el = detail.find(".//h3[@class='detail_title']")
            ep_el = detail.find(".//h4[@class='detail_episode-title']")
            desc_el = detail.find(".//p[@class='detail_desc']")
            meta_el = detail.find(".//div[@class='detail_meta']")

            if title_el is not None and title_el.text:
                title = title_el.text.strip()
            if ep_el is not None:
                episode = re.sub(r"\s+", " ", "".join(ep_el.itertext())).strip()
            if desc_el is not None and desc_el.text:
                desc = " ".join(desc_el.text.split()).strip()
            if meta_el is not None:
                meta = " ".join(meta_el.itertext())
                rating_m = re.search(r"TV-[A-Z0-9]+", meta)
                if rating_m:
                    rating = rating_m.group(0)

        span = row.find(".//span[@class='list__time']")
        span_text = "".join(span.itertext()) if span is not None else ""
        end = parse_end_from_span(span_text, start)

        items.append({
            "start": start,
            "end": end,
            "title": title or CHANNEL_NAME,
            "episode": episode,
            "desc": desc,
            "rating": rating,
        })

    items.sort(key=lambda x: x["start"])
    for i, item in enumerate(items):
        if item["end"] is None:
            if i + 1 < len(items):
                item["end"] = items[i + 1]["start"]
            else:
                item["end"] = item["start"] + timedelta(minutes=30)

    if not items:
        print("No JBS listings found")
        return

    tv = build_xmltv(items)
    save_xml(tv)


def build_xmltv(items):
    print("Reformatting to ZipWave style...")

    tv = etree.Element("tv")
    tv.set("generator-info-name", "ZipWave JBS EPG Generator")
    tv.set("generator-info-url", "https://github.com/benevenstanciano/zip-epg")

    channel = etree.SubElement(tv, "channel", id=CHANNEL_ID)
    etree.SubElement(channel, "display-name").text = CHANNEL_NAME

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=MAX_DAYS)
    count = 0

    for item in items:
        start_utc = item["start"].astimezone(timezone.utc)
        end_utc = item["end"].astimezone(timezone.utc)

        if end_utc < now or start_utc > cutoff:
            continue

        prog = etree.SubElement(tv, "programme", {
            "start": start_utc.strftime("%Y%m%d%H%M%S +0000"),
            "stop": end_utc.strftime("%Y%m%d%H%M%S +0000"),
            "channel": CHANNEL_ID,
        })

        title_text = item["title"]
        if item["episode"]:
            title_text = f'{item["title"]} "{item["episode"]}"'
        etree.SubElement(prog, "title").text = title_text

        if item["desc"]:
            etree.SubElement(prog, "desc").text = item["desc"][:1500]

        if item["rating"]:
            rating = etree.SubElement(prog, "rating", system="MPAA")
            etree.SubElement(rating, "value").text = item["rating"]

        count += 1

    print(f"Generated {count} programme entries for JBS")
    return tv


def save_xml(tv):
    xml_path = OUTPUT_DIR / "epg-jbs.xml"
    tree = etree.ElementTree(tv)
    tree.write(str(xml_path), encoding="utf-8", pretty_print=True, xml_declaration=True)
    print(f"Saved {xml_path} ({xml_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
