# FG Testing Tracker

A small web app for logging finished-goods lab tests for each flavour, keeping the Google Drive link to each lab report, and warning you before any test falls due.

It runs on one computer in your office, and everyone else on the same network opens it in their browser. To host it online instead, so it works from anywhere, follow **DEPLOY_RENDER.md**.

## What's inside

**New test entry** is the home page. It takes four steps: pick a flavour (or add a new one), choose the tests from the drop-down, enter the sample details, then either paste the Google Drive link to the lab report or name the person who will add it when the report arrives.

**Reports pending** lists every sample still waiting for its report link, how long it has waited, and who is responsible.

**Dashboard** shows every flavour against every test, colour-coded by status. It also has a 12-month forecast of tests falling due with estimated lab cost, and a page per flavour with its full history and a link to open each report in Google Drive.

**Alerts** lists the flavours that need a sample aligned with the lab. One click opens a new entry with the due tests already ticked.

**Back end** is password protected. The **Test schedule** page sets how often each test repeats, its price, and how many days of warning you get. **Settings** covers reminders and email alerts.

## 1. Install Python (one time only)

Download Python 3.10 or newer from https://www.python.org/downloads/

On Windows, tick **"Add python.exe to PATH"** on the first screen of the installer.

## 2. Set your password

Open `config.py` in Notepad and change these two lines:

```python
ADMIN_PASSWORD = os.environ.get("FGT_ADMIN_PASSWORD", "changeme")
SECRET_KEY = os.environ.get("FGT_SECRET_KEY", "replace-this-with-a-long-random-string")
```

Replace `changeme` with your own password. Replace the secret key with any long, random text; nobody needs to remember it.

To make everyone sign in before using the app, also set a team password:

```python
TEAM_PASSWORD = os.environ.get("FGT_TEAM_PASSWORD", "your-team-password")
```

## 3. Start the app

- **Windows:** double-click `run_windows.bat`
- **Mac / Linux:** open Terminal in this folder and run `./run_mac_linux.sh`

The first start takes a minute while it installs what it needs. When you see "FG Testing Tracker is running", open http://localhost:5000 in your browser.

Keep that window open. Closing it stops the app.

## 4. Open it from other computers

1. Find this computer's IP address. On Windows, open Command Prompt, type `ipconfig`, and look for the **IPv4 Address**, for example `192.168.1.25`.
2. Other people open `http://192.168.1.25:5000` in their browser.
3. If Windows asks whether to allow Python through the firewall, choose **Private networks** and click Allow.
4. Put that same address in `APP_URL` in `config.py`, so links inside reminder emails work.

It is best to run the app on a computer that stays on during working hours, with a fixed IP address. Your IT person can reserve one on the router.

## 5. How report links work

The app doesn't store report files. Keep the reports in Google Drive as you do now, and paste each one's link into the app.

To copy a link in Google Drive: right-click the report, choose **Share**, then **Copy link**. Under **General access**, choose your company (or "Anyone with the link") so your team can open it. A **Test link** button appears next to the box once you paste, so you can check it opens.

Any web link that starts with `https://` is accepted. If it isn't a Google Drive link, the app shows a warning but still saves it.

## 6. Turn on email alerts (optional)

Without email, alerts still show inside the app: the red banner, the Alerts page and the sidebar counts. With email set up:

- The addresses you list get a **daily summary** of tests to align and reports still missing.
- Anyone named as responsible for a report (with an email) gets a **daily reminder** once its link has been missing longer than the reminder period.

To set it up, go to **Settings** in the back end.

**Gmail or Google Workspace:**
- **SMTP server:** `smtp.gmail.com`
- **Port:** `587`, with **Use TLS** ticked
- **Username:** your full email address
- **Password:** an **app password**, not your normal password. Create one at https://myaccount.google.com/apppasswords (2-step verification must be on).
- **Send from:** the same email address

**Microsoft 365 / Outlook:** server `smtp.office365.com`, port `587`, TLS ticked.

Save, then click **Send test email** to check it works. Emails are checked every 15 minutes while the app is running.

## 7. Start automatically when the computer turns on (Windows)

1. Press `Win + R`, type `shell:startup`, and press Enter.
2. Right-click in that folder, choose **New > Shortcut**, and browse to `run_windows.bat`.

The app will now start whenever someone logs in to that computer.

## Backups

All the app's data (flavours, tests, dates, results, report links and settings) lives in one file, `data.db`. The reports themselves stay in Google Drive.

Once a week, go to **Settings** in the back end and click **Download backup (.zip)**. It contains `data.db` plus `all-test-entries.csv`, a spreadsheet of every entry with its report link that opens in Excel.

## Starting fresh

The first run pre-loads your 21 flavours and the test dates from the Google Sheet. Imported entries are marked "Imported from Google Sheet. No report link."

To start with an empty tracker instead:
1. Set `IMPORT_SHEET_DATA = False` in `config.py`.
2. Delete `data.db`.
3. Start the app again.

## Assumptions in the imported data

- The sheet's "Chemical" column is recorded as both **Physico-chemical** and **Heavy metals**.
- Dates like `6/4/2026` are read as day/month (6 April 2026).
- Aflatoxins & OTA and Illegal dyes had no dates in the sheet, so they show as never tested.
- Achaari Atyachaari and Bloody Peri are marked as sent to the lab on 24 Sep 2026 for all six FSSAI tests.
- Chicken 65, Rogan Josh and Fennel - Gravy have nutrition reports marked as pending (no link yet).
- Every test repeats every **12 months** by default. FSSAI's rule is six-monthly testing; change it in **Test schedule** with one click.

Fix any of these from the flavour's page, or delete an entry there once logged in to the back end.

## Files

| File | What it is |
|---|---|
| `app.py` | The application |
| `config.py` | Passwords, database location, network settings |
| `seed_data.py` | Default tests and the one-time import from your sheet |
| `templates/`, `static/` | Page layouts, styling and browser code |
| `run_windows.bat`, `run_mac_linux.sh` | Start the app on your own computer |
| `render.yaml`, `DEPLOY_RENDER.md` | Host the app online on Render |
