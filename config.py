"""
Settings for the FG Testing Tracker.

Running on your own computer: edit the values below, then restart the app.
Running on Render: set these as Environment Variables in the Render dashboard
(the render.yaml file sets most of them up for you).
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ON_RENDER = bool(os.environ.get("RENDER"))

# Name shown in the sidebar and in email subjects.
APP_NAME = os.environ.get("FGT_APP_NAME", "FG Testing Tracker")

# Online database (Postgres). On Render's free plan, set DATABASE_URL to the
# connection string of a free Neon database so your data is kept permanently.
# Leave it unset on your own computer; the app then uses a local SQLite file.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Folder for the local SQLite file (used only when DATABASE_URL is not set).
# Lab reports themselves stay in Google Drive; the app only stores their links.
DATA_DIR = os.environ.get("FGT_DATA_DIR", BASE_DIR)

# SQLite database file (created automatically on first run).
DB_PATH = os.environ.get("FGT_DB_PATH", os.path.join(DATA_DIR, "data.db"))

# Password everyone uses to open the app. Leave empty on a private office
# network if you don't want a login; ALWAYS set it when hosted online.
TEAM_PASSWORD = os.environ.get("FGT_TEAM_PASSWORD", "")

# Password for the back-end pages (Test schedule, Settings). CHANGE THIS.
ADMIN_PASSWORD = os.environ.get("FGT_ADMIN_PASSWORD", "changeme")

# Used to sign login cookies. Replace with any long random text.
SECRET_KEY = os.environ.get("FGT_SECRET_KEY", "replace-this-with-a-long-random-string")

# Send login cookies over HTTPS only. Turn on when hosted online.
SECURE_COOKIES = os.environ.get("FGT_SECURE_COOKIES", "1" if ON_RENDER else "0") == "1"

# Network settings. Render tells the app which port to use via PORT.
HOST = os.environ.get("FGT_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("FGT_PORT") or 5000)

# The address people use to open the app; used for links inside emails.
APP_URL = (os.environ.get("FGT_APP_URL") or os.environ.get("RENDER_EXTERNAL_URL")
           or "http://localhost:5000").rstrip("/")

# On the very first run, pre-load the flavours and test dates from your
# Google Sheet so the dashboard isn't empty. Set to False to start blank.
IMPORT_SHEET_DATA = os.environ.get("FGT_IMPORT_SHEET_DATA", "1") == "1"
