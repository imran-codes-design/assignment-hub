import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PROBE = """
import json
import django
django.setup()
from django.conf import settings
print(json.dumps({
    "debug": settings.DEBUG,
    "secret_key_set": bool(settings.SECRET_KEY),
    "allowed_hosts": settings.ALLOWED_HOSTS,
    "ssl_redirect": settings.SECURE_SSL_REDIRECT,
    "session_cookie_secure": settings.SESSION_COOKIE_SECURE,
    "csrf_cookie_secure": settings.CSRF_COOKIE_SECURE,
    "hsts_seconds": settings.SECURE_HSTS_SECONDS,
    "hsts_include_subdomains": settings.SECURE_HSTS_INCLUDE_SUBDOMAINS,
    "hsts_preload": settings.SECURE_HSTS_PRELOAD,
    "email_backend": settings.EMAIL_BACKEND,
    "email_port": settings.EMAIL_PORT,
    "email_use_tls": settings.EMAIL_USE_TLS,
    "email_use_ssl": settings.EMAIL_USE_SSL,
    "email_user_set": bool(settings.EMAIL_HOST_USER),
    "email_password_set": bool(settings.EMAIL_HOST_PASSWORD),
}))
"""


class EnvironmentSettingsTests(SimpleTestCase):
    def run_settings_probe(self, **configured):
        environment = os.environ.copy()
        setting_names = {
            "DJANGO_SETTINGS_MODULE",
            "SECRET_KEY",
            "DEBUG",
            "ALLOWED_HOSTS",
            "SECURE_SSL_REDIRECT",
            "SESSION_COOKIE_SECURE",
            "CSRF_COOKIE_SECURE",
            "SECURE_HSTS_SECONDS",
            "SECURE_HSTS_INCLUDE_SUBDOMAINS",
            "SECURE_HSTS_PRELOAD",
            "EMAIL_BACKEND",
            "EMAIL_HOST",
            "EMAIL_PORT",
            "EMAIL_HOST_USER",
            "EMAIL_HOST_PASSWORD",
            "EMAIL_USE_TLS",
            "EMAIL_USE_SSL",
            "DEFAULT_FROM_EMAIL",
        }
        for name in setting_names:
            environment.pop(name, None)
        environment.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "PYTHONDONTWRITEBYTECODE": "1",
                **configured,
            }
        )
        return subprocess.run(
            [sys.executable, "-c", SETTINGS_PROBE],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_production_requires_secret_key(self):
        result = self.run_settings_probe(DEBUG="false")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY must be set", result.stderr)

    def test_production_rejects_wildcard_allowed_hosts(self):
        result = self.run_settings_probe(
            DEBUG="false",
            SECRET_KEY="test-only-secret-key-not-a-real-credential",
            ALLOWED_HOSTS="*",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ALLOWED_HOSTS must not contain", result.stderr)

    def test_development_defaults_remain_usable_over_http(self):
        result = self.run_settings_probe(DEBUG="true")

        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout)
        self.assertTrue(settings["debug"])
        self.assertTrue(settings["secret_key_set"])
        self.assertEqual(
            settings["allowed_hosts"],
            ["localhost", "127.0.0.1", "[::1]"],
        )
        self.assertFalse(settings["ssl_redirect"])
        self.assertFalse(settings["session_cookie_secure"])
        self.assertFalse(settings["csrf_cookie_secure"])
        self.assertEqual(settings["hsts_seconds"], 0)
        self.assertEqual(
            settings["email_backend"],
            "django.core.mail.backends.console.EmailBackend",
        )

    def test_production_security_and_email_environment_are_applied(self):
        result = self.run_settings_probe(
            DEBUG="false",
            SECRET_KEY="test-only-secret-key-not-a-real-credential",
            ALLOWED_HOSTS="example.test,api.example.test",
            SECURE_SSL_REDIRECT="true",
            SESSION_COOKIE_SECURE="true",
            CSRF_COOKIE_SECURE="true",
            SECURE_HSTS_SECONDS="3600",
            SECURE_HSTS_INCLUDE_SUBDOMAINS="true",
            SECURE_HSTS_PRELOAD="true",
            EMAIL_HOST="smtp.example.test",
            EMAIL_PORT="587",
            EMAIL_HOST_USER="test-user",
            EMAIL_HOST_PASSWORD="test-only-password",
            EMAIL_USE_TLS="true",
            EMAIL_USE_SSL="false",
            DEFAULT_FROM_EMAIL="noreply@example.test",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout)
        self.assertFalse(settings["debug"])
        self.assertEqual(
            settings["allowed_hosts"],
            ["example.test", "api.example.test"],
        )
        self.assertTrue(settings["ssl_redirect"])
        self.assertTrue(settings["session_cookie_secure"])
        self.assertTrue(settings["csrf_cookie_secure"])
        self.assertEqual(settings["hsts_seconds"], 3600)
        self.assertTrue(settings["hsts_include_subdomains"])
        self.assertTrue(settings["hsts_preload"])
        self.assertEqual(
            settings["email_backend"],
            "django.core.mail.backends.smtp.EmailBackend",
        )
        self.assertEqual(settings["email_port"], 587)
        self.assertTrue(settings["email_use_tls"])
        self.assertFalse(settings["email_use_ssl"])
        self.assertTrue(settings["email_user_set"])
        self.assertTrue(settings["email_password_set"])
        self.assertNotIn("test-only-password", result.stdout)
