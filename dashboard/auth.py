"""Fail-closed dashboard configuration and Streamlit identity allowlist."""

from collections.abc import Mapping
from dataclasses import dataclass
import os


_REQUIRED_AUTH_FIELDS = ("redirect_uri", "cookie_secret")
_REQUIRED_PROVIDER_FIELDS = ("client_id", "client_secret", "server_metadata_url")
_MIN_COOKIE_SECRET_BYTES = 32


@dataclass(frozen=True)
class AuthConfig:
    environment: str
    mode: str
    bind_address: str
    allowed_emails: tuple[str, ...]

    def __post_init__(self):
        if self.environment not in ("development", "production"):
            raise ValueError("APP_ENVIRONMENT must be development or production")
        if self.mode not in ("disabled", "oidc"):
            raise ValueError("APP_AUTH_MODE must be disabled or oidc")
        allowed = tuple(email.strip().lower() for email in self.allowed_emails if email.strip())
        object.__setattr__(self, "allowed_emails", allowed)
        if self.mode == "disabled":
            if self.environment != "development" or self.bind_address not in ("127.0.0.1", "::1", "localhost"):
                raise ValueError("Disabled authentication requires development on loopback")
        elif not allowed:
            raise ValueError("OIDC requires ALLOWED_EMAILS")

    @classmethod
    def from_env(cls):
        return cls(
            environment=os.environ.get("APP_ENVIRONMENT", "production"),
            mode=os.environ.get("APP_AUTH_MODE", "oidc"),
            bind_address=os.environ.get("STREAMLIT_SERVER_ADDRESS", "127.0.0.1"),
            allowed_emails=tuple(os.environ.get("ALLOWED_EMAILS", "").split(",")),
        )


def authorize_email(email, allowed):
    return isinstance(email, str) and bool(email.strip()) and email.strip().lower() in (
        candidate.strip().lower() for candidate in allowed
    )


def validate_oidc_secrets(secrets) -> None:
    """Fail closed on the Streamlit 1.63 ``[auth]`` mapping without exposing values."""
    try:
        auth = secrets.get("auth")
        if not isinstance(auth, Mapping):
            raise ValueError
        provider = auth.get("default") if "default" in auth else auth
        if not isinstance(provider, Mapping):
            raise ValueError
        values = tuple(auth.get(field) for field in _REQUIRED_AUTH_FIELDS)
        values += tuple(provider.get(field) for field in _REQUIRED_PROVIDER_FIELDS)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError
        cookie_secret = auth.get("cookie_secret")
        if len(cookie_secret.encode("utf-8")) < _MIN_COOKIE_SECRET_BYTES:
            raise ValueError
    except Exception:
        # Never include a configured value or parser exception in browser-visible errors.
        raise ValueError("OIDC 认证配置无效") from None


def require_access(st, config: AuthConfig):
    # Revalidate before any return, including a caller-supplied configuration.
    validated = AuthConfig(config.environment, config.mode, config.bind_address, config.allowed_emails)
    if validated.mode == "disabled":
        # CLI flags override environment variables: check the effective listener too.
        AuthConfig(validated.environment, validated.mode, st.get_option("server.address"), ())
        return None
    validate_oidc_secrets(st.secrets)
    if not st.user.is_logged_in:
        if st.button("登录"):
            st.login()
        st.stop()
    email = getattr(st.user, "email", None)
    if not authorize_email(email, validated.allowed_emails):
        st.error("无权访问此应用")
        if st.button("退出登录"):
            st.logout()
        st.stop()
    return email.strip().lower()
