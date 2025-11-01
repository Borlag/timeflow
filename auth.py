from fastapi import Depends, HTTPException, Request
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from db import SessionLocal
from models import User, Role
from config import SECRET_KEY

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive or unknown user")
    return user

def require_roles(*roles: Role):
    def inner(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return inner

def install_session_middleware(app):
    # Install SessionMiddleware in the main app
    app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")
