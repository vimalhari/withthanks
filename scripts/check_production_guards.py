from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ENTRYPOINT_PATH = ROOT_DIR / "entrypoint.sh"
PYTHON_EXECUTABLE = sys.executable
IMPORT_SETTINGS_COMMAND = [PYTHON_EXECUTABLE, "-c", "import withthanks.settings"]


def run_check(
    name: str,
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    expect_success: bool,
    expected_output: str | None = None,
) -> None:
    result = subprocess.run(
        command,
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{result.stdout}{result.stderr}"

    if expect_success and result.returncode != 0:
        raise SystemExit(f"{name} failed unexpectedly:\n{output}")

    if not expect_success and result.returncode == 0:
        raise SystemExit(f"{name} unexpectedly succeeded.")

    if expected_output and expected_output not in output:
        raise SystemExit(
            f"{name} did not emit the expected message: {expected_output!r}\nActual output:\n{output}"
        )

    print(f"PASS: {name}")


def build_valid_production_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DJANGO_ENV": "production",
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "test-secret-key",
            "ALLOWED_HOSTS": "app.example.com",
            "CSRF_TRUSTED_ORIGINS": "https://app.example.com",
            "DEFAULT_FROM_EMAIL": "No Reply <no-reply@app.example.com>",
            "SERVER_BASE_URL": "https://app.example.com",
        }
    )
    return env


def main() -> None:
    run_check(
        "entrypoint shell syntax",
        ["bash", "-n", str(ENTRYPOINT_PATH)],
        expect_success=True,
    )

    valid_env = build_valid_production_env()
    run_check(
        "production settings import with valid environment",
        IMPORT_SETTINGS_COMMAND,
        env=valid_env,
        expect_success=True,
    )

    missing_env_checks = {
        "DJANGO_SECRET_KEY": "DJANGO_SECRET_KEY environment variable must be set.",
        "ALLOWED_HOSTS": "ALLOWED_HOSTS must be set in production.",
        "CSRF_TRUSTED_ORIGINS": "CSRF_TRUSTED_ORIGINS must be set in production.",
        "DEFAULT_FROM_EMAIL": "DEFAULT_FROM_EMAIL must be set in production.",
        "SERVER_BASE_URL": "SERVER_BASE_URL must be set in production.",
    }
    for variable, expected_message in missing_env_checks.items():
        env = valid_env.copy()
        env.pop(variable, None)
        run_check(
            f"production settings reject missing {variable}",
            IMPORT_SETTINGS_COMMAND,
            env=env,
            expect_success=False,
            expected_output=expected_message,
        )

    debug_env = valid_env.copy()
    debug_env["DJANGO_DEBUG"] = "true"
    run_check(
        "production settings reject DJANGO_DEBUG=true",
        IMPORT_SETTINGS_COMMAND,
        env=debug_env,
        expect_success=False,
        expected_output="DJANGO_DEBUG must be false in production.",
    )

    insecure_csrf_env = valid_env.copy()
    insecure_csrf_env["CSRF_TRUSTED_ORIGINS"] = "http://app.example.com"
    run_check(
        "production settings reject insecure CSRF origins",
        IMPORT_SETTINGS_COMMAND,
        env=insecure_csrf_env,
        expect_success=False,
        expected_output="CSRF_TRUSTED_ORIGINS must use https in production.",
    )

    insecure_base_url_env = valid_env.copy()
    insecure_base_url_env["SERVER_BASE_URL"] = "http://app.example.com"
    run_check(
        "production settings reject insecure server base URL",
        IMPORT_SETTINGS_COMMAND,
        env=insecure_base_url_env,
        expect_success=False,
        expected_output="SERVER_BASE_URL must be a valid https URL in production.",
    )


if __name__ == "__main__":
    main()
