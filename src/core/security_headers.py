"""Enterprise OWASP HTTP Security Headers Middleware.

Injects defense-in-depth security response headers to safeguard clients against
Cross-Site Scripting (XSS), Clickjacking, MIME-confusion, and protocol downgrade attacks.
"""

from __future__ import annotations

from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Strict Content Security Policy
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "base-uri 'self';"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Starlette / FastAPI ASGI middleware injecting OWASP security headers."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Anti-Clickjacking: Prevent framing
        response.headers["X-Frame-Options"] = "DENY"

        # MIME Sniffing Defense: Prevent browser guessing content-type
        response.headers["X-Content-Type-Options"] = "nosniff"

        # XSS Protection for legacy user agents
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer Policy: Send full URL on same origin, only domain across origins
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Strict Transport Security (HSTS): Force HTTPS for 1 year
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

        # Permissions Policy: Disable sensitive browser hardware capabilities
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=(), payment=(), usb=()"
        )

        # Cross-Domain Policy
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"

        # Content Security Policy
        response.headers["Content-Security-Policy"] = DEFAULT_CSP

        return response
