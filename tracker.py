#!/usr/bin/env python3
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

TRACKING_NUMBER = "1Z2EB7356826735511"
SOURCE_URL = f"http://8.134.51.61:8082/trackIndex.htm?documentCode={TRACKING_NUMBER}"
OUTPUT = Path("tracking.json")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts = []
        self.rows = []
        self._in_tr = False
        self._in_td = False
        self._row = []
        self._cell = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "tr":
            self._in_tr = True
            self._row = []
        elif tag == "td" and self._in_tr:
            self._in_td = True
            self._cell = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "td" and self._in_td:
            self._row.append(clean("".join(self._cell)))
            self._in_td = False
            self._cell = []
        elif tag == "tr" and self._in_tr:
            if self._row:
                self.rows.append(self._row)
            self._in_tr = False
            self._row = []

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_td:
            self._cell.append(data)
        self.text_parts.append(data)


def fetch_html() -> str:
    req = Request(
        SOURCE_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(req, timeout=30) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def parse(html: str) -> dict:
    p = PageParser()
    p.feed(html)

    lines = [clean(x) for x in p.text_parts]
    lines = [x for x in lines if x]

    piece_count = None
    for line in lines:
        m = re.search(r"件数\s*[:：]?\s*【?(\d+)】?", line)
        if m:
            piece_count = int(m.group(1))
            break

    labels = ["参考号", "跟踪号码", "目的地", "当地时间", "最新状态"]
    summary = {}
    for i in range(len(lines) - 10):
        if lines[i : i + 5] == labels:
            values = lines[i + 5 : i + 10]
            summary = {
                "reference_number": values[0],
                "tracking_number": values[1],
                "destination": values[2],
                "latest_time": values[3],
                "current_status": values[4].rstrip("/"),
            }
            break

    events = []
    dt_re = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$")
    for row in p.rows:
        cells = [clean(c) for c in row if clean(c)]
        if not cells or not dt_re.match(cells[0]):
            continue
        if len(cells) >= 3:
            date_time, location, status = cells[0], cells[1], cells[-1]
        elif len(cells) == 2:
            date_time, status = cells
            location = None
        else:
            continue
        events.append({
            "date_time": date_time,
            "location": location or None,
            "status": status,
        })

    # Keep first occurrence of each exact event in page order.
    unique = []
    seen = set()
    for event in events:
        key = (event["date_time"], event["location"], event["status"])
        if key not in seen:
            seen.add(key)
            unique.append(event)
    events = unique

    if not summary:
        raise RuntimeError("Could not parse shipment summary from San See HTML")
    if summary.get("tracking_number") != TRACKING_NUMBER:
        raise RuntimeError(f"Tracking number mismatch: {summary.get('tracking_number')!r}")
    if not events:
        raise RuntimeError("Could not parse any tracking events from San See HTML")

    result = {
        "tracking_number": TRACKING_NUMBER,
        "reference_number": summary["reference_number"],
        "destination": summary["destination"],
        "piece_count": piece_count,
        "current_status": summary["current_status"],
        "latest_time": summary["latest_time"],
        "latest_event": events[0],
        "events": events,
        "source": "San See Express / 三色国际物流",
        "source_url": SOURCE_URL,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return result


def main():
    html = fetch_html()
    result = parse(html)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
