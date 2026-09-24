# Hosting the FG Testing Tracker on Render

Render runs the app online so your team can open it from anywhere, on any device, at an address like `https://fg-testing-tracker.onrender.com`. Everyone signs in with a team password.

Setup takes about 20 minutes. You need a GitHub account (free), a Render account, and a debit or credit card.

## What it costs

| Item | Plan | Approx. cost |
|---|---|---|
| Web service | `0.5c-512mb` (formerly "Starter") | $7 per month |
| Persistent disk | 1 GB | $0.25 per month |

Check https://render.com/pricing for current rates.

**Why not the free plan?** The lab reports stay in Google Drive, but the app's own records (flavours, test dates, results and the report links) are kept in a small database file. Free Render services can't attach a persistent disk, so that file would be wiped every time Render restarts the app. Free services also can't send email, so reminders would never go out.

## Step 1: Put the app on GitHub

Render deploys from a GitHub repository.

1. Sign up or sign in at https://github.com
2. Click **+** (top right) and choose **New repository**.
3. Name it `fg-testing-tracker`, choose **Private**, and leave every other box unticked. Click **Create repository**.
4. On the next page, click the link **uploading an existing file**.
5. Unzip `fg-testing-tracker.zip` on your computer and open the `fg-tracker` folder.
6. Select **everything inside** that folder and drag it into the browser window: `app.py`, `config.py`, `render.yaml`, `requirements.txt`, the `templates` and `static` folders, and the rest.

   Do **not** upload `.venv` or `data.db` if they exist. They are created when you run the app on your own computer and don't belong on GitHub.
7. Click **Commit changes**.

Check that `render.yaml` and `app.py` appear at the top level of the repository, not inside a sub-folder.

## Step 2: Create the app on Render

1. Go to https://dashboard.render.com and sign up **with your GitHub account**.
2. Click **New** (top right), then **Blueprint**.
3. Connect GitHub if asked, allow Render to see the `fg-testing-tracker` repository, and select it.
4. Render reads `render.yaml` and shows one web service, `fg-testing-tracker`, with a 1 GB disk.
5. Enter the two passwords Render asks for:
   - **FGT_TEAM_PASSWORD**: everyone on the team uses this to sign in.
   - **FGT_ADMIN_PASSWORD**: opens Test schedule and Settings. Keep this one to QA heads.

   Use long passwords that are different from each other.
6. Add your card if Render asks, then click **Deploy Blueprint** (or **Apply**).
7. Open the service and watch **Logs**. After two to four minutes you'll see:
   ```
   FG Testing Tracker is running.
   Live at https://fg-testing-tracker.onrender.com
   ```

Your address is shown at the top of the service page. It may have extra letters if the name was taken.

The app is created in Render's **Singapore** region, the closest to India. To choose another region, change `region:` in `render.yaml` before Step 2; it can't be changed afterwards.

## Step 3: Check it works

1. Open your app's address and sign in with the team password.
2. The dashboard shows your 21 flavours with the dates imported from the Google Sheet.
3. On **New test entry**, log a test with a real Google Drive report link. Use **Test link** to check it opens, then save.
4. Open the flavour's page and click **Open report** to confirm the link works.
5. Open **Test schedule**, enter the admin password, and set the repeat intervals you want.
6. Share the address and the team password with your team. On phones, "Add to Home Screen" makes it open like an app.

## Step 4: Turn on email alerts

In **Settings** (back end), fill in the email section exactly as described in `README.md`, section 6. For Gmail, use `smtp.gmail.com`, port `587`, TLS ticked, and a Gmail **app password**.

Then click **Send test email**.

Paid Render services can send on ports 587 and 465. Port 25 is blocked on Render, so don't use it.

## Report links

The app saves only the link to each report; the files stay in Google Drive. For a link to open for your team, its sharing must allow them. In Google Drive, right-click the report, choose **Share**, and under **General access** choose your company or "Anyone with the link".

A tidy way to keep this in order is one shared Drive folder, e.g. `FSSAI Test Reports`, shared with the team once. Every report placed inside it is then viewable by everyone.

## Backups

- Render takes an automatic **snapshot** of the disk every day and keeps it for at least seven days. Restore one from the service's **Disk** page.
- Once a week, go to **Settings** and click **Download backup (.zip)**. It contains the database and `all-test-entries.csv`, a spreadsheet of every entry with its report link. Save it to Google Drive.

## Changing things later

- **Passwords:** open the service in Render, go to **Environment**, edit `FGT_TEAM_PASSWORD` or `FGT_ADMIN_PASSWORD`, and save. Render restarts the app with the new value.
- **App updates:** upload changed files to the GitHub repository. Render redeploys automatically within a few minutes. Your data stays safe on the disk. The app is unavailable for a few seconds during each redeploy.
- **Your own domain** (e.g. `tests.yourbrand.in`): add it under the service's **Settings > Custom Domains** and follow Render's DNS instructions.

## If something goes wrong

**Data disappeared after a redeploy.** Check **Environment**: `FGT_DATA_DIR` must be `/var/data`. Then check **Disk**: the mount path must also be `/var/data`.

**The build fails.** Make sure `render.yaml` and `requirements.txt` are at the top level of the GitHub repository.

**Anyone can open the app without a password.** `FGT_TEAM_PASSWORD` is empty. Set it under **Environment**.

**A teammate sees "You need access" when opening a report.** The link works, but the file isn't shared with them. Change its sharing in Google Drive as described under Report links.

**Emails don't arrive.** Open **Logs** and look for "Email notification run failed". The usual causes are using your normal Gmail password instead of an app password, or a port other than 587 or 465.

**The app says it can't be reached.** Open the service in Render and check its status. If a deploy failed, the **Logs** page shows why.
