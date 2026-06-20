"""Tests for the Linux Chromium cookie/session adapter."""

from __future__ import annotations

import base64
import importlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from claude_usage_tracker.browser.profiles import resolve_profile

FIXTURES = Path("tests/fixtures/browser_catalog")


def write_config(
    tmp_path: Path,
    *,
    browser_mode: str = "auto",
    profile_override: str | None = None,
) -> Path:
    lines = [f'browser_mode = "{browser_mode}"']
    if profile_override is not None:
        lines.append(f'profile_override = "{profile_override}"')
    lines.extend(
        [
            "refresh_interval_seconds = 60",
            "",
            "[tooltip]",
            "show_block = true",
            "show_week = true",
            "show_model_breakdown = true",
            "show_project_breakdown = true",
            "show_reset_times = true",
            "",
            "[notifications]",
            "enabled = true",
            "block_thresholds = [50, 75, 90]",
            "week_thresholds = [50, 75, 90]",
            "",
            "[settings_window]",
            "open_on_click = true",
            "remember_position = true",
            "remember_size = true",
            "stay_on_top = false",
            "",
        ]
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


def encrypt_cookie_value(prefix: str, password: str, plaintext: str) -> bytes:
    key = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=16,
        salt=b"saltysalt",
        iterations=1,
    ).derive(password.encode("utf-8"))

    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return prefix.encode("utf-8") + ciphertext


def create_sqlite_cookie_db(
    db_path: Path,
    *,
    password: str,
    prefix: str = "v10",
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE cookies (host_key TEXT, name TEXT, encrypted_value BLOB)"
        )
        connection.executemany(
            "INSERT INTO cookies (host_key, name, encrypted_value) VALUES (?, ?, ?)",
            [
                (
                    ".claude.ai",
                    "sessionKey",
                    encrypt_cookie_value(prefix, password, "session-from-dot-domain"),
                ),
                (
                    "claude.ai",
                    "cf_clearance",
                    encrypt_cookie_value(prefix, password, "clearance-from-root-domain"),
                ),
                (
                    ".example.com",
                    "ignored",
                    encrypt_cookie_value(prefix, password, "ignore-me"),
                ),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def write_local_state(path: Path, *, backend: str | None = None) -> None:
    payload = {"os_crypt": {"encrypted_key": "mock-linux-key"}}
    if backend is not None:
        payload["os_crypt"]["password_store"] = backend
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(
    ("suite", "browser_mode", "password", "expected"),
    [
        (
            "chrome_default",
            "chrome",
            "chrome-secret",
            {
                "sessionKey": "fixture-session-v10",
                "cf_clearance": "fixture-clearance-v10",
            },
        ),
        (
            "brave_default",
            "brave",
            "brave-secret",
            {
                "sessionKey": "fixture-session-v11",
                "cf_clearance": "fixture-clearance-v11",
            },
        ),
    ],
)
def test_reads_domain_cookies_from_supported_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    suite: str,
    browser_mode: str,
    password: str,
    expected: dict[str, str],
):
    cookies = importlib.import_module("claude_usage_tracker.browser.cookies")

    class FakeSecretService:
        @staticmethod
        def ensure_supported_backend(local_state_path: Path) -> str:
            return "secret-service"

        @staticmethod
        def get_secret_service_password(browser_id: str) -> str:
            return password

    config_path = write_config(tmp_path, browser_mode=browser_mode)
    resolved = resolve_profile(FIXTURES / suite, config_path)

    monkeypatch.setattr(cookies, "_secret_service_module", lambda: FakeSecretService)

    assert cookies.read_domain_cookies(resolved, domain="claude.ai") == expected


def test_copies_live_cookie_db_before_sqlite_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    cookies = importlib.import_module("claude_usage_tracker.browser.cookies")

    class FakeSecretService:
        @staticmethod
        def ensure_supported_backend(local_state_path: Path) -> str:
            return "gnome"

        @staticmethod
        def get_secret_service_password(browser_id: str) -> str:
            return "copied-secret"

    browser_root = tmp_path / "browser-root"
    write_local_state(browser_root / "google-chrome" / "Local State", backend="gnome")
    create_sqlite_cookie_db(
        browser_root / "google-chrome" / "Default" / "Cookies",
        password="copied-secret",
    )
    config_path = write_config(tmp_path, browser_mode="chrome")
    resolved = resolve_profile(browser_root, config_path)

    copied_from: list[Path] = []
    real_copy2 = shutil.copy2

    def tracking_copy2(
        source: str | Path,
        destination: str | Path,
        *,
        follow_symlinks: bool = True,
    ):
        copied_from.append(Path(source))
        return real_copy2(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(cookies, "_secret_service_module", lambda: FakeSecretService)
    monkeypatch.setattr(cookies.shutil, "copy2", tracking_copy2)

    assert cookies.read_domain_cookies(resolved, domain="claude.ai") == {
        "sessionKey": "session-from-dot-domain",
        "cf_clearance": "clearance-from-root-domain",
    }
    assert copied_from == [resolved.cookies_db_path]


def test_secret_service_reads_libsecret_password(monkeypatch: pytest.MonkeyPatch):
    secret_service = importlib.import_module("claude_usage_tracker.browser.secret_service")

    class FakeItem:
        def __init__(self, label: str, secret: str) -> None:
            self._label = label
            self._secret = secret

        def get_label(self) -> str:
            return self._label

        def get_secret(self) -> bytes:
            return self._secret.encode("utf-8")

    class FakeCollection:
        def get_all_items(self) -> list[FakeItem]:
            return [
                FakeItem("Unrelated", "ignore-me"),
                FakeItem("Chrome Safe Storage", "chrome-secret"),
            ]

    monkeypatch.setattr(secret_service.secretstorage, "dbus_init", lambda: object())
    monkeypatch.setattr(
        secret_service.secretstorage,
        "get_default_collection",
        lambda connection: FakeCollection(),
    )

    assert secret_service.get_secret_service_password("chrome") == "chrome-secret"


def test_unsupported_backend_degrades_cleanly(tmp_path: Path):
    cookies = importlib.import_module("claude_usage_tracker.browser.cookies")
    secret_service = importlib.import_module("claude_usage_tracker.browser.secret_service")

    browser_root = tmp_path / "browser-root"
    write_local_state(browser_root / "google-chrome" / "Local State", backend="kwallet5")
    cookie_blob = base64.b64encode(
        encrypt_cookie_value("v10", "unused-secret", "unused-session")
    ).decode("ascii")
    cookie_path = browser_root / "google-chrome" / "Default" / "Cookies.sqlite.json"
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "host_key": ".claude.ai",
                        "name": "sessionKey",
                        "encrypted_value": cookie_blob,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config_path = write_config(tmp_path, browser_mode="chrome")
    resolved = resolve_profile(browser_root, config_path)

    with pytest.raises(secret_service.UnsupportedCookieBackendError) as excinfo:
        cookies.read_domain_cookies(resolved, domain="claude.ai")

    assert excinfo.value.backend == "kwallet5"
    assert "kwallet5" in str(excinfo.value)
    assert "unused-session" not in str(excinfo.value)
