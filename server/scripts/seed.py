from sqlalchemy import select

from app.db.models import User
from app.db.session import SessionLocal

EMAIL = "bgao2005@gmail.com"

def main():
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email==EMAIL))
        if existing:
            print(f"Seed user already exists: {existing.user_id}")
            return

        user = User(user_name="Brandon", email=EMAIL)
        db.add(user)
        db.commit()
        print(f"Created seed user: {user.user_id}")

if __name__ == "__main__":
    main()