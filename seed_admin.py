from getpass import getpass
from sqlalchemy import select
from db import init_db, SessionLocal
from models import User, Role
from auth import get_password_hash

def main():
    init_db()
    db = SessionLocal()
    try:
        username = input("Логин админа: ").strip()
        full_name = input("Полное имя: ").strip()
        email = input("Email: ").strip()
        pwd = getpass("Пароль: ")
        exists = db.scalar(select(User).where(User.username == username))
        if exists:
            print("Пользователь с таким логином уже существует")
            return
        u = User(username=username, full_name=full_name, email=email, role=Role.admin, hashed_password=get_password_hash(pwd))
        db.add(u); db.commit()
        print("OK, админ создан.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
