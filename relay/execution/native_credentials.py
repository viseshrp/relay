"""Bounded native credential-store adapter. Values travel through private pipes."""

from __future__ import annotations

import importlib
import json
import platform
import subprocess
import sys

from relay.errors import ConfigError


def credential(operation: str, reference: str, value: str | None = None) -> str | None:
    if operation not in {"get", "set", "delete"} or len(reference) > 512:
        message = "Invalid credential request."
        raise ConfigError(message)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "relay.execution.native_credentials"],
            input=json.dumps({"operation": operation, "reference": reference, "value": value}),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
            shell=False,
        )
        response = json.loads(result.stdout) if result.returncode == 0 else {}
        if not response.get("ok"):
            message = "The native credential store is unavailable or locked."
            raise ConfigError(message)
        return response.get("value")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        message = "The native credential store is unavailable or locked."
        raise ConfigError(message) from None


def _main() -> None:
    backends = {
        "Darwin": ("keyring.backends.macOS", "Keyring"),
        "Windows": ("keyring.backends.Windows", "WinVaultKeyring"),
        "Linux": ("keyring.backends.SecretService", "Keyring"),
    }
    try:
        request = json.loads(sys.stdin.read(131072))
        module, name = backends[platform.system()]
        backend = getattr(importlib.import_module(module), name)()
        service, reference = "Relay workflow secrets", request["reference"]
        value = None
        if request["operation"] == "get":
            value = backend.get_password(service, reference)
        elif request["operation"] == "set":
            backend.set_password(service, reference, request["value"])
        elif request["operation"] == "delete":
            backend.delete_password(service, reference)
        else:
            sys.stdout.write('{"ok": false}')
            sys.exit(1)
        sys.stdout.write(json.dumps({"ok": True, "value": value}))
    except Exception:
        # Native failures can contain account names or private values.
        sys.stdout.write('{"ok": false}')
        sys.exit(1)


if __name__ == "__main__":
    _main()
