"""Linux Secret Service helpers for Chromium-family browser cookies."""

from __future__ import annotations

import json
from pathlib import Path

import secretstorage

_SUPPORTED_BACKENDS = {"secret-service", "libsecret", "gnome-libsecret", "gnome"}
_SAFE_STORAGE_LABELS = {
    "chrome": "Chrome Safe Storage",
    "chromium": "Chromium Safe Storage",
    "brave": "Brave Safe Storage",
    "edge": "Microsoft Edge Safe Storage",
    "vivaldi": "Vivaldi Safe Storage",
    "opera": "Opera Safe Storage",
}


class SecretServiceError(RuntimeError):
    """Base class for Linux Secret Service lookup failures."""


class UnsupportedCookieBackendError(SecretServiceError):
    """Raised when Chromium is configured with an unsupported password backend."""

    def __init__(self, backend: str) -> None:
        self.backend = backend
        super().__init__(
            "unsupported Chromium cookie backend "
            f"'{backend}'; only Secret Service/libsecret is supported"
        )


class SecretServiceItemNotFoundError(SecretServiceError):
    """Raised when the expected Safe Storage entry is unavailable."""


def ensure_supported_backend(local_state_path: str | Path) -> str:
    """Return the normalized password backend or raise a typed unsupported error."""

    state = json.loads(Path(local_state_path).read_text(encoding="utf-8"))
    os_crypt = state.get("os_crypt", {})
    raw_backend = (
        os_crypt.get("password_store")
        or os_crypt.get("store")
        or os_crypt.get("backend")
        or "secret-service"
    )
    if not isinstance(raw_backend, str) or not raw_backend:
        raw_backend = "secret-service"

    backend = raw_backend.lower()
    if backend not in _SUPPORTED_BACKENDS:
        raise UnsupportedCookieBackendError(raw_backend)
    return backend


def get_secret_service_password(browser_id: str) -> str:
    """Return the Safe Storage password for a supported Chromium-family browser."""

    label = _SAFE_STORAGE_LABELS.get(browser_id)
    if label is None:
        raise SecretServiceItemNotFoundError(f"unsupported browser id '{browser_id}'")

    connection = secretstorage.dbus_init()
    collection = secretstorage.get_default_collection(connection)
    for item in collection.get_all_items():
        if item.get_label() != label:
            continue
        secret = item.get_secret().decode("utf-8")
        if secret:
            return secret
        break

    raise SecretServiceItemNotFoundError(f"Secret Service item '{label}' not found")
