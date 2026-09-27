"""Fixed OIDC endpoints; real provider registration is an explicit server-side choice."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

SCOPES = "openid email profile"
MICROSOFT_CONSUMERS = "9188040d-6c67-4c5b-b112-36a304b66dad"


@dataclass(frozen=True)
class Provider:
    name: str
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    scope: str = SCOPES

    @property
    def enabled(self) -> bool:
        parts = urlsplit(self.redirect_uri)
        local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
        safe_redirect = parts.scheme == "https" or (parts.scheme == "http" and local)
        return bool(self.client_id and self.client_secret and safe_redirect and parts.netloc and self.scope == SCOPES)


def google(*, client_id: str = "", client_secret: str = "", redirect_uri: str = "") -> Provider:
    """Google's OIDC web flow; no Gmail or offline access scope."""
    return Provider(
        "google", "https://accounts.google.com", "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token", "https://www.googleapis.com/oauth2/v3/certs",
        client_id, client_secret, redirect_uri,
    )


def microsoft(
    *, client_id: str = "", client_secret: str = "", redirect_uri: str = "", tenant: str = MICROSOFT_CONSUMERS,
) -> Provider:
    """A configured Entra tenant; consumers is the closed-by-default personal-account slot."""
    if not tenant or not all(char.isalnum() or char == "-" for char in tenant):
        raise ValueError("Invalid tenant")
    base = f"https://login.microsoftonline.com/{tenant}/v2.0"
    return Provider(
        "microsoft", base, f"{base}/authorize", f"{base}/token",
        f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
        client_id, client_secret, redirect_uri,
    )
