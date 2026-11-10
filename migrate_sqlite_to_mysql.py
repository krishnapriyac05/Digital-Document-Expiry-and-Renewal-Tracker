"""Copy this project's SQLite documents and renewal history into configured MySQL."""

from __future__ import annotations

import sqlite3

import app


def main() -> None:
    if not app.DATABASE_URL.startswith(("mysql://", "mysql+pymysql://")):
        raise SystemExit("Configure a MySQL DATABASE_URL in .env before running this migration.")
    if not app.DB_PATH.exists():
        raise SystemExit(f"SQLite database was not found: {app.DB_PATH}")

    app.initialize(seed_empty=False)
    source = sqlite3.connect(f"file:{app.DB_PATH.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        documents = source.execute("SELECT * FROM documents ORDER BY id").fetchall()
        renewals = source.execute("SELECT * FROM renewals ORDER BY id").fetchall()
    finally:
        source.close()

    copied_documents = copied_renewals = 0
    with app.connect() as target:
        for row in documents:
            exists = target.execute("SELECT id FROM documents WHERE id=?", (row["id"],)).fetchone()
            if exists:
                continue
            target.execute(
                "INSERT INTO documents(id, name, doc_type, issue_date, expiry_date, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (row["id"], row["name"], row["doc_type"], row["issue_date"], row["expiry_date"], row["created_at"]),
            )
            copied_documents += 1
        for row in renewals:
            exists = target.execute("SELECT id FROM renewals WHERE id=?", (row["id"],)).fetchone()
            if exists:
                continue
            target.execute(
                "INSERT INTO renewals(id, document_id, document_name, previous_issue_date, previous_expiry_date, new_issue_date, new_expiry_date, renewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (row["id"], row["document_id"], row["document_name"], row["previous_issue_date"], row["previous_expiry_date"], row["new_issue_date"], row["new_expiry_date"], row["renewed_at"]),
            )
            copied_renewals += 1
    print(f"Migration complete: copied {copied_documents} document(s) and {copied_renewals} renewal record(s).")
    print("Existing MySQL rows with matching IDs were skipped. SQLite data was left unchanged.")


if __name__ == "__main__":
    main()
