"""OIDC adapters for real, explicitly enabled account sign-in."""

from nabiz.console.identity.oidc import (
    AuthorizationRequest,
    Identity,
    LoginClosed,
    OidcClient,
    OidcError,
    clear_login_cookie,
    set_login_cookie,
)
from nabiz.console.identity.providers import Provider, google, microsoft

__all__ = [
    "AuthorizationRequest", "Identity", "LoginClosed", "OidcClient", "OidcError", "Provider",
    "clear_login_cookie", "google", "microsoft", "set_login_cookie",
]
