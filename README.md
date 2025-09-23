## Deployment
- Create free PostgreSQL on Render and set `DATABASE_URL`.
- Use external free cron (e.g., cron-job.org) to ping `/health` every 10 min (`*/10 * * * *`).
- Optional: Set up DB backup with Discord/Google Drive webhook; use `/backup` command.
- Troubleshoot: Check logs for "Webhook set", DB errors, or external cron failures.

## Backups
- Use `/backup` in Telegram as admin to trigger manual backup.
- For automated backups, set external cron to GET `https://yourbot.onrender.com/trigger_backup` daily (e.g., `0 0 * * *`).
- Configure `GOOGLE_DRIVE_CREDENTIALS_JSON` (base64-encoded service account JSON) or `DISCORD_WEBHOOK_URL` in env vars.
- To set up Google Drive:
  1. Go to `console.cloud.google.com`, create project
  2. Enable Drive API
  3. Create service account, download JSON key
  4. Base64 encode JSON and set as env var
  5. Share a Drive folder with the service account email
# AVAP Support Telegram Bot

This is a comprehensive Telegram bot for AVAP, designed to manage student interactions, submissions, and administrative tasks. The bot is built with `python-telegram-bot`, `FastAPI`, and `SQLite`. It supports webhook-based deployment for production (e.g., on Render) and polling for local development.

## Features

The bot provides a rich set of features for students and admins:

### Student Features (DM-Only)
1.  **Verification**: Students can verify themselves by providing their name, email, and phone number, which are checked against a pre-registered list.
2.  **Assignment Submission**: Verified students can submit assignments for modules 1-12 as images or videos.
3.  **Share Small Win**: Verified students can share their small wins as text, images, or videos.
4.  **Ask a Question**: Verified students can ask questions directly to the support team.
5.  **Check Status**: Verified students can check their submission status, scores, and win count.

### Admin Features
1.  **Add Student**: Admins can pre-register students to the verification list.
2.  **Manual Verification**: Admins can manually verify a student using their email.
3.  **Remove Student**: Admins can remove a student's verified status.
4.  **Grading**: Admins can grade submissions directly from the assignments group using an interactive inline flow.
5.  **Answering Questions**: Admins can answer student questions from the questions group.

### Group Features
-   In the support group, verified users can use the `/ask <question>` command to ask a question. All other commands are disabled for non-admins in groups.

### Scheduled Tasks
-   A weekly reminder is sent to all verified students on Sundays.

## Setup

Follow these steps to set up the project locally.

### 1. Clone the Repository
```bash
git clone <repository_url>
cd <repository_directory>
```

### 2. Create a Virtual Environment
It is recommended to use a virtual environment to manage dependencies.
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the root of the project by copying the example file:
```bash
cp .env.example .env
```
Now, open the `.env` file and fill in the required values. You will need to get a `TELEGRAM_TOKEN` from BotFather on Telegram. For local testing, you only need to set `TELEGRAM_TOKEN`, `ADMIN_ID`, and the group IDs you want to use.

## Local Testing (Polling Mode)

For local development and testing, you can run the bot in polling mode. This mode does not require a public URL or webhook setup.

Run the following command in your terminal:
```bash
python bot.py poll
```
The bot will start polling for updates from Telegram. You can now interact with it.

## Deployment (Render)

This bot is designed to be deployed as a Web Service on Render.

### 1. Create a New Web Service
-   Go to your Render dashboard and create a new "Web Service".
-   Connect your GitHub repository.

### 2. Configure the Service
-   **Name**: Give your service a name (e.g., `avap-support-bot`).
-   **Region**: Choose a region close to you.
-   **Branch**: Select the branch to deploy (e.g., `main`).
-   **Build Command**: `pip install -r requirements.txt`
-   **Start Command**: `python bot.py`

### 3. Add Environment Variables
-   In the "Environment" section, add all the environment variables from your `.env` file.
-   **Important**: For the `WEBHOOK_URL` variable, use the URL of your Render service (e.g., `https://your-app-name.onrender.com`). Render provides this URL in the service dashboard.

### 4. Deploy
-   Click "Create Web Service". Render will build and deploy your bot.
-   The bot will automatically set the webhook to your Render service URL on startup.
-   You can check the logs to ensure everything is running correctly. The health check endpoint at `/health` should return a 200 OK status.

### Important: Persisting the Database on Render
By default, Render's free Web Services have an ephemeral filesystem, which means the SQLite database file (`avap_bot.db`) will be deleted every time the bot restarts or is re-deployed. To prevent this and keep your data, you must attach a **Render Free Disk**.

1.  **Create a Disk**: In your Render dashboard, go to the "Disks" section and create a new disk.
    -   **Name**: `avap-bot-data` (or any name you prefer).
    -   **Mount Path**: `/data`
    -   **Size**: 1 GB is sufficient.
2.  **Attach the Disk**: Go to your Web Service's "Settings" and find the "Disks" section. Attach the disk you just created.
3.  **Update Environment Variable**: In your Web Service's "Environment" settings, update the `DB_PATH` variable to point to the disk's mount path:
    -   `DB_PATH`: `/data/avap_bot.db`

After making these changes, re-deploy your service. The database will now be stored on the persistent disk and will not be lost on restarts.
