# Validity — Digital Document Expiry and Renewal Tracker

A browser-based app for tracking document dates. Create an account or log in to open a private workspace; accounts and document records stay in the configured database on this computer. Python/Flask provides the backend, MySQL can store the records when configured, and SQLite is the zero-configuration local fallback. The app does not store identification numbers, accept document uploads, or connect to government services.

## Project phases

1. **Plan the data:** Documents have a unique database ID, name, type, issue date, and expiry date. Renewals keep both the old and new validity periods.
2. **Build the backend:** Flask provides routes for adding, editing, deleting, renewing, searching/listing, reading history, and generating each named report from the same status calculation. Configure MySQL with `DATABASE_URL` in `.env` to use MySQL storage.
3. **Build the interface:** The responsive blue/navy dashboard shows counts, searchable/filterable document lists, expiry windows, edit and renewal forms, and renewal history.
4. **Build reports:** Dedicated report tabs show all, active, expired, and documents expiring within 7, 15, and 30 days, plus renewal history. Both status and renewal reports can be downloaded as CSV.
5. **Check the rules:** Dates are validated, expiry cannot precede issue, remaining days are calculated from the computer's local date, and 7/15/30-day reports include documents expiring within the selected number of days.
6. **Run locally:** Start the Python server and use the app in a browser.

## Requirements checklist

- [x] Unique auto-incrementing ID for every document (SQLite or MySQL)
- [x] Add, view, update, search, and delete documents
- [x] Store issue and expiry dates
- [x] Reject invalid dates and expiry dates earlier than issue dates
- [x] Identify active, expiring-soon, and expired documents
- [x] Backend reports for all, active, expired, and expiring within 7, 15, or 30 days
- [x] Renew current validity while retaining prior dates
- [x] View renewal history
- [x] Dashboard status summary and dedicated reports for all, active, expired, and 7/15/30-day expiry windows
- [x] Renewal history report with previous and renewed validity dates
- [x] Downloadable CSV exports for each selected status report and renewal history
- [x] Fictional records only; no document upload or external integration

## Start the app on Windows

Double-click `start_tracker.bat`. It checks the Python dependencies, starts the backend and frontend separately, waits for both to respond, and opens the frontend. Keep both server windows open while using the app.

- Frontend: `http://127.0.0.1:5500`
- Backend health: `http://127.0.0.1:5051/api/health`

To start manually, open two terminals in this folder. In the first terminal, run:

```powershell
$env:PORT = "5051"
$env:FRONTEND_ORIGIN = "http://127.0.0.1:5500"
python app.py
```

In the second terminal, run:

```powershell
$env:FRONTEND_PORT = "5500"
$env:BACKEND_PORT = "5051"
python frontend_server.py
```

Then open `http://127.0.0.1:5500` in your browser. Keep both terminals open while using the app; press Ctrl+C in each to stop the services.

Install Python 3.10 or newer if needed. Install project dependencies with `python -m pip install -r requirements.txt`. If using MySQL, copy `.env.example` to `.env`, configure the database URL, and create the database; the app creates its tables automatically. To move existing SQLite documents and renewals, run `python migrate_sqlite_to_mysql.py` once after configuring MySQL. If `DATABASE_URL` is blank, the app saves data in `documents.db` beside `app.py`.

The backend stores account credentials as password hashes, document details (including vehicle insurance and vehicle registration documents), and renewal history. SQLite is the default persistent storage; MySQL can be configured for shared storage. The app binds only to your own computer (`127.0.0.1`).

The app adds four fictional sample documents when the selected database is empty. You can also use **Load fictional examples** in Recent Documents to add them to an existing workspace; duplicate sample names are skipped and existing records are not modified.

## Deploy on Render

The repository includes `render.yaml` for a single Render web service. In Render, choose **New → Blueprint**, connect this GitHub repository, and deploy the `main` branch. The Blueprint serves the UI and API from the same HTTPS URL, initializes the database at startup, and stores SQLite at `/var/data/documents.db` on a persistent disk. After deployment, open the service URL; the health check is `/api/health`.

This SQLite configuration includes a persistent disk, which Render only supports on a paid web service. The service is configured as a single instance to avoid concurrent SQLite writes to a shared disk. Keep the generated `SECRET_KEY` value stable; changing it signs users out. Render deploys later pushes to the connected branch automatically.
## Main files

- `app.py` — Flask app, validation, SQLite/MySQL storage, API, and CSV reports
- `frontend_server.py` — local frontend server on port 5500
- `render.yaml` — Render web service, health check, secrets, and persistent database disk
- `migrate_sqlite_to_mysql.py` — one-time migration for existing SQLite documents and renewal history
- `templates/index.html` — page structure and forms
- `static/styles.css` — responsive styling
- `static/app.js` — dashboard behavior and API interactions
- `requirements.txt` — Python dependency
- `document_tracker.py` — original command-line version
