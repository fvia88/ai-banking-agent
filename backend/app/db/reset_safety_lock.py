"""Explicit local operator reset. Does not change balances or remove transactions."""
import argparse

from app.db.session import SessionLocal
from app.services.safety_lock import reset_safety_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--reason", required=True, help="Review note, without secrets")
    parser.add_argument("--confirm-demo-reset", action="store_true", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        try:
            audit_id = reset_safety_lock(db, args.user_id, args.reason)
            db.commit()
        except Exception:
            db.rollback()
            raise
    print(f"Demo safety lock reset for {args.user_id}. Audit: {audit_id}")


if __name__ == "__main__":
    main()
