# Hosting the FG Testing Tracker on Render (free)

This setup runs the app on Render's **free** plan and keeps your data in a **free Neon database**, so nothing is lost when Render restarts the app. Neither needs a disk.

## What the free setup means

- **The app sleeps.** After 15 minutes with no visitors, the app goes to sleep. The next person to open it waits about a minute while it wakes up. After that it is fast again.
- **No email alerts.** Render's free plan blocks outgoing email. Alerts still show inside the app: the red banner, the Alerts page and the sidebar counts.
- **Neon's free limits are plenty for this app.** You get 0.5 GB of storage (enough for tens of thousands of test entries) and 100 compute hours a month. The database also sleeps when unused, which saves those hours.

To get email alerts and stop the sleeping later, change the Render instance type to **Starter** (about $7/month). Keep the Neon database; nothing else changes.

## If you already created the Web Service (your case)

Your deploy failed because `FGT_DATA_DIR` points to `/var/data`, which only exists when a paid disk is attached. The steps below fix it.

### Step 1: Create the free Neon database

1. Go to https://neon.com and sign up. Your Google account is fine, and no card is needed.
2. Create a project:
   - **Name:** `fg-testing-tracker`
   - **Postgres version:** leave the default
   - **Region:** **AWS Asia Pacific (Singapore)**. This should match your Render region; if your Render service is in another region, pick the closest Neon region to it.
3. On the project dashboard, click **Connect**. Copy the **connection string**. It looks like
   `postgresql://neondb_owner:abc123@ep-cool-name-123456-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`

   Leave "Connection pooling" on, which is the default. Treat this string like a password.

### Step 2: Upload the new files to GitHub

1. Unzip `fg-testing-tracker.zip` and open the `fg-tracker` folder.
2. In your GitHub repository, click **Add file**, then **Upload files**.
3. Select **everything inside** the `fg-tracker` folder, drag it in, and click **Commit changes**. Files with the same name are replaced automatically.

The files that changed are `app.py`, `config.py`, `seed_data.py`, `requirements.txt`, `render.yaml`, `templates/base.html` and `templates/admin_settings.html`. Uploading everything is simplest and safe.

### Step 3: Fix the environment variables on Render

1. Open your service on https://dashboard.render.com and go to **Environment**.
2. **Delete** `FGT_DATA_DIR`. This is what caused the crash.
3. **Add** a variable:
   - **Key:** `DATABASE_URL`
   - **Value:** the Neon connection string from Step 1
4. Keep `FGT_TEAM_PASSWORD`, `FGT_ADMIN_PASSWORD` and `FGT_SECRET_KEY` as they are. If `FGT_SECRET_KEY` is missing, add it with any long random text.
5. Click **Save, rebuild, and deploy**. If you only see **Save Changes**, click it, then use **Manual Deploy**, then **Deploy latest commit**.

### Step 4: Check it worked

1. Open **Logs**. After two to four minutes you should see:
   ```
   FG Testing Tracker is running.
   Database: Postgres (DATABASE_URL)
   ```
2. Open your app's address (shown at the top of the service page) and sign in with the team password.
3. The dashboard should show your 21 flavours.
4. Add a test entry, then restart the service (**Manual Deploy**, then **Restart service**). If the entry is still there afterwards, your data is being saved permanently.

## Creating the Web Service from scratch (for reference)

If you ever need to set it up again: create the Neon database first (Step 1), then in Render click **New**, then **Web Service**, pick the repository, and enter:

| Setting | Value |
|---|---|
| Language | Python 3 |
| Branch | `main` |
| Region | Singapore |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python app.py` |
| Instance Type | Free |
| Health Check Path (under Advanced) | `/healthz` |

Under **Environment Variables**, add:

| Key | Value |
|---|---|
| `DATABASE_URL` | the Neon connection string |
| `FGT_TEAM_PASSWORD` | the password your team signs in with |
| `FGT_ADMIN_PASSWORD` | the password for Test schedule and Settings |
| `FGT_SECRET_KEY` | any long random text |

Don't add `FGT_DATA_DIR`, and don't add a disk.

## Report links

The app saves only the link to each report; the files stay in Google Drive. For a link to open for your team, its sharing must allow them. In Google Drive, right-click the report, choose **Share**, and under **General access** choose your company or "Anyone with the link".

The simplest approach is one shared Drive folder, e.g. `FSSAI Test Reports`, shared with the team once. Every report placed inside it is then viewable by everyone.

## Backups

- Neon's free plan can restore the database to any moment in the **last 6 hours**, from the Neon dashboard.
- Once a week, go to **Settings** in the app and click **Download backup (.zip)**. It contains `all-test-entries.csv` (every entry with its report link, which opens in Excel) and `all-data.json` (a complete copy of the data). Save it to Google Drive.

## If something goes wrong

**A red banner says "Data is not being saved permanently".** `DATABASE_URL` is missing or empty. Add it under **Environment** (Step 3).

**The logs say "password authentication failed" or "could not connect".** The connection string was copied incompletely. Copy it again from Neon's **Connect** button and replace the `DATABASE_URL` value.

**The app takes about a minute to open.** It was asleep, which is normal on the free plan. Starter ($7/month) keeps it awake.

**A teammate sees "You need access" when opening a report.** The link works, but the file isn't shared with them. Change its sharing in Google Drive, as described under Report links.

**The database stopped responding near the end of the month.** The free Neon compute hours ran out. It resumes at the start of the next month, or you can upgrade in Neon. This is unlikely for a team this size.
