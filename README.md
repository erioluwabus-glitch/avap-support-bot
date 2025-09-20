# AVAP Support Telegram Bot

This is a comprehensive, modular Telegram bot for AVAP, designed to manage student interactions, submissions, and administrative tasks. The bot is built with `python-telegram-bot`, `FastAPI`, and `SQLite`. It supports webhook-based deployment for production and polling for local development.

This repository has been refactored from a single-file application into a structured, modular project to improve maintainability, readability, and ease of debugging.

## Features

The bot provides a rich set of features for students and admins:

### Student Features (DM-Only)
-   **Verification**: Students verify themselves by providing their name, email, and phone number, which are checked against a pre-registered list.
-   **Assignment Submission**: Verified students can submit assignments for modules 1-12.
-   **Share Small Win**: Verified students can share their small wins as text, images, or videos.
-   **Ask a Question**: Verified students can ask questions directly to the support team.
-   **Check Status**: Verified students can check their submission status, scores, and win count.

### Admin Features
-   **Add Student**: Admins can pre-register students to the verification list.
-   **Manual Verification**: Admins can manually verify a student using their email.
-   **Remove Student**: Admins can remove a student's verified status.
-   **Grading**: Admins can grade submissions directly from the assignments group using an interactive inline flow.
-   **Answering Questions**: Admins can answer student questions from the questions group.

### Group & Scheduled Features
-   **Join Requests**: Automatically approves join requests for verified users and declines others.
-   **Weekly Reminders**: A scheduled job sends a reminder to all verified students every Sunday.

---

## Project Structure

The project is organized into a modular structure to separate concerns:

```
.
├── bot/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, startup/shutdown, webhook logic
│   ├── config.py        # Environment variables and logging setup
│   ├── database.py      # All SQLite database functions
│   ├── models.py        # Conversation states and keyboards
│   ├── scheduler.py     # APScheduler setup and jobs
│   ├── external/        # Modules for third-party services
│   │   ├── gsheets.py   # Google Sheets integration
│   │   └── systeme.py   # Systeme.io integration
│   └── handlers/        # Telegram update handlers
│       ├── admin.py     # Handlers for admin commands
│       ├── student.py   # Handlers for student conversations
│       ├── general.py   # General handlers (/start, /status)
│       └── callback.py  # Handlers for all inline button callbacks
├── scripts/
│   └── run_polling.py   # Script to run the bot locally for testing
├── .env.example         # Example environment file
├── requirements.txt     # Python dependencies
└── TESTING.md           # Manual testing plan
```

---

## Local Setup and Testing

Follow these steps to set up and run the project locally in polling mode.

### 1. Clone the Repository
```bash
git clone <repository_url>
cd <repository_directory>
```

### 2. Create a Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the root of the project. You can copy the example file:
```bash
cp .env.example .env
```
Now, open the `.env` file and fill in the required values. For local testing, you only need to set `BOT_TOKEN` and `ADMIN_ID`. The other group and API keys are optional.

### 5. Run the Bot in Polling Mode
For local development, you can run the bot in polling mode. This mode connects directly to Telegram's servers and does not require a public URL or webhook setup.

Run the following command in your terminal:
```bash
python scripts/run_polling.py
```
The bot will start polling for updates from Telegram. You can now interact with it to test its functionality as described in `TESTING.md`.

---

## Deployment (Render)

This bot is designed to be deployed as a Web Service on Render. The entry point for the web server is `bot.main:app`.

### 1. Create a New Web Service
-   Go to your Render dashboard and create a new "Web Service".
-   Connect your GitHub repository.

### 2. Configure the Service
-   **Name**: Give your service a name (e.g., `avap-support-bot`).
-   **Region**: Choose a region close to you.
-   **Branch**: Select the branch to deploy (e.g., `main`).
-   **Build Command**: `pip install -r requirements.txt`
-   **Start Command**: `uvicorn bot.main:app --host 0.0.0.0 --port $PORT`

### 3. Add Environment Variables
-   In the "Environment" section, add all the environment variables from your `.env` file.
-   **Important**: For the `WEBHOOK_URL` variable, use the public URL of your Render service (e.g., `https://your-app-name.onrender.com`). Render provides this URL in the service dashboard. The bot will automatically set the webhook on startup.

### 4. Persisting the Database on Render
By default, Render's free Web Services have an ephemeral filesystem, which means the SQLite database file (`avap_bot.db`) will be deleted on every restart or re-deployment. To persist your data, you must attach a **Render Free Disk**.

1.  **Create a Disk**: In your Render dashboard, go to the "Disks" section and create a new disk.
    -   **Name**: `avap-bot-data` (or any name you prefer).
    -   **Mount Path**: `/data`
    -   **Size**: 1 GB is sufficient.
2.  **Attach the Disk**: Go to your Web Service's "Settings" and find the "Disks" section. Attach the disk you just created.
3.  **Update Environment Variable**: In your Web Service's "Environment" settings, update the `DB_PATH` variable to point to the disk's mount path: `DB_PATH=/data/avap_bot.db`.

After making these changes, re-deploy your service. The database will now be stored on the persistent disk.
