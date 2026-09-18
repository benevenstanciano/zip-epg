#!/usr/bin/env python3
"""
Standalone Silk Way TV EPG generator from https://silkwaytv.kz/en/schedule

Source times are Kazakhstan local time (Asia/Almaty, UTC+5, no DST).
Output times are UTC in XMLTV format, matching the other ZipWave generators.

Outputs: output/epg-silkway.xml

Wire-up (same pattern as JBS / PTN / Best Coach TV):

  .github/workflows/update.yml
      - name: Generate Silk Way EPG
        continue-on-error: true
        run: python scripts/generate_silkway_epg.py

  scripts/combine_epg.py  SOURCES list
      "docs/epg-silkway.xml",
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

try:
    import requests
    from lxml import etree, html
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Add 'lxml' and 'requests' to requirements.txt")
    sys.exit(0)

SCHEDULE_URL = "https://silkwaytv.kz/en/schedule"
OUTPUT_DIR = Path("output")
CHANNEL_ID = "silkway"
CHANNEL_NAME = "Silk Way"
TZ = ZoneInfo("Asia/Almaty")
MAX_DAYS = 14
LOOKBACK_DAYS = 1
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    "Referer": "https://silkwaytv.kz/en/",
}

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
DATE_QUERY_RE = re.compile(r"date=(\d{4}-\d{2}-\d{2})")
BOLD_ROW_RE = re.compile(
    r"\*\*\s*(\d{1,2}:\d{2})\s*\*\*.*?\*\*\s*(.+?)\s*\*\*",
    re.DOTALL,
)


def fetch(url: str) -> str | None:
    try:
        r = requests.get(url, timeout=60, headers=HEADERS)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        print(f"Downloaded {url} ({len(r.text):,} characters)")
        return r.text
    except Exception as e:
        print(f"Fetch failed for {url}: {e}")
        return None


def discover_dates(page: str, fallback_today: date) -> list[date]:
    found: set[date] = set()
    for match in DATE_QUERY_RE.finditer(page or ""):
        try:
            found.add(date.fromisoformat(match.group(1)))
        except ValueError:
            continue

    if not found:
        for offset in range(-LOOKBACK_DAYS, 7):
            found.add(fallback_today + timedelta(days=offset))

    start = fallback_today - timedelta(days=LOOKBACK_DAYS)
    end = fallback_today + timedelta(days=MAX_DAYS - 1)
    dates = [d for d in sorted(found) if start <= d <= end]
    if not dates:
        dates = [fallback_today + timedelta(days=i) for i in range(7)]
    return dates


def cell_text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def parse_clock(value: str) -> tuple[int, int] | None:
    match = TIME_RE.match(value.strip())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def extract_listings_from_html(page: str) -> list[tuple[tuple[int, int], str]]:
    listings: list[tuple[tuple[int, int], str]] = []
    try:
        root = html.fromstring(page.encode("utf-8", errors="ignore"))
    except Exception:
        return listings

    seen: set[tuple[int, int, str]] = set()

    def add(clock: tuple[int, int], title: str) -> None:
        title = re.sub(r"\s+", " ", title).strip(" |-*")
        if not title:
            return
        key = (clock[0], clock[1], title.casefold())
        if key in seen:
            return
        seen.add(key)
        listings.append((clock, title))

    for row in root.xpath("//tr"):
        cells = row.xpath("./th|./td")
        if len(cells) < 2:
            continue
        clock = parse_clock(cell_text(cells[0]))
        title = cell_text(cells[1])
        if clock and title and not DATE_QUERY_RE.search(title):
            add(clock, title)

    if listings:
        return listings

    for node in root.xpath("//*"):
        text = cell_text(node)
        clock = parse_clock(text)
        if not clock:
            continue
        title = ""
        sibling = node.getnext()
        if sibling is not None:
            title = cell_text(sibling)
        if not title:
            parent = node.getparent()
            if parent is not None:
                full = cell_text(parent)
                title = full.replace(text, "", 1).strip(" |-")
        if title:
            add(clock, title)

    return listings


def extract_listings_from_text(page: str) -> list[tuple[tuple[int, int], str]]:
    listings: list[tuple[tuple[int, int], str]] = []
    seen: set[tuple[int, int, str]] = set()

    for hour, minute, title in re.findall(
        r"(?m)^\s*\*{0,2}\s*(\d{1,2}):(\d{2})\s*\*{0,2}\s*[|\t ]+\s*\*{0,2}\s*(.+?)\s*\*{0,2}\s*$",
        page,
    ):
        clock = parse_clock(f"{hour}:{minute}")
        clean = re.sub(r"\s+", " ", title).strip(" |-*")
        if not clock or not clean or DATE_QUERY_RE.search(clean):
            continue
        key = (clock[0], clock[1], clean.casefold())
        if key in seen:
            continue
        seen.add(key)
        listings.append((clock, clean))

    if listings:
        return listings

    for match in BOLD_ROW_RE.finditer(page):
        clock = parse_clock(match.group(1))
        title = re.sub(r"\s+", " ", match.group(2)).strip(" |-*")
        if clock and title:
            listings.append((clock, title))
    return listings


def parse_day(page: str, day: date) -> list[dict]:
    rows = extract_listings_from_html(page) or extract_listings_from_text(page)
    items = []
    for clock, title in rows:
        start = datetime(day.year, day.month, day.day, clock[0], clock[1], tzinfo=TZ)
        items.append({"start": start, "end": None, "title": title})
    items.sort(key=lambda item: item["start"])
    return items


def close_gaps(items: list[dict]) -> list[dict]:
    items.sort(key=lambda item: item["start"])
    for i, item in enumerate(items):
        if item["end"] is not None:
            continue
        if i + 1 < len(items):
            item["end"] = items[i + 1]["start"]
        else:
            item["end"] = item["start"] + timedelta(minutes=30)
        if item["end"] <= item["start"]:
            item["end"] = item["start"] + timedelta(minutes=30)
    return items


def build_xmltv(items: list[dict]) -> etree._Element:
    print("Reformatting to ZipWave style...")

    tv = etree.Element("tv")
    tv.set("generator-info-name", "ZipWave Silk Way EPG Generator")
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
        etree.SubElement(prog, "title").text = item["title"] or CHANNEL_NAME
        count += 1

    print(f"Generated {count} programme entries for Silk Way")
    return tv


def save_xml(tv: etree._Element) -> None:
    xml_path = OUTPUT_DIR / "epg-silkway.xml"
    tree = etree.ElementTree(tv)
    tree.write(str(xml_path), encoding="utf-8", pretty_print=True, xml_declaration=True)
    print(f"Saved {xml_path} ({xml_path.stat().st_size:,} bytes)")


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"Working dir: {Path.cwd()}")
    print(f"Output dir: {OUTPUT_DIR.absolute()}")
    print("Fetching Silk Way schedule...")

    today = datetime.now(TZ).date()
    landing = fetch(SCHEDULE_URL)
    if landing is None:
        print("→ Skipping Silk Way EPG (source unavailable). Continuing job.")
        return

    dates = discover_dates(landing, today)
    print(f"Schedule dates: {', '.join(d.isoformat() for d in dates)}")

    items: list[dict] = []
    pages: dict[date, str] = {}

    landing_dates = discover_dates(landing, today)
    if today in landing_dates or DATE_QUERY_RE.search(landing or ""):
        pages[today] = landing

    for day in dates:
        if day in pages:
            page = pages[day]
        else:
            page = fetch(f"{SCHEDULE_URL}?date={day.isoformat()}")
            if page is None:
                continue
            pages[day] = page
        day_items = parse_day(page, day)
        print(f"  {day.isoformat()}: {len(day_items)} listings")
        items.extend(day_items)

    if not items:
        print("No Silk Way listings found")
        return

    items = close_gaps(items)
    tv = build_xmltv(items)
    save_xml(tv)


if __name__ == "__main__":
    main()
