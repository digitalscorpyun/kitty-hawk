"""Offline checks for watsonx_client.py's env-var self-healing fallback
(_load_missing_from_user_registry, added 2026-08-24 to diagnose an env-var
propagation stall in a long-lived launcher process). No live provider call: the
module-level REQUIRED_VARS fail-fast is satisfied with dummy credentials
before import, and the registry itself is never touched -- `winreg` is
swapped for a fake in sys.modules so these checks work identically whether
or not the real Windows User-scope WATSONX_* values happen to be present."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(name, "test-dummy")
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import watsonx_client as wc  # noqa: E402


class _FakeKey:
    def __init__(self, values: dict[str, str]):
        self._values = values

    def __enter__(self) -> "_FakeKey":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class _FakeWinreg(types.ModuleType):
    def __init__(self, values: dict[str, str], *, raise_on_open: bool = False):
        super().__init__("winreg")
        self.HKEY_CURRENT_USER = object()
        self._values = values
        self._raise_on_open = raise_on_open
        self.opened = False

    def OpenKey(self, hive, subkey):  # noqa: N802 - matches real winreg's API name
        self.opened = True
        if self._raise_on_open:
            raise OSError("registry unavailable (fake, for test)")
        return _FakeKey(self._values)

    def QueryValueEx(self, key, name):  # noqa: N802
        if name in key._values:
            return key._values[name], 1
        raise FileNotFoundError(name)


def _install_fake_winreg(values: dict[str, str], *, raise_on_open: bool = False) -> tuple[_FakeWinreg, object | None]:
    original = sys.modules.get("winreg")
    fake = _FakeWinreg(values, raise_on_open=raise_on_open)
    sys.modules["winreg"] = fake
    return fake, original


def _restore_winreg(original: object | None) -> None:
    if original is not None:
        sys.modules["winreg"] = original
    else:
        sys.modules.pop("winreg", None)


def main() -> None:
    checks = 0

    def check(value: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not value:
            raise AssertionError(label)

    # --- A var genuinely absent from both process env and the registry
    # is reported still-missing, no crash, nothing added to os.environ. ---
    # Force win32 platform for registry-dependent checks so they pass cross-platform (Linux CI)
    _orig_platform = sys.platform
    try:
        sys.platform = "win32"
        fake, original = _install_fake_winreg({})
        try:
            os.environ.pop("WATSONX_TEST_ABSENT_VAR", None)
            still_missing = wc._load_missing_from_user_registry(["WATSONX_TEST_ABSENT_VAR"])
            check(still_missing == ["WATSONX_TEST_ABSENT_VAR"], "a var absent from the registry was not reported still-missing")
            check("WATSONX_TEST_ABSENT_VAR" not in os.environ, "a var absent from the registry was written to os.environ anyway")
            check(fake.opened, "the fallback never attempted to open the registry key at all")
        finally:
            _restore_winreg(original)

        # --- The KH-01 scenario itself: a var present in the User-scope
        # registry but absent from this process's inherited environment gets
        # self-healed into os.environ, and a var genuinely absent stays
        # reported missing alongside it. ---
        fake, original = _install_fake_winreg({"WATSONX_TEST_FAKE_VAR": "resolved-from-registry"})
        try:
            os.environ.pop("WATSONX_TEST_FAKE_VAR", None)
            os.environ.pop("WATSONX_TEST_ABSENT_VAR", None)
            still_missing = wc._load_missing_from_user_registry(["WATSONX_TEST_FAKE_VAR", "WATSONX_TEST_ABSENT_VAR"])
            check(still_missing == ["WATSONX_TEST_ABSENT_VAR"], "the resolvable var was not removed from the still-missing list")
            check(os.environ.get("WATSONX_TEST_FAKE_VAR") == "resolved-from-registry", "the resolvable var was not populated into os.environ")
        finally:
            os.environ.pop("WATSONX_TEST_FAKE_VAR", None)
            _restore_winreg(original)

        # --- A registry read failure (key missing entirely, permissions, etc.)
        # degrades to "still missing" rather than crashing the caller. ---
        fake, original = _install_fake_winreg({}, raise_on_open=True)
        try:
            still_missing = wc._load_missing_from_user_registry(["WATSONX_TEST_ABSENT_VAR"])
            check(still_missing == ["WATSONX_TEST_ABSENT_VAR"], "an OSError opening the registry key was not handled gracefully")
        finally:
            _restore_winreg(original)
    finally:
        sys.platform = _orig_platform

    # --- Off Windows, the registry is never touched at all. ---
    fake, original = _install_fake_winreg({"WATSONX_TEST_FAKE_VAR": "should-never-be-read"})
    original_platform = sys.platform
    try:
        sys.platform = "linux"
        still_missing = wc._load_missing_from_user_registry(["WATSONX_TEST_FAKE_VAR"])
        check(still_missing == ["WATSONX_TEST_FAKE_VAR"], "non-Windows path did not leave the var reported missing")
        check(not fake.opened, "non-Windows path still attempted to open the Windows registry")
    finally:
        sys.platform = original_platform
        _restore_winreg(original)

    # --- REQUIRED_VARS/the fail-fast guard's own shape, unrelated to the
    # fallback function itself, still holds after this change. ---
    check(wc.REQUIRED_VARS == ["WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"], "REQUIRED_VARS changed shape")

    # --- KH-03 provider-boundary hardening: bounded transport configuration
    # is explicit and does not disable TLS verification or substitute another
    # provider. This constructs the REAL WatsonXClient class and REAL
    # manifest/provider plumbing through the explicit offline seam
    # (initialize_sdk=False) -- it does not claim real IBM SDK object
    # construction, which initialize_sdk=False deliberately skips. ask() is
    # never called here. ---
    client = wc.WatsonXClient(initialize_sdk=False)
    check(client.initialize_sdk is False, "offline-constructed client did not record initialize_sdk=False")
    check(client.creds is None, "offline-constructed client fabricated a credentials object instead of leaving it None")
    check(client.http_timeout.connect == 10.0, "watsonx connect timeout is not explicitly bounded at 10 seconds")
    check(client.http_timeout.read == 150.0, "watsonx read timeout is not explicitly bounded at 150 seconds")
    check(client.http_timeout.write == 30.0 and client.http_timeout.pool == 30.0, "watsonx write/pool timeouts are not explicitly bounded at 30 seconds")
    check(client.http_config.timeout is client.http_timeout, "HttpClientConfig does not carry the configured timeout")
    check(client.http_config.limits is client.http_limits, "HttpClientConfig does not carry the configured connection limits")

    # --- Fail-closed, not fail-silent: an offline-constructed client that
    # reaches an unpatched ask() must raise, never silently no-op or return a
    # fabricated response, and must never touch the network to find out. ---
    try:
        client.ask("this must never reach a provider")
        check(False, "ask() on an offline-constructed (initialize_sdk=False) client did not raise")
    except wc.WatsonXOfflineConstructionError:
        check(True, "ask() on an offline-constructed client correctly raised WatsonXOfflineConstructionError")

    # --- The default, production construction path (initialize_sdk=True)
    # must itself fail closed with a clear, intelligible error when the IBM
    # SDK is not installed -- never a bare TypeError from a None SDK class,
    # and never a silent substitute provider. This environment has no
    # ibm-watsonx-ai installed (public offline dependency set), so this
    # exercises the real absent-SDK path, not a simulation of it. ---
    if wc.Credentials is None:
        try:
            wc.WatsonXClient()
            check(False, "default construction (initialize_sdk=True) did not raise with the IBM SDK absent")
        except wc.WatsonXSDKUnavailableError:
            check(True, "default construction correctly raised WatsonXSDKUnavailableError with the IBM SDK absent")
    else:
        print("NOTE: ibm-watsonx-ai is installed in this environment -- the absent-SDK fail-closed path is not exercised here.")

    print(f"All {checks} watsonx_client checks passed.")


if __name__ == "__main__":
    main()
