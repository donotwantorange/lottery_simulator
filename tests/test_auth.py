from dataclasses import FrozenInstanceError
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dashboard.auth import AuthConfig, authorize_email, require_access


class Stopped(Exception):
    pass


class StreamlitBoundary:
    """Only UI/session effects are substituted; the access gate remains real."""

    def __init__(self, logged_in=False, email=None, clicked=False, address="127.0.0.1"):
        self.user = SimpleNamespace(is_logged_in=logged_in, email=email)
        self.clicked = clicked
        self.address = address
        self.buttons = []
        self.errors = []
        self.login_calls = 0
        self.logout_calls = 0

    def get_option(self, name):
        if name != "server.address":
            raise AssertionError(name)
        return self.address

    def button(self, label):
        self.buttons.append(label)
        return self.clicked

    def error(self, message):
        self.errors.append(message)

    def login(self):
        self.login_calls += 1

    def logout(self):
        self.logout_calls += 1

    def stop(self):
        raise Stopped


class AuthConfigTests(unittest.TestCase):
    def test_production_disabled_raises(self):
        with self.assertRaises(ValueError):
            AuthConfig("production", "disabled", "127.0.0.1", ())

    def test_oidc_without_allowed_emails_raises(self):
        for allowed in ((), (" ",)):
            with self.subTest(allowed=allowed), self.assertRaises(ValueError):
                AuthConfig("production", "oidc", "0.0.0.0", allowed)

    def test_development_disabled_public_bind_raises(self):
        for address in ("0.0.0.0", "::", "192.0.2.1", "", None):
            with self.subTest(address=address), self.assertRaises(ValueError):
                AuthConfig("development", "disabled", address, ())

    def test_development_disabled_loopback_passes(self):
        config = AuthConfig("development", "disabled", "127.0.0.1", ())
        self.assertIsNone(require_access(StreamlitBoundary(), config))

    def test_unknown_environment_and_mode_raise(self):
        for environment, mode in (("staging", "oidc"), ("production", "none")):
            with self.subTest(environment=environment, mode=mode), self.assertRaises(ValueError):
                AuthConfig(environment, mode, "127.0.0.1", ("owner@example.com",))

    def test_config_cannot_be_mutated_after_validation(self):
        config = AuthConfig("production", "oidc", "0.0.0.0", ("owner@example.com",))
        with self.assertRaises(FrozenInstanceError):
            config.mode = "disabled"

    def test_from_env_normalizes_allowlist(self):
        with patch.dict(os.environ, {
            "APP_ENVIRONMENT": "production", "APP_AUTH_MODE": "oidc",
            "STREAMLIT_SERVER_ADDRESS": "0.0.0.0",
            "ALLOWED_EMAILS": " OWNER@Example.COM , , second@example.com ",
        }, clear=True):
            config = AuthConfig.from_env()
        self.assertEqual(config.allowed_emails, ("owner@example.com", "second@example.com"))
        self.assertEqual(config.bind_address, "0.0.0.0")

    def test_missing_environment_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            AuthConfig.from_env()

    def test_development_from_env_defaults_to_loopback(self):
        with patch.dict(os.environ, {
            "APP_ENVIRONMENT": "development", "APP_AUTH_MODE": "disabled",
        }, clear=True):
            config = AuthConfig.from_env()
        self.assertEqual(config.bind_address, "127.0.0.1")
        self.assertIsNone(require_access(StreamlitBoundary(), config))

    def test_email_comparison_trims_and_lowercases(self):
        self.assertTrue(authorize_email(" Owner@EXAMPLE.com ", (" OWNER@example.COM ",)))

    def test_unknown_or_missing_email_fails(self):
        for email in ("unknown@example.com", "owner@example.com.evil", "", None, 123):
            with self.subTest(email=email):
                self.assertFalse(authorize_email(email, ("owner@example.com",)))
        self.assertFalse(authorize_email(" ", (" ",)))


class AccessGateTests(unittest.TestCase):
    def setUp(self):
        self.config = AuthConfig("production", "oidc", "0.0.0.0", ("owner@example.com",))

    def test_logged_out_renders_one_login_button_and_stops(self):
        for clicked in (False, True):
            with self.subTest(clicked=clicked):
                st = StreamlitBoundary(clicked=clicked)
                with self.assertRaises(Stopped):
                    require_access(st, self.config)
                self.assertEqual(len(st.buttons), 1)
                self.assertEqual(st.login_calls, int(clicked))
                self.assertEqual(st.logout_calls, 0)

    def test_unknown_email_renders_denial_logout_and_stops(self):
        for email in (None, "unknown@example.com"):
            for clicked in (False, True):
                with self.subTest(email=email, clicked=clicked):
                    st = StreamlitBoundary(True, email, clicked)
                    with self.assertRaises(Stopped):
                        require_access(st, self.config)
                    self.assertEqual(st.errors, ["无权访问此应用"])
                    self.assertEqual(len(st.buttons), 1)
                    self.assertEqual(st.logout_calls, int(clicked))
                    self.assertEqual(st.login_calls, 0)

    def test_allowed_user_returns_normalized_email_without_reading_tokens(self):
        class Identity:
            is_logged_in = True
            email = " OWNER@Example.COM "

            @property
            def tokens(self):
                raise AssertionError("tokens must not be read")

        st = StreamlitBoundary()
        st.user = Identity()
        self.assertEqual(require_access(st, self.config), "owner@example.com")
        self.assertEqual(st.buttons, [])

    def test_disabled_gate_rejects_actual_public_bind(self):
        config = AuthConfig("development", "disabled", "127.0.0.1", ())
        for address in ("0.0.0.0", "::", None):
            with self.subTest(address=address), self.assertRaises(ValueError):
                require_access(StreamlitBoundary(address=address), config)


if __name__ == "__main__":
    unittest.main()
