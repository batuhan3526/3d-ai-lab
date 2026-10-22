"""Token-based auth.

İki tür token kabul edilir:
- **APP_TOKEN** (makine token'ı): worker/script/e2e için sabit token. HER ZAMAN
  önce ve sabit-zamanlı (`secrets.compare_digest`) karşılaştırılır → makine
  bağlamı asla kırılmaz. Kullanıcı bağlamı: `request.state.user_id = None`.
- **Oturum token'ı**: `POST /auth/login`/`/auth/setup` ile üretilen opak token
  (DB `sessions` tablosu, 30 gün). Süresi geçmemişse `request.state.user_id`
  ilgili kullanıcıya ayarlanır.
"""
import secrets

from common.config import get_settings
from fastapi import Depends, Header, HTTPException, Request, status


def _extract_bearer(authorization: str | None) -> str | None:
    """`Bearer <token>` formatından token'ı çıkar; başarısızsa None."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _lookup_session(token: str) -> str | None:
    """Oturum token'ından user_id (süresi geçmemişse); DB hatasında None."""
    try:
        from gateway.db import get_sessionmaker
        from gateway.users import lookup_session_user

        sm = get_sessionmaker()
        with sm() as session:
            return lookup_session_user(session, token)
    except Exception:  # noqa: BLE001 — tablo yok / DB down → oturum yok
        return None


async def verify_token(
    request: Request, authorization: str | None = Header(default=None)
) -> None:
    """Authorization header'ından Bearer token'ı doğrula.

    APP_TOKEN önce (sabit-zamanlı); eşleşmezse oturum lookup'ı. Başarıda
    `request.state.user_id` ayarlanır (makine token'ında None)."""
    token = _extract_bearer(authorization)
    if not token:
        raise _unauthorized()

    expected = get_settings().app_token
    # APP_TOKEN İLK — makine token'ı asla kırılmaz (worker/e2e).
    if expected and secrets.compare_digest(token, expected):
        request.state.user_id = None
        return

    user_id = _lookup_session(token)
    if user_id is not None:
        request.state.user_id = user_id
        return

    raise _unauthorized()


def require_token() -> Depends:
    """Route dependency factory: `_: None = require_token()` route'a auth ekler."""
    return Depends(verify_token)
