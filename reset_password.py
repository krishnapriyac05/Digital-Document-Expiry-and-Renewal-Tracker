"""Reset a Document Tracker account password from the local project terminal."""

from __future__ import annotations

from getpass import getpass

from werkzeug.security import generate_password_hash

from app import connect


def reset_password(email: str, new_password: str) -> bool:
    normalized_email = email.strip().lower()
    if not normalized_email:
        raise ValueError("Enter the email address used for the account.")
    if len(new_password) < 8:
        raise ValueError("Choose a password with at least 8 characters.")

    with connect() as db:
        user = db.execute("SELECT id FROM users WHERE email=?", (normalized_email,)).fetchone()
        if user is None:
            return False
        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (generate_password_hash(new_password), user["id"]),
        )
    return True


def main() -> int:
    print("Document Tracker password recovery")
    email = input("Account email: ").strip()
    new_password = getpass("New password (at least 8 characters): ")
    confirmation = getpass("Confirm new password: ")
    if new_password != confirmation:
        print("The passwords did not match. No changes were made.")
        return 1
    try:
        updated = reset_password(email, new_password)
    except ValueError as exc:
        print(exc)
        return 1
    if not updated:
        print("No account was found for that email. Check the address and try again.")
        return 1
    print("Password reset successfully. Log in with your new password.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
