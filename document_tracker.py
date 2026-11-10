"""Digital Document Expiry and Renewal Tracker.

Uses a local SQLite database (documents.db) in this folder. Sample data is
fictional and deliberately contains no real identification numbers.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path


DB_PATH = Path(__file__).with_name("documents.db")
DATE_FORMAT = "%d-%m-%Y"
SOON_DAYS = (7, 15, 30)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                issue_date TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS renewals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id),
                previous_issue_date TEXT NOT NULL,
                previous_expiry_date TEXT NOT NULL,
                new_issue_date TEXT NOT NULL,
                new_expiry_date TEXT NOT NULL,
                renewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError as exc:
        raise ValueError("Enter a valid date in DD-MM-YYYY format.") from exc


def ask_date(prompt: str, min_date: date | None = None) -> date:
    while True:
        try:
            result = parse_date(input(prompt))
            if min_date is not None and result < min_date:
                print("Expiry date cannot be earlier than issue date.")
                continue
            return result
        except ValueError as exc:
            print(exc)


def status_for(expiry: date, today: date | None = None) -> tuple[str, int]:
    today = today or date.today()
    remaining = (expiry - today).days
    if remaining < 0:
        return "Expired", remaining
    if remaining <= 30:
        return "Expiring Soon", remaining
    return "Active", remaining


def display_rows(rows: list[sqlite3.Row]) -> None:
    if not rows:
        print("No documents found.")
        return
    print("\n{:<5} {:<25} {:<18} {:<12} {:<12} {:<15} {:>8}".format(
        "ID", "Document", "Type", "Issue", "Expiry", "Status", "Days"
    ))
    print("-" * 101)
    for row in rows:
        expiry = date.fromisoformat(row["expiry_date"])
        status, days = status_for(expiry)
        print("{:<5} {:<25} {:<18} {:<12} {:<12} {:<15} {:>8}".format(
            row["id"], row["name"][:24], row["doc_type"][:17],
            date.fromisoformat(row["issue_date"]).strftime(DATE_FORMAT),
            expiry.strftime(DATE_FORMAT), status, days
        ))


def all_documents() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM documents ORDER BY expiry_date, id").fetchall()


def add_document() -> None:
    name = input("Document name: ").strip()
    doc_type = input("Document type: ").strip()
    if not name or not doc_type:
        print("Name and type are required.")
        return
    issue = ask_date("Issue date (DD-MM-YYYY): ")
    expiry = ask_date("Expiry date (DD-MM-YYYY): ", issue)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO documents (name, doc_type, issue_date, expiry_date) VALUES (?, ?, ?, ?)",
            (name, doc_type, issue.isoformat(), expiry.isoformat()),
        )
        print(f"Document added successfully. ID: {cur.lastrowid}")


def find_document(document_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()


def prompt_document() -> sqlite3.Row | None:
    try:
        document_id = int(input("Document ID: ").strip())
    except ValueError:
        print("Enter a numeric document ID.")
        return None
    row = find_document(document_id)
    if row is None:
        print("Document not found.")
    return row


def update_document() -> None:
    row = prompt_document()
    if row is None:
        return
    print("Press Enter to keep the current value.")
    name = input(f"Name [{row['name']}]: ").strip() or row["name"]
    doc_type = input(f"Type [{row['doc_type']}]: ").strip() or row["doc_type"]
    old_issue = date.fromisoformat(row["issue_date"])
    old_expiry = date.fromisoformat(row["expiry_date"])
    issue_text = input(f"Issue date [{old_issue.strftime(DATE_FORMAT)}]: ").strip()
    expiry_text = input(f"Expiry date [{old_expiry.strftime(DATE_FORMAT)}]: ").strip()
    try:
        issue = parse_date(issue_text) if issue_text else old_issue
        expiry = parse_date(expiry_text) if expiry_text else old_expiry
        if expiry < issue:
            print("Expiry date cannot be earlier than issue date.")
            return
    except ValueError as exc:
        print(exc)
        return
    with connect() as conn:
        conn.execute(
            "UPDATE documents SET name=?, doc_type=?, issue_date=?, expiry_date=? WHERE id=?",
            (name, doc_type, issue.isoformat(), expiry.isoformat(), row["id"]),
        )
    print("Document updated successfully.")


def search_document() -> None:
    term = input("Search by name or type: ").strip()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE name LIKE ? OR doc_type LIKE ? ORDER BY name",
            (f"%{term}%", f"%{term}%"),
        ).fetchall()
    display_rows(rows)


def filtered_documents(kind: str, days: int | None = None) -> list[sqlite3.Row]:
    today = date.today()
    rows = all_documents()
    result = []
    for row in rows:
        expiry = date.fromisoformat(row["expiry_date"])
        remaining = (expiry - today).days
        if kind == "expired" and remaining < 0:
            result.append(row)
        elif kind == "active" and remaining > 30:
            result.append(row)
        elif kind == "soon" and days is not None and 0 <= remaining <= days:
            result.append(row)
    return result


def renew_document() -> None:
    row = prompt_document()
    if row is None:
        return
    issue = ask_date("New issue date (DD-MM-YYYY): ")
    expiry = ask_date("New expiry date (DD-MM-YYYY): ", issue)
    with connect() as conn:
        conn.execute(
            "INSERT INTO renewals (document_id, previous_issue_date, previous_expiry_date, new_issue_date, new_expiry_date) VALUES (?, ?, ?, ?, ?)",
            (row["id"], row["issue_date"], row["expiry_date"], issue.isoformat(), expiry.isoformat()),
        )
        conn.execute(
            "UPDATE documents SET issue_date=?, expiry_date=? WHERE id=?",
            (issue.isoformat(), expiry.isoformat(), row["id"]),
        )
    print("Renewal successful. Previous validity has been saved to renewal history.")


def renewal_history() -> None:
    with connect() as conn:
        rows = conn.execute(
            "SELECT r.*, d.name FROM renewals r JOIN documents d ON d.id=r.document_id ORDER BY r.renewed_at DESC, r.id DESC"
        ).fetchall()
    if not rows:
        print("No renewal history found.")
        return
    print("\n{:<5} {:<25} {:<12} {:<12} {:<12} {:<12} {}".format(
        "ID", "Document", "Old Issue", "Old Expiry", "New Issue", "New Expiry", "Renewed at"
    ))
    print("-" * 105)
    for row in rows:
        values = [row[k] for k in ("previous_issue_date", "previous_expiry_date", "new_issue_date", "new_expiry_date")]
        dates = [date.fromisoformat(v).strftime(DATE_FORMAT) for v in values]
        print("{:<5} {:<25} {:<12} {:<12} {:<12} {:<12} {}".format(
            row["document_id"], row["name"][:24], *dates, row["renewed_at"]
        ))


def status_report() -> None:
    print("\nDocument Status Report")
    display_rows(all_documents())
    today = date.today()
    print("\nSummary")
    print(f"Total documents: {len(all_documents())}")
    print(f"Active (more than 30 days): {len(filtered_documents('active'))}")
    print(f"Expired: {len(filtered_documents('expired'))}")
    for days in SOON_DAYS:
        print(f"Expiring within {days} days: {len(filtered_documents('soon', days))}")
    print(f"Report date: {today.strftime(DATE_FORMAT)}")


def main() -> None:
    initialize()
    actions = {
        "1": add_document,
        "2": lambda: display_rows(all_documents()),
        "3": update_document,
        "4": search_document,
        "5": lambda: display_rows(filtered_documents("expired")),
        "6": lambda: expiring_menu(),
        "7": renew_document,
        "8": renewal_history,
        "9": status_report,
    }
    while True:
        print("\n=== Digital Document Expiry and Renewal Tracker ===")
        print("1. Add Document\n2. View All Documents\n3. Update Document Details")
        print("4. Search Document\n5. View Expired Documents\n6. View Documents Expiring Soon")
        print("7. Renew Document\n8. View Renewal History\n9. Generate Document Status Report\n10. Exit")
        choice = input("Choose an option: ").strip()
        if choice == "10":
            print("Goodbye!")
            break
        action = actions.get(choice)
        if action:
            action()
        else:
            print("Choose a number from 1 to 10.")


def expiring_menu() -> None:
    print("\nExpiring within: 1. 7 days  2. 15 days  3. 30 days")
    choice = input("Choose a range: ").strip()
    days = {"1": 7, "2": 15, "3": 30}.get(choice)
    if days is None:
        print("Choose 1, 2, or 3.")
        return
    print(f"Documents expiring within {days} days:")
    display_rows(filtered_documents("soon", days))


if __name__ == "__main__":
    main()
