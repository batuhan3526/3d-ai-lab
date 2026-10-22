"""Auth route'ları — ev/LAN çok-kullanıcı (setup/login/me/users/password).

APP_TOKEN "makine token'ı" olarak geçerli kalır (worker/e2e kırılmaz); bu
route'lar oturum (session) token'larıyla kullanıcı bağlamı ekler. Admin
işlemleri (kullanıcı ekle/sil) makine token'ıyla da yapılabilir (tam yetki).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from gateway.auth import verify_token
from gateway.db import get_db
from gateway import users as users_mod

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Şemalar -------------------------------------------------------------------
class SetupIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class CreateUserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)
    is_admin: bool = False


class PasswordIn(BaseModel):
    old: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=1, max_length=200)


# --- Bağımlılıklar -------------------------------------------------------------
async def current_user_id(
    request: Request, _: None = Depends(verify_token)
) -> str | None:
    """verify_token çalıştıktan sonra istekteki kullanıcı bağlamı.

    Makine token'ı (APP_TOKEN) ile None döner (belirli bir kullanıcı yok)."""
    return getattr(request.state, "user_id", None)


async def require_admin(
    uid: str | None = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> str | None:
    """Admin gerektiren route'lar için. Makine token'ı = tam yetki (admin)."""
    if uid is None:
        return None  # makine token'ı
    user = users_mod.get_user_by_id(db, uid)
    if user is None or not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Admin yetkisi gerekli")
    return uid


# --- Public route'lar ----------------------------------------------------------
@router.get("/needs-setup")
def needs_setup(db: Session = Depends(get_db)) -> dict:
    """Hiç kullanıcı yoksa frontend kurulum ekranını gösterir."""
    return {"needs_setup": users_mod.count_users(db) == 0}


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def setup(payload: SetupIn, db: Session = Depends(get_db)) -> dict:
    """İlk admin'i oluştur — SADECE users tablosu boşken çalışır."""
    if users_mod.count_users(db) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Kurulum zaten yapıldı")
    user = users_mod.create_user(db, payload.username, payload.password, is_admin=True)
    token = users_mod.create_session(db, user.id)
    db.commit()
    return {"token": token, "username": user.username, "is_admin": user.is_admin}


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)) -> dict:
    row = users_mod.get_user_by_username(db, payload.username)
    if row is None or not users_mod.verify_password(payload.password, row.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Kullanıcı adı veya parola hatalı")
    token = users_mod.create_session(db, row.id)
    db.commit()
    return {"token": token, "username": row.username, "is_admin": bool(row.is_admin)}


# --- Korumalı route'lar --------------------------------------------------------
@router.get("/me")
def me(
    uid: str | None = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    if uid is None:
        # Makine token'ı — belirli bir kullanıcı yok, tam yetkili sayılır.
        return {"id": None, "username": None, "is_admin": True, "machine": True}
    user = users_mod.get_user_by_id(db, uid)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Oturum geçersiz")
    return {"id": user.id, "username": user.username,
            "is_admin": user.is_admin, "machine": False}


@router.get("/users")
def list_users(
    _admin: str | None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {"id": u.id, "username": u.username, "is_admin": u.is_admin,
         "created_at": u.created_at}
        for u in users_mod.list_users(db)
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def add_user(
    payload: CreateUserIn,
    _admin: str | None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    if users_mod.username_exists(db, payload.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Kullanıcı adı zaten var")
    user = users_mod.create_user(db, payload.username, payload.password,
                                 is_admin=payload.is_admin)
    db.commit()
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin}


@router.delete("/users/{user_id}")
def remove_user(
    user_id: str,
    uid: str | None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    if uid is not None and uid == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Kendinizi silemezsiniz")
    if users_mod.get_user_by_id(db, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Kullanıcı bulunamadı")
    users_mod.delete_user(db, user_id)
    db.commit()
    return {"deleted": user_id}


@router.post("/password")
def change_password(
    payload: PasswordIn,
    uid: str | None = Depends(current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    if uid is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Makine token'ının parolası değiştirilemez")
    row = users_mod.get_user_by_username(
        db, users_mod.get_user_by_id(db, uid).username
    )
    if row is None or not users_mod.verify_password(payload.old, row.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Mevcut parola hatalı")
    users_mod.set_password(db, uid, payload.new)
    db.commit()
    return {"ok": True}
