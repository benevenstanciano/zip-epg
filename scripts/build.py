import gzip
import json
import os
from pathlib import Path
from datetime import timedelta
from collections import defaultdict

import yaml
import requests

from lxml import etree

from xmltv_utils import (
    parse_xmltv_time,
    xmltv_time,
    now_utc
)

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

for source_id, source in sources.items():

    cache_file = CACHE_DIR / f"{source_id}.xml"

    refresh = True

    if cache_file.exists():
        age_hours = (
            now.timestamp()
            - cache_file.stat().st_mtime
        ) / 3600

        if age_hours < source["refresh_hours"]:
            refresh = False

    if refresh:

        try:
            r = requests.get(source["url"], timeout=120)
            r.raise_for_status()
        except Exception as e:
            print(f"Failed source {source_id}: {e}")
            continue

        if source["url"].endswith(".gz"):
            content = gzip.decompress(r.content)
        else:
            content = r.content

        cache_file.write_bytes(content)

    source_docs[source_id] = etree.parse(
        str(cache_file)
    )


tv = etree.Element("tv")

json_output = {}

for channel in channels:

    if not channel.get("enabled", True):
        continue

    cid = channel["id"]

    channel_element = etree.SubElement(
        tv,
        "channel",
        id=cid
    )

    display = etree.SubElement(
        channel_element,
        "display-name"
    )

    display.text = channel["name"]

    programmes = []

    found = False

    for source_ref in channel["epg_sources"]:

        source_doc = source_docs[source_ref["source"]]

        xmltv_id = source_ref["channel_id"]

        for programme in source_doc.xpath(
            f'//programme[@channel="{xmltv_id}"]'
        ):
            try:

                start = parse_xmltv_time(
                    programme.get("start")
                )

                stop = parse_xmltv_time(
                    programme.get("stop")
                )

                if stop < history_limit:
                    continue

                if start > future_limit:
                    continue

                programmes.append(
                    (start, stop, programme)
                )

            except Exception:
                pass

        if programmes:
            found = True
            break

    if not found:

        placeholder = etree.SubElement(
            tv,
            "programme",
            channel=cid,
            start=xmltv_time(now),
            stop=xmltv_time(future_limit)
        )

        title = etree.SubElement(
            placeholder,
            "title"
        )

        title.text = channel["placeholder"]["title"]

        desc = etree.SubElement(
            placeholder,
            "desc"
        )

        desc.text = channel["placeholder"]["description"]

        continue

    programmes.sort(key=lambda x: x[0])

    current_item = None
    next_item = None

    for idx, (start, stop, programme) in enumerate(programmes):

        new_prog = etree.SubElement(
            tv,
            "programme",
            channel=cid,
            start=xmltv_time(start),
            stop=xmltv_time(stop)
        )

        for child in programme:
            new_prog.append(child)

        if start <= now < stop:

            title = programme.findtext("title")

            current_item = {
                "title": title,
                "start": start.isoformat(),
                "end": stop.isoformat()
            }

            if idx + 1 < len(programmes):

                ns, ne, np = programmes[idx + 1]

                next_item = {
                    "title": np.findtext("title"),
                    "start": ns.isoformat(),
                    "end": ne.isoformat()
                }

    json_output[cid] = {
        "name": channel["name"],
        "current": current_item,
        "next": next_item
    }

tree = etree.ElementTree(tv)

xml_path = OUTPUT_DIR / "epg.xml"

tree.write(
    str(xml_path),
    encoding="utf-8",
    pretty_print=True,
    xml_declaration=True
)

with gzip.open(
    OUTPUT_DIR / "epg.xml.gz",
    "wb"
) as f:
    f.write(xml_path.read_bytes())

with open(
    OUTPUT_DIR / "current.json",
    "w",
    encoding="utf-8"
) as f:
    json.dump(
        json_output,
        f,
        indent=2,
        ensure_ascii=False
    )
