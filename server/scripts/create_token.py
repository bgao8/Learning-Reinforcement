import argparse
import sys

from sqlalchemy import select

from app.db.models import User
from app.db.session import SessionLocal
from app.auth import issue_token


def main():
    parser = argparse.ArgumentParser(description="Issue a device token and print it once.")
    parser.add_argument("--email", required=True, help="the user to issue the token for")
    parser.add_argument("--label", help='names the device, e.g. "MacBook"')
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email))
        if user is None:
            sys.exit(f"No user with email {args.email}; run scripts/seed.py first")

        token = issue_token(db, user.user_id, args.label)
        db.commit()
    
    label = f" for {args.label}" if args.label else ""
    print(f"Token{label} (shown once, store it now):")
    print(token)


if __name__ == "__main__":
      main()