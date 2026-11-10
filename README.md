# Validity — Digital Document Expiry and Renewal Tracker

A local browser-based app for tracking document dates. Python/Flask provides the backend, MySQL can store the records when configured, and HTML/CSS/JavaScript provide the interface. SQLite is the zero-configuration local fallback. The app does not store identification numbers, accept document uploads, or connect to government services.

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

## Start the app

1. Install Python 3.10 or newer if it is not already installed.
2. Open a terminal in this folder. To use MySQL, copy `.env.example` to `.env`, edit the MySQL username/password and database name, and create the database in MySQL Workbench or your MySQL client. For example: `CREATE DATABASE document_tracker CHARACTER SET utf8mb4;`. The app creates its tables automatically. To move existing SQLite documents and renewals, run `python migrate_sqlite_to_mysql.py` once after configuring `.env`; IDs are preserved and the SQLite file is left unchanged. If `DATABASE_URL` is blank, the app uses `documents.db` (SQLite).
3. Install the dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Start the server:

   ```powershell
   python app.py
   ```

5. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser. Keep the terminal window open while using the app; press Ctrl+C there to stop it.

With SQLite, `documents.db` is created beside `app.py`. With MySQL configured, records are stored in your configured MySQL database. The app binds only to your own computer (`127.0.0.1`).

To confirm which storage the running app is using and how many records it sees, open [http://127.0.0.1:5000/api/health](http://127.0.0.1:5000/api/health). The server terminal also prints the active storage mode at startup.

The app adds four fictional sample documents when the selected database is empty. You can also use **Load fictional examples** in Recent Documents to add them to an existing workspace; duplicate sample names are skipped and existing records are not modified.

## Main files

- `app.py` — Flask app, validation, SQLite/MySQL storage, API, and CSV reports
- `migrate_sqlite_to_mysql.py` — one-time migration for existing SQLite documents and renewal history
- `templates/index.html` — page structure and forms
- `static/styles.css` — responsive styling
- `static/app.js` — dashboard behavior and API interactions
- `requirements.txt` — Python dependency
- `document_tracker.py` — original command-line version
