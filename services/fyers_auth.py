from __future__ import annotations
import json, logging, os, threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from fyers_apiv3 import fyersModel
from config import Config

logger = logging.getLogger(__name__)
_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime_data"
_TOKEN_FILE = _RUNTIME_DIR / "fyers_session.json"
_LOCK = threading.RLock()

class FyersAuthError(RuntimeError):
    pass

@dataclass(frozen=True, slots=True)
class AuthState:
    configured: bool
    authenticated: bool
    client_id: str | None
    redirect_uri: str | None
    token_source: str | None
    token_updated_at: str | None
    missing_fields: tuple[str, ...]
    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "authenticated": self.authenticated,
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "token_source": self.token_source,
            "token_updated_at": self.token_updated_at,
            "missing_fields": list(self.missing_fields),
        }

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _missing() -> list[str]:
    return Config.missing_fyers_fields()

def _validate_redirect() -> None:
    uri = Config.FYERS_REDIRECT_URI
    p = urlparse(uri)
    if p.scheme not in {"http", "https"} or not p.netloc:
        raise FyersAuthError("FYERS_REDIRECT_URI is invalid.")
    if Config.APP_ENV == "production" and p.scheme != "https":
        raise FyersAuthError("Production FYERS_REDIRECT_URI must use HTTPS.")

def _read_record() -> dict[str, Any] | None:
    with _LOCK:
        if not _TOKEN_FILE.exists():
            return None
        try:
            data = json.loads(_TOKEN_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Unable to read FYERS token record")
            return None
        if not isinstance(data, dict) or not str(data.get("access_token") or "").strip():
            return None
        return data

def _write_record(token: str) -> None:
    token = str(token or "").strip()
    if not token:
        raise FyersAuthError("FYERS returned an empty access token.")
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _TOKEN_FILE.with_suffix(".tmp")
    payload = {
        "access_token": token,
        "source": "oauth_runtime",
        "updated_at": _now(),
    }
    with _LOCK:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, _TOKEN_FILE)

def get_access_token() -> str | None:
    env_token = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token
    record = _read_record()
    return str(record["access_token"]).strip() if record else None

def token_source() -> str | None:
    if os.getenv("FYERS_ACCESS_TOKEN", "").strip():
        return "environment"
    record = _read_record()
    return str(record.get("source") or "oauth_runtime") if record else None

def token_updated_at() -> str | None:
    if os.getenv("FYERS_ACCESS_TOKEN", "").strip():
        return None
    record = _read_record()
    if not record:
        return None
    return str(record.get("updated_at") or "") or None

def get_auth_state() -> AuthState:
    missing = tuple(_missing())
    return AuthState(
        configured=not missing,
        authenticated=get_access_token() is not None,
        client_id=Config.FYERS_CLIENT_ID or None,
        redirect_uri=Config.FYERS_REDIRECT_URI or None,
        token_source=token_source(),
        token_updated_at=token_updated_at(),
        missing_fields=missing,
    )

def _session() -> Any:
    missing = _missing()
    if missing:
        raise FyersAuthError("FYERS configuration incomplete: " + ", ".join(missing))
    _validate_redirect()
    try:
        return fyersModel.SessionModel(
            client_id=Config.FYERS_CLIENT_ID,
            secret_key=Config.FYERS_SECRET_KEY,
            redirect_uri=Config.FYERS_REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code",
        )
    except Exception as exc:
        raise FyersAuthError(f"Unable to initialize FYERS session: {exc}") from exc

def generate_login_url() -> str:
    try:
        url = str(_session().generate_authcode() or "").strip()
    except FyersAuthError:
        raise
    except Exception as exc:
        raise FyersAuthError(f"Unable to generate FYERS login URL: {exc}") from exc
    if not url:
        raise FyersAuthError("FYERS SDK returned an empty login URL.")
    return url

def exchange_auth_code(auth_code: str) -> dict[str, Any]:
    code = str(auth_code or "").strip()
    if not code:
        raise FyersAuthError("FYERS auth_code is missing.")
    session = _session()
    try:
        session.set_token(code)
        response = session.generate_token()
    except Exception as exc:
        raise FyersAuthError(f"FYERS token exchange failed: {exc}") from exc
    if not isinstance(response, dict):
        raise FyersAuthError("FYERS token exchange returned an invalid response.")
    token = str(response.get("access_token") or "").strip()
    if not token:
        raise FyersAuthError(str(response.get("message") or response.get("msg") or "FYERS did not return an access token."))
    _write_record(token)
    return {
        "success": True,
        "authenticated": True,
        "token_source": "oauth_runtime",
        "updated_at": token_updated_at(),
    }

def clear_access_token() -> bool:
    with _LOCK:
        try:
            if _TOKEN_FILE.exists():
                _TOKEN_FILE.unlink()
            return True
        except OSError:
            logger.exception("Unable to clear FYERS token")
            return False

def create_fyers_client(*, is_async: bool = False, log_path: str = "") -> Any:
    missing = _missing()
    if missing:
        raise FyersAuthError("FYERS configuration incomplete: " + ", ".join(missing))
    token = get_access_token()
    if not token:
        raise FyersAuthError("FYERS is not authenticated.")
    try:
        return fyersModel.FyersModel(
            client_id=Config.FYERS_CLIENT_ID,
            token=token,
            is_async=is_async,
            log_path=log_path,
        )
    except Exception as exc:
        raise FyersAuthError(f"Unable to initialize FYERS REST client: {exc}") from exc

def verify_access_token() -> dict[str, Any]:
    try:
        response = create_fyers_client().get_profile()
    except FyersAuthError:
        raise
    except Exception as exc:
        raise FyersAuthError(f"FYERS token verification failed: {exc}") from exc
    if not isinstance(response, dict) or str(response.get("s") or "").lower() != "ok":
        message = response.get("message") if isinstance(response, dict) else None
        raise FyersAuthError(str(message or "FYERS rejected the current access token."))
    data = response.get("data")
    if not isinstance(data, dict):
        data = {}
    return {
        "success": True,
        "verified": True,
        "profile": {
            "name": data.get("name"),
            "display_name": data.get("display_name"),
            "fy_id": data.get("fy_id"),
        },
        "token_source": token_source(),
        "token_updated_at": token_updated_at(),
    }

def websocket_access_token() -> str:
    token = get_access_token()
    if not Config.FYERS_CLIENT_ID:
        raise FyersAuthError("FYERS_CLIENT_ID is missing.")
    if not token:
        raise FyersAuthError("FYERS is not authenticated.")
    return f"{Config.FYERS_CLIENT_ID}:{token}"

