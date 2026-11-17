#!/usr/bin/env python3
"""Weekly planner: a local web page backed by one Markdown file per week.

    planner.py          serve the page and run the daily check-in ping
    planner.py ping     show the check-in dialog right now (for testing)

Standard library only. Data lives in ./data/<year>-W<week>.md.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("PLANNER_DATA", ROOT / "data"))
PORT = int(os.environ.get("PLANNER_PORT", "4747"))
URL = "http://localhost:%d/" % PORT

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# Daily check-in: weekdays at 16:00. If the laptop was asleep at 16:00 the
# ping fires when it wakes, as long as it is still before PING_UNTIL.
PING_WEEKDAYS = {0, 1, 2, 3, 4}  # Monday=0 ... Sunday=6
PING_HOUR = 16
PING_UNTIL = 20
PING_MESSAGE = "4pm check-in: tick off what is done and add what is not finished yet."

WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
ITEM_RE = re.compile(r"^(?P<indent>\s*)(?:[-*+]\s+)?(?:\[(?P<box>[ xX])\]\s*)?(?P<text>.*)$")
SUMMARY_NOTE = (
    '<!-- "Finished" and "Not finished" are generated from the checkboxes on every save. '
    'Your own lines go under "### Also finished" and "### Also not finished"; those are kept. -->'
)
OWN_HEADS = {"also finished": "finished", "also not finished": "unfinished"}
SEARCH_LIMIT = 200

write_lock = threading.Lock()


# ---------- weeks ----------

def monday_of(week_id):
    m = WEEK_RE.match(week_id)
    if not m:
        raise ValueError("bad week id: %r" % week_id)
    return dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)


def week_id_of(date):
    year, week, _ = date.isocalendar()
    return "%d-W%02d" % (year, week)


def week_label(week_id):
    mon = monday_of(week_id)
    fri = mon + dt.timedelta(days=len(DAYS) - 1)
    start = "%s %d" % (mon.strftime("%b"), mon.day)
    end = str(fri.day) if fri.month == mon.month else "%s %d" % (fri.strftime("%b"), fri.day)
    return "Week %d · %s – %s, %d" % (mon.isocalendar()[1], start, end, fri.year)


def week_path(week_id):
    monday_of(week_id)  # validates; the id is the only user input in the path
    return DATA / (week_id + ".md")


# ---------- markdown <-> data ----------

def parse(text):
    """Read a week file into a dict.

    days        {day name: [{"text", "done", "depth"}]}; depth 1 is a sub-item of the
                nearest depth-0 item above it (any indent of two spaces or more)
    notes       free text under "## Notes"
    finished    the user's own summary lines ("### Also finished")
    unfinished  the user's own summary lines ("### Also not finished")
    extra       any other "## " sections, kept verbatim
    """
    days = {name: [] for name in DAYS}
    week = {"days": days, "finished": [], "unfinished": []}
    notes, extra = [], []
    target = own = None
    for line in text.splitlines():
        if line.startswith("## "):
            head = line[3:].strip()
            first = head.split(" ")[0].capitalize() if head else ""
            own = None
            if first in days:
                target = first
            elif head.lower() == "notes":
                target = "notes"
            elif head.lower() == "summary":
                target = "summary"
            else:
                target = "extra"
                extra.append(line)
            continue
        if target is None:
            if line.strip() and not line.startswith("# "):
                extra.append(line)  # stray text above the first section
        elif target == "summary":
            # The generated lists are skipped; only the user's own lines are read back.
            if line.startswith("### "):
                own = OWN_HEADS.get(line[4:].strip().lower())
            elif own:
                item_text = ITEM_RE.match(line).group("text").strip()
                if item_text:
                    week[own].append(item_text)
        elif target == "notes":
            notes.append(line)
        elif target == "extra":
            extra.append(line)
        else:
            m = ITEM_RE.match(line)
            item_text = m.group("text").strip()
            if item_text:
                indent = len(m.group("indent").replace("\t", "    "))
                days[target].append({
                    "text": item_text,
                    "done": m.group("box") in ("x", "X"),
                    "depth": 1 if indent >= 2 and days[target] else 0,
                })
    week["notes"] = "\n".join(notes).strip()
    week["extra"] = "\n".join(extra).strip()
    return week


def merge(into, item):
    key = " ".join(item["text"].lower().split())
    entry = into.setdefault(key, {"text": item["text"], "done": False, "subs": {}})
    entry["done"] = entry["done"] or item["done"]
    return entry


def summarize(days):
    """Top-level items merged by text across the week; finished if ticked on any day.

    Sub-items are merged under their parent by the same rule. A parent is finished
    only when it is ticked itself, whatever the state of its sub-items.
    """
    seen = {}
    for name in DAYS:
        parent = None
        for item in days[name]:
            if item["depth"] and parent:
                merge(parent["subs"], item)
            else:
                parent = merge(seen, item)
    finished = [e for e in seen.values() if e["done"]]
    unfinished = [e for e in seen.values() if not e["done"]]
    return finished, unfinished


def summary_lines(entries, list_open_subs):
    out = []
    for entry in entries:
        subs = list(entry["subs"].values())
        done = sum(1 for sub in subs if sub["done"])
        out.append("- " + entry["text"] + (" (%d/%d sub-items done)" % (done, len(subs)) if subs else ""))
        if list_open_subs:
            out += ["  - " + sub["text"] for sub in subs if not sub["done"]]
    return out


def render(week_id, week):
    mon = monday_of(week_id)
    out = ["# " + week_label(week_id), ""]
    for i, name in enumerate(DAYS):
        out.append("## %s %s" % (name, (mon + dt.timedelta(days=i)).isoformat()))
        for item in week["days"][name]:
            out.append("%s- [%s] %s" % ("  " * item["depth"], "x" if item["done"] else " ", item["text"]))
        out.append("")
    out.append("## Notes")
    if week["notes"]:
        out.append(week["notes"])
    out.append("")
    if week["extra"]:
        out += [week["extra"], ""]
    finished, unfinished = summarize(week["days"])
    out += ["## Summary", SUMMARY_NOTE, "### Finished"]
    out += summary_lines(finished, False)
    out += ["", "### Not finished"]
    out += summary_lines(unfinished, True)
    if week["finished"]:
        out += ["", "### Also finished"] + ["- " + t for t in week["finished"]]
    if week["unfinished"]:
        out += ["", "### Also not finished"] + ["- " + t for t in week["unfinished"]]
    return "\n".join(out) + "\n"


def clean_lines(values):
    lines = [" ".join(str(raw).split()) for raw in values or []]
    return [line for line in lines if line]


def mtime_of(path):
    try:
        return str(path.stat().st_mtime_ns)
    except FileNotFoundError:
        return None


def load(week_id):
    path = week_path(week_id)
    mtime = mtime_of(path)
    text = path.read_text(encoding="utf-8") if mtime else ""
    week = parse(text)
    mon = monday_of(week_id)
    return {
        "week": week_id,
        "label": week_label(week_id),
        "prev": week_id_of(mon - dt.timedelta(days=7)),
        "next": week_id_of(mon + dt.timedelta(days=7)),
        "current": week_id_of(dt.date.today()),
        "today": dt.date.today().isoformat(),
        "days": [
            {"name": name, "date": (mon + dt.timedelta(days=i)).isoformat(), "items": week["days"][name]}
            for i, name in enumerate(DAYS)
        ],
        "summary": {"finished": week["finished"], "unfinished": week["unfinished"]},
        "notes": week["notes"],
        "mtime": mtime,
    }


def save(week_id, body):
    """Write a week. Returns (ok, payload); ok is False when the file changed on disk."""
    path = week_path(week_id)
    days = {}
    for name in DAYS:
        items = []
        for raw in (body.get("days") or {}).get(name) or []:
            item_text = " ".join(str(raw.get("text", "")).split())
            if item_text:
                depth = 1 if raw.get("depth") and items else 0  # the first item cannot be a sub-item
                items.append({"text": item_text, "done": bool(raw.get("done")), "depth": depth})
        days[name] = items
    notes = str(body.get("notes") or "").strip()

    with write_lock:
        mtime = mtime_of(path)
        if mtime != body.get("mtime"):
            return False, load(week_id)
        old = parse(path.read_text(encoding="utf-8") if mtime else "")
        week = {"days": days, "notes": notes, "extra": old["extra"]}
        own = body.get("summary")
        for kind in ("finished", "unfinished"):
            # A page loaded before own summary lines existed sends none: keep what is on disk.
            week[kind] = clean_lines(own.get(kind)) if isinstance(own, dict) else old[kind]
        has_content = notes or any(days.values()) or week["finished"] or week["unfinished"]
        if mtime is None and not has_content:
            return True, {"mtime": None}  # nothing to record yet
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(render(week_id, week), encoding="utf-8")
        os.replace(tmp, path)
        return True, {"mtime": mtime_of(path)}


# ---------- search ----------

def search(query):
    """Find lines containing every word of the query, newest week first."""
    words = query.lower().split()
    hits = []
    if not words or not DATA.is_dir():
        return {"results": hits, "truncated": False}
    for path in sorted(DATA.glob("*.md"), reverse=True):
        try:
            mon = monday_of(path.stem)
        except ValueError:
            continue
        week = parse(path.read_text(encoding="utf-8"))
        rows = []
        for i, name in enumerate(DAYS):
            date = (mon + dt.timedelta(days=i)).isoformat()
            parent = None
            for item in week["days"][name]:
                if not item["depth"]:
                    parent = item["text"]
                rows.append((name, date, item["text"], item["done"], parent if item["depth"] else None))
        rows += [("Summary", None, line, True, None) for line in week["finished"]]
        rows += [("Summary", None, line, False, None) for line in week["unfinished"]]
        rows += [("Notes", None, line.strip(), None, None) for line in week["notes"].splitlines()]
        rows += [("Other", None, line.strip(), None, None) for line in week["extra"].splitlines()]
        for where, date, line, done, parent in rows:
            low = line.lower()
            if all(word in low for word in words):
                if len(hits) >= SEARCH_LIMIT:
                    return {"results": hits, "truncated": True}
                hits.append({
                    "week": path.stem, "label": week_label(path.stem),
                    "where": where, "date": date, "text": line, "done": done, "parent": parent,
                })
    return {"results": hits, "truncated": False}


# ---------- http ----------

ALLOWED_HOSTS = {"localhost:%d" % PORT, "127.0.0.1:%d" % PORT}
ALLOWED_ORIGINS = {"http://" + h for h in ALLOWED_HOSTS}
WEEK_ROUTE = re.compile(r"^/api/week/([\w-]+)$")
# The only files served besides the API: url path -> (file next to this script, content type).
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/icon.png": ("icon.png", "image/png"),
    "/favicon.ico": ("icon.png", "image/png"),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def week_id(self):
        m = WEEK_ROUTE.match(self.path.split("?")[0])
        if not m:
            return None
        week_id = week_id_of(dt.date.today()) if m.group(1) == "current" else m.group(1)
        try:
            monday_of(week_id)
        except ValueError:
            return None
        return week_id

    def do_GET(self):
        # The Host check stops other sites from reaching the planner via DNS rebinding.
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            return self.send(403, {"error": "forbidden"})
        url = urlsplit(self.path)
        if url.path in STATIC:
            name, ctype = STATIC[url.path]
            return self.send(200, (ROOT / name).read_bytes(), ctype)
        if url.path == "/api/search":
            return self.send(200, search(parse_qs(url.query).get("q", [""])[0]))
        week_id = self.week_id()
        if not week_id:
            return self.send(404, {"error": "not found"})
        self.send(200, load(week_id))

    def do_POST(self):
        # Only the planner page itself may write.
        origin = self.headers.get("Origin")
        if self.headers.get("Host") not in ALLOWED_HOSTS or (origin and origin not in ALLOWED_ORIGINS):
            return self.send(403, {"error": "forbidden"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send(415, {"error": "expected application/json"})
        week_id = self.week_id()
        if not week_id:
            return self.send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1000000:
            return self.send(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
            ok, payload = save(week_id, body)
        except (ValueError, AttributeError, TypeError) as err:
            return self.send(400, {"error": str(err)})
        self.send(200 if ok else 409, payload)


# ---------- daily ping ----------

def show_ping(timeout=3600):
    """Show the check-in dialog; open the planner if asked. Blocks until answered."""
    script = (
        "activate\n"
        "beep\n"
        'display dialog "%s" with title "Weekly planner" '
        'buttons {"Skip", "Open planner"} default button "Open planner" '
        "giving up after %d" % (PING_MESSAGE, timeout)
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if "button returned:Open planner" in result.stdout:
        subprocess.run(["open", URL + "?checkin=1"])
    return result


def ping_loop():
    marker = DATA / ".last-ping"
    while True:
        now = dt.datetime.now()
        today = now.date().isoformat()
        due = now.weekday() in PING_WEEKDAYS and PING_HOUR <= now.hour < PING_UNTIL
        if due and (marker.read_text() if marker.exists() else "") != today:
            DATA.mkdir(parents=True, exist_ok=True)
            marker.write_text(today)
            threading.Thread(target=show_ping, daemon=True).start()
        time.sleep(30)


def main():
    if sys.argv[1:] == ["ping"]:
        result = show_ping()
        print(result.stdout.strip() or result.stderr.strip())
        return
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    if os.environ.get("PLANNER_NO_PING") != "1":
        threading.Thread(target=ping_loop, daemon=True).start()
    print("Weekly planner on %s, data in %s" % (URL, DATA), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
