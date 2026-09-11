"""Fail-closed dashboard configuration and Streamlit identity allowlist."""

from dataclasses import dataclass
import os


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


def require_access(st, config: AuthConfig):
    # Revalidate before any return, including a caller-supplied configuration.
    validated = AuthConfig(config.environment, config.mode, config.bind_address, config.allowed_emails)
    if validated.mode == "disabled":
        # CLI flags override environment variables: check the effective listener too.
        AuthConfig(validated.environment, validated.mode, st.get_option("server.address"), ())
        return None
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
