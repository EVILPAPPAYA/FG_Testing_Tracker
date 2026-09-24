"""
FG Testing Tracker
A small web app for logging finished-goods lab tests per flavour, keeping the
Google Drive link to each lab report, and warning you before tests fall due.

Run:  python app.py      then open http://localhost:5000
"""
import calendar
import csv
import functools
import io
import json
import os
import re
import smtplib
import sqlite3
import tempfile
import threading
import time
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from functools import wraps

from flask import (Flask, abort, after_this_request, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import seed_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(BASE_DIR, p)


DB_PATH = _abs(config.DB_PATH)
USE_PG = bool(config.DATABASE_URL)
STORAGE_WARNING = ""  # shown in the app if data can't be kept permanently

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row
    DB_ERRORS = (sqlite3.Error, psycopg.Error)
else:
    DB_ERRORS = (sqlite3.Error,)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.update(
    SESSION_COOKIE_SECURE=config.SECURE_COOKIES,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
# Render (and most hosts) sit behind a proxy that handles HTTPS.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

DEFAULT_SETTINGS = {
    "lead_days": "30",          # warn this many days before a test is due
    "reminder_days": "7",       # remind about a missing report after this many days
    "default_lab": "Equinox",
    "notify_emails": "",        # comma separated, gets the daily summary
    "digest_hour": "9",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_tls": "1",
    "last_digest": "",
}

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS flavours(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category TEXT NOT NULL DEFAULT 'existing',
    notes TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tests(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    covers TEXT NOT NULL DEFAULT '',
    frequency_months INTEGER NOT NULL DEFAULT 12,
    price REAL,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100
);
CREATE TABLE IF NOT EXISTS submissions(
    id INTEGER PRIMARY KEY,
    flavour_id INTEGER NOT NULL REFERENCES flavours(id) ON DELETE CASCADE,
    sample_date TEXT NOT NULL,
    lab_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,                 -- awaiting_report | complete
    assigned_to TEXT NOT NULL DEFAULT '',
    assigned_email TEXT NOT NULL DEFAULT '',
    report_no TEXT NOT NULL DEFAULT '',
    report_date TEXT,
    report_link TEXT,
    file_path TEXT,
    original_filename TEXT,
    remarks TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    uploaded_by TEXT NOT NULL DEFAULT '',
    uploaded_at TEXT,
    last_reminded TEXT,
    source TEXT NOT NULL DEFAULT 'app',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submission_tests(
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    result TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(submission_id, test_id)
);
CREATE TABLE IF NOT EXISTS exclusions(
    flavour_id INTEGER NOT NULL REFERENCES flavours(id) ON DELETE CASCADE,
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    PRIMARY KEY(flavour_id, test_id)
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""


SCHEMA_PG = [
    """CREATE TABLE IF NOT EXISTS flavours(
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'existing',
        notes TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS flavours_name_key ON flavours (lower(name))",
    """CREATE TABLE IF NOT EXISTS tests(
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        covers TEXT NOT NULL DEFAULT '',
        frequency_months INTEGER NOT NULL DEFAULT 12,
        price DOUBLE PRECISION,
        active INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 100)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS tests_name_key ON tests (lower(name))",
    """CREATE TABLE IF NOT EXISTS submissions(
        id SERIAL PRIMARY KEY,
        flavour_id INTEGER NOT NULL REFERENCES flavours(id) ON DELETE CASCADE,
        sample_date TEXT NOT NULL,
        lab_name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        assigned_to TEXT NOT NULL DEFAULT '',
        assigned_email TEXT NOT NULL DEFAULT '',
        report_no TEXT NOT NULL DEFAULT '',
        report_date TEXT,
        report_link TEXT,
        file_path TEXT,
        original_filename TEXT,
        remarks TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        uploaded_by TEXT NOT NULL DEFAULT '',
        uploaded_at TEXT,
        last_reminded TEXT,
        source TEXT NOT NULL DEFAULT 'app',
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS submission_tests(
        submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
        test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
        result TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(submission_id, test_id))""",
    """CREATE TABLE IF NOT EXISTS exclusions(
        flavour_id INTEGER NOT NULL REFERENCES flavours(id) ON DELETE CASCADE,
        test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
        PRIMARY KEY(flavour_id, test_id))""",
    "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)",
]


# ---------------------------------------------------------------- database

_PG_NAMED = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


@functools.lru_cache(maxsize=512)
def _to_pg(sql):
    """Turn SQLite-style placeholders (? and :name) into Postgres ones (%s and %(name)s)."""
    return _PG_NAMED.sub(r"%(\1)s", sql.replace("%", "%%")).replace("?", "%s")


def _mask_secrets(text):
    text = re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1****@", text)
    return re.sub(r"npg_\w+", "npg_****", text)


class Database:
    """One connection to either Postgres (online) or SQLite (on your own computer)."""

    def __init__(self):
        if USE_PG:
            try:
                self.conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row,
                                            prepare_threshold=None, connect_timeout=20)
            except psycopg.ProgrammingError:
                # Don't let the error text print the password into the logs.
                raise RuntimeError(
                    "DATABASE_URL is not a valid connection string. In Neon, click Connect, use the copy "
                    "button, and paste the whole value into Render. It must look like "
                    "postgresql://USER:PASSWORD@HOST/neondb?sslmode=require") from None
            except psycopg.OperationalError as exc:
                raise RuntimeError("Could not connect to the database: " + _mask_secrets(str(exc))) from None
        else:
            self.conn = sqlite3.connect(DB_PATH, timeout=15)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql, params=()):
        return self.conn.execute(_to_pg(sql) if USE_PG else sql, params)

    def insert(self, sql, params=()):
        """Run an INSERT and return the new row's id."""
        if USE_PG:
            return self.conn.execute(_to_pg(sql) + " RETURNING id", params).fetchone()["id"]
        return self.conn.execute(sql, params).lastrowid

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def connect():
    return Database()


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        try:
            db.close()
        except DB_ERRORS:
            pass


def _prepare_sqlite_path():
    """Make sure the SQLite folder is usable; fall back to the app folder instead of crashing."""
    global DB_PATH, STORAGE_WARNING
    folder = os.path.dirname(DB_PATH) or "."
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write-test")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
    except OSError as exc:
        fallback = os.path.join(BASE_DIR, "data.db")
        print(f"  WARNING: can't write to {folder} ({exc}). Using {fallback} instead.")
        DB_PATH = fallback
        if config.ON_RENDER:
            STORAGE_WARNING = ("Data is not being saved permanently: no database is connected and no disk is "
                               "attached, so entries will be lost when Render restarts the app. "
                               "Add DATABASE_URL in Render (see DEPLOY_RENDER.md).")
    else:
        if config.ON_RENDER and not os.environ.get("FGT_DATA_DIR"):
            STORAGE_WARNING = ("Data is not being saved permanently. Add DATABASE_URL in Render "
                               "(see DEPLOY_RENDER.md).")


def init_db():
    if not USE_PG:
        _prepare_sqlite_path()
    db = connect()
    if USE_PG:
        for stmt in SCHEMA_PG:
            db.execute(stmt)
    else:
        db.conn.executescript(SCHEMA_SQLITE)
        cols = {r["name"] for r in db.execute("PRAGMA table_info(submissions)")}
        if "report_link" not in cols:  # databases created by the earlier file-upload version
            db.execute("ALTER TABLE submissions ADD COLUMN report_link TEXT")
    for k, v in DEFAULT_SETTINGS.items():
        db.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT DO NOTHING", (k, v))
    first_run = db.execute("SELECT COUNT(*) AS n FROM tests").fetchone()["n"] == 0
    if first_run:
        seed_data.seed_tests(db)
        if config.IMPORT_SHEET_DATA:
            seed_data.seed_sheet(db, now_iso())
    db.commit()
    db.close()


def get_setting(key):
    row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(key, value):
    get_db().execute("INSERT INTO settings(key, value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))


def int_setting(key, fallback):
    try:
        return int(get_setting(key))
    except (TypeError, ValueError):
        return fallback


# ---------------------------------------------------------------- helpers

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        return None


def add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


@app.template_filter("nice")
def nice_date(value):
    d = value if isinstance(value, date) else parse_date(value)
    return f"{d.day} {d.strftime('%b %Y')}" if d else "—"


@app.template_filter("short")
def short_date(value):
    d = value if isinstance(value, date) else parse_date(value)
    return f"{d.day} {d.strftime('%b')} '{d.strftime('%y')}" if d else "—"


@app.template_filter("rupees")
def rupees(value):
    if value is None or value == "":
        return "—"
    n = int(round(float(value)))
    s = str(n)
    if len(s) > 3:  # Indian digit grouping
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
        s = head + "," + tail
    return "₹" + s


def clean_link(value):
    """Return the link if it looks like a web address, otherwise None."""
    link = (value or "").strip()
    if re.match(r"^https?://[^\s/$.?#][^\s]*$", link, re.I) and len(link) <= 2000:
        return link
    return None


def looks_like_drive(link):
    return bool(re.match(r"^https?://(drive|docs)\.google\.com/", link or "", re.I))


def is_admin():
    return session.get("admin") is True


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin():
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------- status engine

def active_tests():
    return get_db().execute("SELECT * FROM tests WHERE active=1 ORDER BY sort_order, name").fetchall()


def active_flavours():
    return get_db().execute(
        "SELECT * FROM flavours WHERE active=1 ORDER BY CASE category WHEN 'existing' THEN 0 ELSE 1 END, lower(name)"
    ).fetchall()


def compute_status():
    """Work out, for every flavour and test, when it was last done and when it is next due."""
    db = get_db()
    today = date.today()
    lead = int_setting("lead_days", 30)
    flavours = active_flavours()
    tests = active_tests()
    excluded = {(r["flavour_id"], r["test_id"]) for r in db.execute("SELECT * FROM exclusions")}

    latest = {}
    for r in db.execute(
        """SELECT s.id, s.flavour_id, s.sample_date, s.report_link, st.test_id, st.result
           FROM submissions s JOIN submission_tests st ON st.submission_id = s.id
           WHERE s.status='complete' ORDER BY s.sample_date, s.id"""
    ):
        latest[(r["flavour_id"], r["test_id"])] = r

    at_lab = {}
    for r in db.execute(
        """SELECT s.id, s.flavour_id, s.sample_date, st.test_id
           FROM submissions s JOIN submission_tests st ON st.submission_id = s.id
           WHERE s.status='awaiting_report' ORDER BY s.sample_date"""
    ):
        at_lab[(r["flavour_id"], r["test_id"])] = r

    grid = {}
    for f in flavours:
        for t in tests:
            key = (f["id"], t["id"])
            if key in excluded:
                grid[key] = {"state": "na"}
                continue
            rec = latest.get(key)
            cell = {"state": "never", "last": None, "due": None, "days": None,
                    "result": "", "at_lab": None, "submission_id": None, "link": None}
            if rec:
                last = parse_date(rec["sample_date"])
                due = add_months(last, int(t["frequency_months"] or 12))
                days = (due - today).days
                cell.update(last=last, due=due, days=days, result=rec["result"],
                            submission_id=rec["id"], link=rec["report_link"])
                cell["state"] = "overdue" if days < 0 else ("soon" if days <= lead else "ok")
            if key in at_lab:
                cell["at_lab"] = parse_date(at_lab[key]["sample_date"])
            grid[key] = cell
    return flavours, tests, grid


def needs_action(cell):
    if cell["state"] == "na" or cell.get("at_lab"):
        return False
    return cell["state"] in ("never", "overdue", "soon") or cell.get("result") == "Fail"


def build_alerts():
    flavours, tests, grid = compute_status()
    today = date.today()
    groups = []
    for f in flavours:
        items = []
        for t in tests:
            c = grid[(f["id"], t["id"])]
            if not needs_action(c):
                continue
            if c.get("result") == "Fail" and c["state"] != "never":
                kind, text = "fail", f"failed on {nice_date(c['last'])}, needs a retest"
            elif c["state"] == "never":
                kind, text = "never", "no test on record"
            elif c["state"] == "overdue":
                kind, text = "overdue", f"{-c['days']} days late, was due {nice_date(c['due'])}"
            else:
                kind, text = "soon", f"due {nice_date(c['due'])}, in {c['days']} days"
            items.append({"test": t, "kind": kind, "text": text, "price": t["price"]})
        if items:
            urgent = any(i["kind"] != "soon" for i in items)
            cost = sum(i["price"] or 0 for i in items)
            unpriced = sum(1 for i in items if not i["price"])
            groups.append({"flavour": f, "issues": items, "urgent": urgent, "cost": cost, "unpriced": unpriced,
                           "test_ids": ",".join(str(i["test"]["id"]) for i in items)})
    groups.sort(key=lambda gr: (not gr["urgent"], -sum(1 for i in gr["issues"] if i["kind"] != "soon")))

    awaiting = []
    for s in pending_submissions():
        waited = (today - parse_date(s["sample_date"])).days
        awaiting.append({"s": s, "waited": waited})
    return groups, awaiting


def pending_submissions():
    db = get_db()
    rows = db.execute(
        """SELECT s.*, f.name AS flavour_name FROM submissions s JOIN flavours f ON f.id = s.flavour_id
           WHERE s.status='awaiting_report' ORDER BY s.sample_date"""
    ).fetchall()
    out = []
    for r in rows:
        tests = db.execute(
            "SELECT t.name FROM submission_tests st JOIN tests t ON t.id = st.test_id WHERE st.submission_id=? ORDER BY t.sort_order",
            (r["id"],),
        ).fetchall()
        d = dict(r)
        d["tests"] = [t["name"] for t in tests]
        out.append(d)
    return out


@app.context_processor
def inject_globals():
    if request.endpoint in ("static", "team_login", "healthz", None):
        return {"app_name": config.APP_NAME, "is_admin": is_admin(), "team_login": bool(config.TEAM_PASSWORD)}
    try:
        groups, awaiting = build_alerts()
        alert_count = sum(1 for gr in groups if gr["urgent"])
    except DB_ERRORS:
        alert_count, awaiting = 0, []
    return {"app_name": config.APP_NAME, "alert_count": alert_count, "team_login": bool(config.TEAM_PASSWORD),
            "storage_warning": STORAGE_WARNING,
            "pending_count": len(awaiting), "is_admin": is_admin(), "today": date.today()}


# ---------------------------------------------------------------- team login

OPEN_ENDPOINTS = {"team_login", "healthz", "static"}


@app.before_request
def require_team_login():
    if not config.TEAM_PASSWORD or request.endpoint in OPEN_ENDPOINTS:
        return None
    if session.get("member") or session.get("admin"):
        return None
    return redirect(url_for("team_login", next=request.full_path if request.query_string else request.path))


@app.route("/login", methods=["GET", "POST"])
def team_login():
    if not config.TEAM_PASSWORD:
        return redirect(url_for("entry"))
    if request.method == "POST":
        if request.form.get("password") == config.TEAM_PASSWORD:
            session.permanent = True
            session["member"] = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("entry"))
        time.sleep(1)  # slow down password guessing
        flash("That password isn't right.", "error")
    return render_template("team_login.html")


@app.route("/logout")
def team_logout():
    session.clear()
    return redirect(url_for("team_login") if config.TEAM_PASSWORD else url_for("entry"))


@app.route("/healthz")
def healthz():
    # Deliberately doesn't touch the database, so Render's frequent health checks
    # don't keep a free Neon database awake and use up its monthly hours.
    return "ok"


# ---------------------------------------------------------------- pages

@app.route("/")
def home():
    return redirect(url_for("entry"))


@app.route("/entry", methods=["GET", "POST"])
def entry():
    db = get_db()
    tests = active_tests()
    if request.method == "POST":
        f = request.form
        errors = []

        flavour_id = f.get("flavour_id", "")
        if flavour_id == "__new":
            new_name = f.get("new_flavour_name", "").strip()
            if not new_name:
                errors.append("Type a name for the new flavour.")
            elif db.execute("SELECT 1 FROM flavours WHERE lower(name)=lower(?)", (new_name,)).fetchone():
                errors.append(f"A flavour called “{new_name}” already exists. Pick it from the list instead.")
        elif not flavour_id.isdigit() or not db.execute("SELECT 1 FROM flavours WHERE id=?", (flavour_id,)).fetchone():
            errors.append("Choose a flavour.")

        test_ids = [int(x) for x in f.getlist("test_ids") if x.isdigit()]
        valid_ids = {t["id"] for t in tests}
        test_ids = [t for t in test_ids if t in valid_ids]
        if not test_ids:
            errors.append("Choose at least one test.")

        sample_date = f.get("sample_date", "")
        if not parse_date(sample_date):
            errors.append("Enter the date the sample was sent.")

        mode = f.get("report_mode", "now")
        link = clean_link(f.get("report_link"))
        if mode == "now":
            if not f.get("report_link", "").strip():
                errors.append("Paste the Google Drive link to the report, or choose “Report not received yet”.")
            elif not link:
                errors.append("The report link must be a full web address starting with https://")
        else:
            if not f.get("assigned_to", "").strip():
                errors.append("Enter who will add the report link.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("entry.html", active="entry", flavours=active_flavours(), tests=tests,
                                   form=f, selected=test_ids, status_map=status_map_for_js())

        if flavour_id == "__new":
            flavour_id = db.insert("INSERT INTO flavours(name, category, notes, created_at) VALUES (?,?,?,?)",
                                   (new_name, f.get("new_flavour_category", "new"), "", now_iso()))
        flavour_id = int(flavour_id)

        common = dict(flavour_id=flavour_id, sample_date=sample_date, lab_name=f.get("lab_name", "").strip(),
                      created_by=f.get("created_by", "").strip(), remarks=f.get("remarks", "").strip(),
                      created_at=now_iso())
        if mode == "now":
            sid = db.insert(
                """INSERT INTO submissions(flavour_id, sample_date, lab_name, status, report_no, report_date, report_link,
                   remarks, created_by, uploaded_by, uploaded_at, created_at)
                   VALUES (:flavour_id, :sample_date, :lab_name, 'complete', :report_no, :report_date, :report_link,
                   :remarks, :created_by, :created_by, :uploaded_at, :created_at)""",
                dict(common, report_no=f.get("report_no", "").strip(), report_date=f.get("report_date") or None,
                     report_link=link, uploaded_at=now_iso()),
            )
            msg = "Saved with the report link."
        else:
            sid = db.insert(
                """INSERT INTO submissions(flavour_id, sample_date, lab_name, status, assigned_to, assigned_email,
                   remarks, created_by, created_at)
                   VALUES (:flavour_id, :sample_date, :lab_name, 'awaiting_report', :assigned_to, :assigned_email,
                   :remarks, :created_by, :created_at)""",
                dict(common, assigned_to=f.get("assigned_to", "").strip(), assigned_email=f.get("assigned_email", "").strip()),
            )
            msg = f"Saved. {f.get('assigned_to').strip()} has been asked to add the report link."
        for tid in test_ids:
            result = f.get(f"result_{tid}", "") if mode == "now" else ""
            db.execute("INSERT INTO submission_tests(submission_id, test_id, result) VALUES (?,?,?)",
                       (sid, tid, result if result in ("Pass", "Fail") else ""))
        db.commit()
        flash(msg, "success")
        return redirect(url_for("flavour_detail", fid=flavour_id))

    pre_f = request.args.get("flavour", "")
    pre_t = [int(x) for x in request.args.get("tests", "").split(",") if x.isdigit()]
    return render_template("entry.html", active="entry", flavours=active_flavours(), tests=tests,
                           form={"flavour_id": pre_f, "sample_date": date.today().isoformat(),
                                 "lab_name": get_setting("default_lab"), "report_mode": "now"},
                           selected=pre_t, status_map=status_map_for_js())


def status_map_for_js():
    flavours, tests, grid = compute_status()
    out = {}
    for f in flavours:
        m = {}
        for t in tests:
            c = grid[(f["id"], t["id"])]
            if c["state"] == "na":
                m[t["id"]] = {"state": "na", "label": "Not applicable"}
            elif c.get("at_lab"):
                m[t["id"]] = {"state": "lab", "label": "At lab"}
            elif c["state"] == "never":
                m[t["id"]] = {"state": "never", "label": "Never tested"}
            elif c["state"] == "overdue":
                m[t["id"]] = {"state": "overdue", "label": f"Overdue {-c['days']}d"}
            elif c["state"] == "soon":
                m[t["id"]] = {"state": "soon", "label": f"Due in {c['days']}d"}
            else:
                m[t["id"]] = {"state": "ok", "label": "Due " + nice_date(c["due"])}
        out[f["id"]] = m
    return out


@app.route("/pending")
def pending():
    today = date.today()
    rows = pending_submissions()
    for r in rows:
        r["waited"] = (today - parse_date(r["sample_date"])).days
    return render_template("pending.html", active="pending", rows=rows,
                           reminder_days=int_setting("reminder_days", 7))


@app.route("/upload/<int:sid>", methods=["GET", "POST"])
def upload(sid):
    db = get_db()
    s = db.execute("""SELECT s.*, f.name AS flavour_name FROM submissions s JOIN flavours f ON f.id=s.flavour_id
                      WHERE s.id=?""", (sid,)).fetchone()
    if not s:
        abort(404)
    tests = db.execute("""SELECT t.id, t.name, st.result FROM submission_tests st JOIN tests t ON t.id=st.test_id
                          WHERE st.submission_id=? ORDER BY t.sort_order""", (sid,)).fetchall()
    if request.method == "POST":
        link = clean_link(request.form.get("report_link"))
        if not link:
            flash("Paste the full Google Drive link to the report (it starts with https://).", "error")
            return redirect(request.url)
        report_no = request.form.get("report_no", "").strip()
        remarks = request.form.get("remarks", "").strip() or s["remarks"]
        db.execute(
            """UPDATE submissions SET status='complete', report_no=?, report_date=?, report_link=?,
               uploaded_by=?, uploaded_at=?, remarks=? WHERE id=?""",
            (report_no, request.form.get("report_date") or None, link,
             request.form.get("uploaded_by", "").strip(), now_iso(), remarks, sid),
        )
        for t in tests:
            r = request.form.get(f"result_{t['id']}", "")
            db.execute("UPDATE submission_tests SET result=? WHERE submission_id=? AND test_id=?",
                       (r if r in ("Pass", "Fail") else "", sid, t["id"]))
        db.commit()
        flash("Report link saved.", "success")
        return redirect(url_for("flavour_detail", fid=s["flavour_id"]))
    return render_template("upload.html", active="pending", s=s, tests=tests)


@app.route("/dashboard")
def dashboard():
    flavours, tests, grid = compute_status()
    today = date.today()
    lead = int_setting("lead_days", 30)

    rows, fully_ok = [], 0
    overdue_n = soon_n = 0
    for f in flavours:
        cells = [grid[(f["id"], t["id"])] for t in tests]
        applicable = [c for c in cells if c["state"] != "na"]
        in_date = sum(1 for c in applicable if c["state"] in ("ok", "soon") and c.get("result") != "Fail")
        attn = any(needs_action(c) for c in cells)
        for c in applicable:
            if c.get("at_lab"):
                continue
            if c["state"] in ("never", "overdue"):
                overdue_n += 1
            elif c["state"] == "soon":
                soon_n += 1
        if applicable and in_date == len(applicable):
            fully_ok += 1
        rows.append({"f": f, "cells": cells, "in_date": in_date, "applicable": len(applicable), "attn": attn})

    # next 12 months
    start = date(today.year, today.month, 1)
    months = [{"label": "Overdue now", "key": "now", "count": 0, "cost": 0, "detail": defaultdict(list)}]
    for i in range(12):
        d = add_months(start, i)
        months.append({"label": d.strftime("%b %Y"), "key": d.strftime("%Y-%m"), "count": 0, "cost": 0,
                       "detail": defaultdict(list)})
    index = {m["key"]: m for m in months}
    for f in flavours:
        for t in tests:
            c = grid[(f["id"], t["id"])]
            if c["state"] == "na" or c.get("at_lab"):
                continue
            m = index["now"] if c["state"] in ("never", "overdue") else index.get(c["due"].strftime("%Y-%m"))
            if m:
                m["count"] += 1
                m["cost"] += t["price"] or 0
                m["detail"][f["name"]].append(t["name"])
    peak = max((m["count"] for m in months), default=1) or 1

    return render_template("dashboard.html", active="dashboard", tests=tests, rows=rows, months=months, peak=peak,
                           fully_ok=fully_ok, total=len(flavours), overdue_n=overdue_n, soon_n=soon_n, lead=lead,
                           pending_n=len(pending_submissions()))


@app.route("/flavour/<int:fid>", methods=["GET", "POST"])
def flavour_detail(fid):
    db = get_db()
    f = db.execute("SELECT * FROM flavours WHERE id=?", (fid,)).fetchone()
    if not f:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Flavour name can't be empty.", "error")
            return redirect(request.url)
        clash = db.execute("SELECT 1 FROM flavours WHERE lower(name)=lower(?) AND id<>?", (name, fid)).fetchone()
        if clash:
            flash(f"Another flavour is already called “{name}”.", "error")
            return redirect(request.url)
        db.execute("UPDATE flavours SET name=?, category=?, notes=?, active=? WHERE id=?",
                   (name, request.form.get("category", "existing"), request.form.get("notes", "").strip(),
                    0 if request.form.get("archived") else 1, fid))
        db.execute("DELETE FROM exclusions WHERE flavour_id=?", (fid,))
        for tid in request.form.getlist("na_tests"):
            if tid.isdigit():
                db.execute("INSERT INTO exclusions(flavour_id, test_id) VALUES (?,?) ON CONFLICT DO NOTHING", (fid, int(tid)))
        db.commit()
        flash("Flavour updated.", "success")
        return redirect(request.url)

    flavours, tests, grid = compute_status()
    cards = [{"t": t, "c": grid.get((fid, t["id"]), {"state": "na"})} for t in tests] if f["active"] else []
    history = []
    for s in db.execute("SELECT * FROM submissions WHERE flavour_id=? ORDER BY sample_date DESC, id DESC", (fid,)):
        st = db.execute("""SELECT t.name, st.result FROM submission_tests st JOIN tests t ON t.id=st.test_id
                           WHERE st.submission_id=? ORDER BY t.sort_order""", (s["id"],)).fetchall()
        history.append({"s": s, "tests": st})
    excluded = {r["test_id"] for r in db.execute("SELECT test_id FROM exclusions WHERE flavour_id=?", (fid,))}
    all_tests = db.execute("SELECT * FROM tests WHERE active=1 ORDER BY sort_order").fetchall()
    return render_template("flavour.html", active="dashboard", f=f, cards=cards, history=history,
                           all_tests=all_tests, excluded=excluded)


@app.route("/submission/<int:sid>/delete", methods=["POST"])
@admin_required
def delete_submission(sid):
    db = get_db()
    s = db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    if not s:
        abort(404)
    db.execute("DELETE FROM submissions WHERE id=?", (sid,))
    db.commit()
    flash("Entry deleted. The report in Google Drive was not touched.", "success")
    return redirect(url_for("flavour_detail", fid=s["flavour_id"]))


@app.route("/alerts")
def alerts():
    groups, awaiting = build_alerts()
    return render_template("alerts.html", active="alerts", groups=groups, awaiting=awaiting,
                           reminder_days=int_setting("reminder_days", 7), lead=int_setting("lead_days", 30))


# ---------------------------------------------------------------- back end

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == config.ADMIN_PASSWORD:
            session.permanent = True
            session["admin"] = True
            session["member"] = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("admin_tests"))
        time.sleep(1)  # slow down password guessing
        flash("That password isn't right.", "error")
    return render_template("login.html", active="admin")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Logged out of the back end.", "success")
    return redirect(url_for("entry"))


@app.route("/admin/tests", methods=["GET", "POST"])
@admin_required
def admin_tests():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form.get("new_name", "").strip()
            if not name:
                flash("Give the new test a name.", "error")
            elif db.execute("SELECT 1 FROM tests WHERE lower(name)=lower(?)", (name,)).fetchone():
                flash(f"A test called “{name}” already exists.", "error")
            else:
                db.execute("INSERT INTO tests(name, covers, frequency_months, price, active, sort_order) VALUES (?,?,?,?,1,?)",
                           (name, request.form.get("new_covers", "").strip(),
                            max(1, int(request.form.get("new_freq") or 12)), _price(request.form.get("new_price")),
                            (db.execute("SELECT COALESCE(MAX(sort_order),0)+10 AS n FROM tests").fetchone()["n"])))
                db.commit()
                flash(f"Added “{name}”.", "success")
        elif action == "save":
            for t in db.execute("SELECT id FROM tests").fetchall():
                tid = t["id"]
                name = request.form.get(f"name_{tid}", "").strip()
                if not name:
                    continue
                try:
                    freq = max(1, min(60, int(request.form.get(f"freq_{tid}") or 12)))
                except ValueError:
                    freq = 12
                if db.execute("SELECT 1 FROM tests WHERE lower(name)=lower(?) AND id<>?", (name, tid)).fetchone():
                    flash(f"Two tests can't share the name “{name}”. That name wasn't changed.", "error")
                    name = db.execute("SELECT name FROM tests WHERE id=?", (tid,)).fetchone()["name"]
                try:
                    order = int(request.form.get(f"order_{tid}") or 100)
                except ValueError:
                    order = 100
                db.execute("UPDATE tests SET name=?, covers=?, frequency_months=?, price=?, active=?, sort_order=? WHERE id=?",
                           (name, request.form.get(f"covers_{tid}", "").strip(), freq,
                            _price(request.form.get(f"price_{tid}")),
                            1 if request.form.get(f"active_{tid}") else 0, order, tid))
            lead = request.form.get("lead_days", "")
            if lead.isdigit():
                set_setting("lead_days", max(1, min(365, int(lead))))
            db.commit()
            flash("Test schedule saved. Due dates have been recalculated.", "success")
        elif action == "all6" or action == "all12":
            months = 6 if action == "all6" else 12
            db.execute("UPDATE tests SET frequency_months=? WHERE active=1", (months,))
            db.commit()
            flash(f"Every active test now repeats every {months} months.", "success")
        return redirect(url_for("admin_tests"))
    tests = db.execute("SELECT * FROM tests ORDER BY sort_order, name").fetchall()
    return render_template("admin_tests.html", active="admin_tests", tests=tests,
                           lead=int_setting("lead_days", 30), default_pw=config.ADMIN_PASSWORD == "changeme")


def _price(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        if request.form.get("action") == "test_email":
            to = [e.strip() for e in get_setting("notify_emails").split(",") if e.strip()]
            if not smtp_ready():
                flash("Fill in the SMTP server and “Send from” address, save, then try again.", "error")
            elif not to:
                flash("Add at least one address under “Send the daily summary to” first.", "error")
            else:
                try:
                    send_email(to, f"{config.APP_NAME}: test email",
                               "Email alerts are working. You'll get a daily summary of tests that need aligning.")
                    flash(f"Test email sent to {', '.join(to)}.", "success")
                except Exception as e:  # noqa: BLE001
                    flash(f"Couldn't send email: {e}", "error")
            return redirect(url_for("admin_settings"))
        keys = ["reminder_days", "default_lab", "notify_emails", "digest_hour", "smtp_host", "smtp_port",
                "smtp_user", "smtp_from"]
        for k in keys:
            set_setting(k, request.form.get(k, "").strip())
        if request.form.get("smtp_password"):
            set_setting("smtp_password", request.form.get("smtp_password"))
        set_setting("smtp_tls", "1" if request.form.get("smtp_tls") else "0")
        get_db().commit()
        flash("Settings saved.", "success")
        return redirect(url_for("admin_settings"))
    s = {k: get_setting(k) for k in DEFAULT_SETTINGS}
    return render_template("admin_settings.html", active="admin_settings", s=s,
                           smtp_ready=smtp_ready(), default_pw=config.ADMIN_PASSWORD == "changeme",
                           on_render=config.ON_RENDER)


@app.route("/admin/backup")
@admin_required
def admin_backup():
    """Download a zip with an Excel-friendly list of every entry plus a full copy of the data."""
    tmpdir = tempfile.mkdtemp()
    src = connect()
    agg = "string_agg" if USE_PG else "GROUP_CONCAT"

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Flavour", "Sample sent", "Tests and results", "Lab", "Report no.", "Report date",
                "Report link", "Status", "Responsible", "Remarks"])
    for r in src.execute(
        f"""SELECT s.*, f.name AS flavour_name,
                  (SELECT {agg}(t.name || CASE WHEN st.result <> '' THEN ' (' || st.result || ')' ELSE '' END, '; ')
                   FROM submission_tests st JOIN tests t ON t.id = st.test_id WHERE st.submission_id = s.id) AS tests
           FROM submissions s JOIN flavours f ON f.id = s.flavour_id
           ORDER BY lower(f.name), s.sample_date DESC"""
    ):
        w.writerow([r["flavour_name"], r["sample_date"], r["tests"] or "", r["lab_name"], r["report_no"],
                    r["report_date"] or "", r["report_link"] or "",
                    "Awaiting report" if r["status"] == "awaiting_report" else "Complete",
                    r["assigned_to"], r["remarks"]])

    # Full copy of every table (settings minus the email password), for restoring or moving the data.
    dump = {}
    for table in ("flavours", "tests", "submissions", "submission_tests", "exclusions", "settings"):
        rows = [dict(r) for r in src.execute(f"SELECT * FROM {table}")]
        if table == "settings":
            rows = [r for r in rows if r["key"] != "smtp_password"]
        dump[table] = rows
    src.close()

    zip_path = os.path.join(tmpdir, "backup.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("all-test-entries.csv", "\ufeff" + out.getvalue())  # BOM so Excel reads names correctly
        z.writestr("all-data.json", json.dumps(dump, indent=1, ensure_ascii=False, default=str))

    @after_this_request
    def _cleanup(response):
        response.call_on_close(lambda: __import__("shutil").rmtree(tmpdir, ignore_errors=True))
        return response

    return send_file(zip_path, as_attachment=True,
                     download_name=f"fg-tracker-backup-{date.today().isoformat()}.zip")


# ---------------------------------------------------------------- email alerts

def smtp_ready():
    return bool(get_setting("smtp_host") and (get_setting("smtp_from") or get_setting("smtp_user")))


def send_email(to, subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = get_setting("smtp_from") or get_setting("smtp_user")
    msg["To"] = ", ".join(to)
    msg.set_content(body)
    host, port = get_setting("smtp_host"), int(get_setting("smtp_port") or 587)
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        if get_setting("smtp_tls") == "1":
            server.starttls()
    with server:
        if get_setting("smtp_user"):
            server.login(get_setting("smtp_user"), get_setting("smtp_password"))
        server.send_message(msg)


def run_notifications():
    """Called every 15 minutes: daily summary + reminders for missing reports."""
    if not smtp_ready():
        return
    db = get_db()
    now = datetime.now()
    today_s = date.today().isoformat()

    if now.hour >= int_setting("digest_hour", 9) and get_setting("last_digest") != today_s:
        to = [e.strip() for e in get_setting("notify_emails").split(",") if e.strip()]
        groups, awaiting = build_alerts()
        if to and (groups or awaiting):
            lines = [f"Testing summary for {nice_date(date.today())}", ""]
            urgent = [gr for gr in groups if gr["urgent"]]
            soon = [gr for gr in groups if not gr["urgent"]]
            if urgent:
                lines.append("ALIGN A SAMPLE NOW")
                for gr in urgent:
                    lines.append(f"- {gr['flavour']['name']}")
                    lines += [f"    {i['test']['name']}: {i['text']}" for i in gr["issues"]]
                lines.append("")
            if soon:
                lines.append(f"DUE IN THE NEXT {int_setting('lead_days', 30)} DAYS")
                for gr in soon:
                    lines.append(f"- {gr['flavour']['name']}: " + ", ".join(f"{i['test']['name']} ({i['text']})" for i in gr["issues"]))
                lines.append("")
            if awaiting:
                lines.append("REPORT LINKS STILL TO ADD")
                for a in awaiting:
                    who = a["s"]["assigned_to"] or "unassigned"
                    lines.append(f"- {a['s']['flavour_name']}: {', '.join(a['s']['tests'])} (sent {nice_date(a['s']['sample_date'])}, {who})")
                lines.append("")
            lines.append(f"Open the tracker: {config.APP_URL}/alerts")
            send_email(to, f"{config.APP_NAME}: {len(urgent)} flavours need testing", "\n".join(lines))
        set_setting("last_digest", today_s)
        db.commit()

    wait = int_setting("reminder_days", 7)
    for s in pending_submissions():
        if not s["assigned_email"] or s["last_reminded"] == today_s:
            continue
        if (date.today() - parse_date(s["sample_date"])).days < wait:
            continue
        body = (f"Hi {s['assigned_to'] or 'there'},\n\n"
                f"The lab report for {s['flavour_name']} ({', '.join(s['tests'])}), sample sent on "
                f"{nice_date(s['sample_date'])}, hasn't been added yet.\n\n"
                f"Paste the Google Drive link here: {config.APP_URL}/upload/{s['id']}\n")
        send_email([s["assigned_email"]], f"Please add the {s['flavour_name']} lab report link", body)
        db.execute("UPDATE submissions SET last_reminded=? WHERE id=?", (today_s, s["id"]))
        db.commit()


def notifier_loop():
    while True:
        try:
            with app.app_context():
                run_notifications()
        except Exception:  # noqa: BLE001
            app.logger.exception("Email notification run failed")
        time.sleep(900)


init_db()

if __name__ == "__main__":
    threading.Thread(target=notifier_loop, daemon=True).start()
    print(f"\n  {config.APP_NAME} is running.")
    if config.ON_RENDER:
        print(f"  Live at {config.APP_URL}")
    else:
        print(f"  Open http://localhost:{config.PORT} on this computer,")
        print(f"  or http://<this computer's IP>:{config.PORT} from others on the network.")
    if config.ON_RENDER and not config.TEAM_PASSWORD:
        print("  WARNING: FGT_TEAM_PASSWORD is not set, so anyone with the link can open the app.")
    print("  Database: " + ("Postgres (DATABASE_URL)" if USE_PG else DB_PATH))
    if STORAGE_WARNING:
        print("  WARNING: " + STORAGE_WARNING)
    print()
    try:
        from waitress import serve
        serve(app, host=config.HOST, port=config.PORT)
    except ImportError:
        app.run(host=config.HOST, port=config.PORT, debug=False, use_reloader=False)
