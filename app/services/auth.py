import hmac

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.core.config import ADMIN_PASSWORD, ADMIN_USERNAME


def is_admin_authenticated(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def verify_admin_credentials(username: str, password: str) -> bool:
    return hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(password, ADMIN_PASSWORD)


def login_admin(request: Request, username: str, password: str) -> bool:
    if not verify_admin_credentials(username, password):
        return False
    request.session["is_admin"] = True
    request.session["admin_username"] = username
    return True


def logout_admin(request: Request) -> None:
    request.session.clear()


def ensure_admin(request: Request) -> RedirectResponse | None:
    if is_admin_authenticated(request):
        return None
    return RedirectResponse(url="/admin/login", status_code=303)