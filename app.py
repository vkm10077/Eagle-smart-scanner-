from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from config import Config
from services.fyers_auth import (
    FyersAuthError,
    clear_access_token,
    exchange_auth_code,
    generate_login_url,
    get_auth_state,
    verify_access_token,
)


BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(Config.APP_NAME)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_error(
    message: str,
    *,
    status_code: int = 400,
    error: str = "request_error",
    details: dict[str, Any] | None = None,
):
    payload: dict[str, Any] = {
        "success": False,
        "error": error,
        "message": message,
        "timestamp": utc_now_iso(),
    }

    if details:
        payload["details"] = details

    return jsonify(payload), status_code


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(BASE_DIR / "static"),
        template_folder=str(BASE_DIR / "templates"),
    )

    app.config.update(
        SECRET_KEY=Config.SECRET_KEY,
        JSON_SORT_KEYS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=Config.SESSION_COOKIE_SECURE,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )

    # =========================================================
    # SECURITY / RESPONSE HEADERS
    # =========================================================

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"

        if Config.APP_ENV == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response

    # =========================================================
    # FOUNDATION
    # =========================================================

    @app.get("/health")
    def health():
        auth_state = get_auth_state()

        return jsonify(
            {
                "success": True,
                "app": Config.APP_NAME,
                "version": Config.APP_VERSION,
                "status": "healthy",
                "environment": Config.APP_ENV,
                "fyers_configured": auth_state.configured,
                "fyers_authenticated": auth_state.authenticated,
                "timestamp": utc_now_iso(),
            }
        )

    @app.get("/api/system/config")
    def system_config():
        return jsonify(
            {
                "success": True,
                "config": Config.public_runtime_config(),
                "timestamp": utc_now_iso(),
            }
        )

    @app.get("/")
    def root():
        auth_state = get_auth_state()

        return jsonify(
            {
                "success": True,
                "app": Config.APP_NAME,
                "version": Config.APP_VERSION,
                "stage": "FYERS authentication",
                "status": "running",
                "fyers": auth_state.as_dict(),
                "endpoints": {
                    "health": "/health",
                    "system_config": "/api/system/config",
                    "auth_status": "/api/auth/status",
                    "auth_login": "/auth/login",
                    "auth_verify": "/api/auth/verify",
                    "auth_logout": "/auth/logout",
                },
                "message": (
                    "FYERS authentication is ready for testing."
                    if auth_state.configured
                    else "Add FYERS environment variables in Render."
                ),
                "timestamp": utc_now_iso(),
            }
        )

    # =========================================================
    # FYERS AUTHENTICATION
    # =========================================================

    @app.get("/api/auth/status")
    def auth_status():
        state = get_auth_state()

        return jsonify(
            {
                "success": True,
                "auth": state.as_dict(),
                "timestamp": utc_now_iso(),
            }
        )

    @app.get("/auth/login")
    def auth_login():
        """
        Starts official FYERS OAuth flow.

        Expected environment variables:
        FYERS_CLIENT_ID
        FYERS_SECRET_KEY
        FYERS_REDIRECT_URI
        """
        try:
            login_url = generate_login_url()
        except FyersAuthError as exc:
            logger.warning("FYERS login URL error: %s", exc)
            return _json_error(
                str(exc),
                status_code=503,
                error="fyers_configuration_error",
                details={
                    "missing_fields": get_auth_state().as_dict().get(
                        "missing_fields",
                        [],
                    )
                },
            )

        # Store a lightweight marker only.
        # Actual FYERS token is never stored inside the browser session.
        session["fyers_login_started"] = True
        session["fyers_login_started_at"] = utc_now_iso()

        return redirect(login_url, code=302)

    @app.get("/auth/callback")
    def auth_callback():
        """
        FYERS redirects here after user authorization.

        Common callback fields:
        auth_code=<real authorization code>
        s=ok
        state=...
        """
        auth_code = str(
            request.args.get("auth_code")
            or request.args.get("code")
            or ""
        ).strip()

        status = str(request.args.get("s") or "").strip().lower()

        if status and status != "ok":
            message = str(
                request.args.get("message")
                or "FYERS authentication was not completed."
            )
            logger.warning(
                "FYERS callback rejected: status=%s message=%s",
                status,
                message,
            )
            return _json_error(
                message,
                status_code=401,
                error="fyers_auth_rejected",
            )

        if not auth_code:
            return _json_error(
                "FYERS callback did not contain auth_code.",
                status_code=400,
                error="missing_auth_code",
            )

        try:
            result = exchange_auth_code(auth_code)
        except FyersAuthError as exc:
            logger.warning("FYERS token exchange failed: %s", exc)
            return _json_error(
                str(exc),
                status_code=401,
                error="fyers_token_exchange_failed",
            )

        session.pop("fyers_login_started", None)
        session.pop("fyers_login_started_at", None)

        # Browser-friendly success response for this build stage.
        return jsonify(
            {
                "success": True,
                "message": "FYERS authentication completed.",
                "auth": result,
                "next": "/api/auth/verify",
                "timestamp": utc_now_iso(),
            }
        )

    @app.get("/api/auth/verify")
    def auth_verify():
        """
        Real verification call to FYERS profile endpoint.
        This proves that the stored token actually works.
        """
        state = get_auth_state()

        if not state.authenticated:
            return _json_error(
                "FYERS is not authenticated.",
                status_code=401,
                error="not_authenticated",
            )

        try:
            verification = verify_access_token()
        except FyersAuthError as exc:
            logger.warning("FYERS token verification failed: %s", exc)
            return _json_error(
                str(exc),
                status_code=401,
                error="fyers_verification_failed",
            )

        return jsonify(
            {
                "success": True,
                "verification": verification,
                "timestamp": utc_now_iso(),
            }
        )

    @app.route("/auth/logout", methods=["GET", "POST"])
    def auth_logout():
        """
        Clears Eagle's locally cached OAuth token.
        This does not claim to revoke the token at FYERS.
        """
        cleared = clear_access_token()

        session.clear()

        if not cleared:
            return _json_error(
                "Unable to clear local FYERS token cache.",
                status_code=500,
                error="logout_failed",
            )

        return jsonify(
            {
                "success": True,
                "authenticated": False,
                "message": "Local FYERS session cleared.",
                "timestamp": utc_now_iso(),
            }
        )

    # =========================================================
    # API PLACEHOLDERS FOR FUTURE STAGES
    # Explicit 501 responses prevent frontend confusion and make it
    # obvious which stage is not implemented yet.
    # =========================================================

    @app.get("/api/indices")
    def indices_not_ready():
        return _json_error(
            "Index service is not implemented yet.",
            status_code=501,
            error="stage_not_ready",
        )

    @app.get("/api/sectors")
    def sectors_not_ready():
        return _json_error(
            "Sector service is not implemented yet.",
            status_code=501,
            error="stage_not_ready",
        )

    @app.get("/api/stocks")
    def stocks_not_ready():
        return _json_error(
            "Stock service is not implemented yet.",
            status_code=501,
            error="stage_not_ready",
        )

    @app.get("/api/signals")
    def signals_not_ready():
        return _json_error(
            "Scanner engine is not implemented yet.",
            status_code=501,
            error="stage_not_ready",
        )

    # =========================================================
    # ERROR HANDLERS
    # =========================================================

    @app.errorhandler(404)
    def not_found(_error):
        return _json_error(
            "Requested endpoint does not exist.",
            status_code=404,
            error="not_found",
            details={"path": request.path},
        )

    @app.errorhandler(405)
    def method_not_allowed(_error):
        return _json_error(
            "HTTP method is not allowed for this endpoint.",
            status_code=405,
            error="method_not_allowed",
            details={"path": request.path},
        )

    @app.errorhandler(413)
    def payload_too_large(_error):
        return _json_error(
            "Request payload is too large.",
            status_code=413,
            error="payload_too_large",
        )

    @app.errorhandler(Exception)
    def unexpected_error(exc: Exception):
        logger.exception("Unhandled Eagle Smart Scanner error")

        message = (
            str(exc)
            if Config.DEBUG_ERRORS
            else "Internal server error."
        )

        return _json_error(
            message,
            status_code=500,
            error="internal_server_error",
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        debug=Config.FLASK_DEBUG,
    )

