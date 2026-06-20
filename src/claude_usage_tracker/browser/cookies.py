"""Linux Chromium cookie reading and decryption helpers."""

from __future__ import annotations

import base64
import importlib
import json
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from claude_usage_tracker.browser.profiles import ResolvedProfile


class CookieReadError(RuntimeError):
    """Base class for Chromium cookie-reading failures."""


class CookieDecryptionError(CookieReadError):
    """Raised when a cookie payload cannot be decrypted as supported Linux Chromium data."""


def read_domain_cookies(
    profile: ResolvedProfile,
    *,
    domain: str = "claude.ai",
) -> dict[str, str]:
    """Copy the cookies DB aside, decrypt supported domain cookies, and return name/value pairs."""

    secret_service = _secret_service_module()
    secret_service.ensure_supported_backend(profile.local_state_path)
    password = secret_service.get_secret_service_password(profile.browser_id)

    with tempfile.TemporaryDirectory(prefix="claude-usage-tracker-cookies-") as temp_dir:
        copied_db_path = Path(temp_dir) / profile.cookies_db_path.name
        shutil.copy2(profile.cookies_db_path, copied_db_path)

        return {
            name: _decrypt_cookie_value(encrypted_value, password)
            for name, encrypted_value in _iter_domain_cookie_rows(copied_db_path, domain)
        }


def _secret_service_module():
    return importlib.import_module("claude_usage_tracker.browser.secret_service")


def _iter_domain_cookie_rows(path: Path, domain: str) -> Iterator[tuple[str, bytes]]:
    if path.suffix == ".json":
        yield from _iter_fixture_cookie_rows(path, domain)
        return

    connection = sqlite3.connect(path)
    try:
        cursor = connection.execute(
            "SELECT name, encrypted_value FROM cookies WHERE host_key = ? OR host_key = ?",
            (domain, f".{domain}"),
        )
        for name, encrypted_value in cursor.fetchall():
            yield str(name), bytes(encrypted_value)
    finally:
        connection.close()


def _iter_fixture_cookie_rows(path: Path, domain: str) -> Iterator[tuple[str, bytes]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for cookie in payload.get("cookies", []):
        host_key = cookie.get("host_key")
        if host_key not in {domain, f".{domain}"}:
            continue
        encrypted_value = cookie.get("encrypted_value")
        if not isinstance(encrypted_value, str):
            continue
        yield str(cookie.get("name", "")), base64.b64decode(encrypted_value)


def _decrypt_cookie_value(encrypted_value: bytes, password: str) -> str:
    if len(encrypted_value) <= 3:
        raise CookieDecryptionError("cookie blob too short")

    prefix = encrypted_value[:3].decode("utf-8", errors="replace")
    if prefix not in {"v10", "v11"}:
        raise CookieDecryptionError(f"unsupported cookie prefix '{prefix}'")

    key = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=16,
        salt=b"saltysalt",
        iterations=1,
    ).derive(password.encode("utf-8"))
    cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
    decryptor = cipher.decryptor()
    padded = decryptor.update(encrypted_value[3:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()

    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError:
        if len(plaintext) <= 32:
            raise CookieDecryptionError("cookie plaintext is not valid UTF-8") from None
        try:
            return plaintext[32:].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CookieDecryptionError("cookie plaintext is not valid UTF-8") from exc
