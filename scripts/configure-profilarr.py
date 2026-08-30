#!/usr/bin/env python3

from __future__ import annotations

import argparse
import secrets
import sqlite3
import stat
import string
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "http://127.0.0.1:6868"
DEFAULT_CONTAINER = "profilarr"
DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_SECRET_FILE = (
    DEFAULT_STACK_DIR
    / "secrets"
    / "profilarr-admin.txt"
)
DEFAULT_DB_PATH = (
    DEFAULT_STACK_DIR
    / "config"
    / "profilarr"
    / "data"
    / "profilarr.db"
)
DEFAULT_USERNAME = "admin"


class ProfilarrError(RuntimeError):
    pass


class NoRedirect(
    urllib.request.HTTPRedirectHandler
):
    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        return None


def detect_public_url(
    fallback_url: str,
) -> str:
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
    ):
        return fallback_url

    addresses = result.stdout.split()

    if not addresses:
        return fallback_url

    parsed = urllib.parse.urlparse(fallback_url)
    host = addresses[0]
    netloc = host

    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"

    return urllib.parse.urlunparse(
        (
            parsed.scheme or "http",
            netloc,
            "",
            "",
            "",
            "",
        )
    )


def generate_password() -> str:
    alphabet = (
        string.ascii_letters
        + string.digits
        + "-_@#%"
    )

    return "".join(
        secrets.choice(alphabet)
        for _ in range(24)
    )


def setup_required(
    base_url: str,
) -> bool:
    opener = urllib.request.build_opener(
        NoRedirect()
    )
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/auth/setup",
        method="GET",
    )

    try:
        with opener.open(
            request,
            timeout=30,
        ) as response:
            return response.getcode() == 200
    except urllib.error.HTTPError as error:
        if error.code == 303:
            return False

        raise ProfilarrError(
            "Unable to inspect Profilarr setup state: "
            f"HTTP {error.code}"
        ) from error
    except urllib.error.URLError as error:
        raise ProfilarrError(
            f"Unable to reach Profilarr: {error}"
        ) from error


def create_initial_user(
    base_url: str,
    username: str,
    password: str,
) -> None:
    target = f"{base_url.rstrip('/')}/auth/setup"
    encoded = urllib.parse.urlencode(
        {
            "username": username,
            "password": password,
            "confirmPassword": password,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        target,
        data=encoded,
        headers={
            "Origin": base_url.rstrip("/"),
            "Referer": target,
            "Content-Type": (
                "application/x-www-form-urlencoded"
            ),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode(
            "utf-8",
            errors="replace",
        )
        raise ProfilarrError(
            "Unable to create initial Profilarr user: "
            f"HTTP {error.code}\n{body}"
        ) from error
    except urllib.error.URLError as error:
        raise ProfilarrError(
            "Unable to create initial Profilarr user: "
            f"{error}"
        ) from error


def hash_password_with_container(
    container: str,
    password: str,
) -> str:
    script = (
        'import { hash } from "jsr:@felix/bcrypt"; '
        "console.log(await hash(Deno.args[0]));"
    )

    try:
        result = subprocess.run(
            [
                "sudo",
                "docker",
                "exec",
                container,
                "deno",
                "eval",
                script,
                "--",
                password,
            ],
            capture_output=True,
            check=True,
            text=True,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
    ) as error:
        raise ProfilarrError(
            "Unable to generate Profilarr bcrypt hash."
        ) from error

    hashed = result.stdout.strip().splitlines()

    if not hashed:
        raise ProfilarrError(
            "Profilarr bcrypt helper returned no hash."
        )

    value = hashed[-1].strip()

    if not value.startswith("$2"):
        raise ProfilarrError(
            "Profilarr bcrypt helper returned an "
            "unexpected hash."
        )

    return value


def reset_admin_password(
    db_path: Path,
    username: str,
    password_hash: str,
) -> None:
    try:
        connection = sqlite3.connect(db_path)
    except sqlite3.Error as error:
        raise ProfilarrError(
            f"Unable to open Profilarr DB {db_path}: {error}"
        ) from error

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE users
            SET password_hash = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE username = ?
            """,
            (
                password_hash,
                username,
            ),
        )
        connection.commit()
    except sqlite3.Error as error:
        raise ProfilarrError(
            f"Unable to update Profilarr user: {error}"
        ) from error
    finally:
        connection.close()

    if cursor.rowcount != 1:
        raise ProfilarrError(
            f"Expected to update 1 Profilarr user named "
            f"{username}, updated {cursor.rowcount}."
        )


def write_credentials_file(
    secret_file: Path,
    username: str,
    password: str,
    public_url: str,
) -> None:
    secret_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    secret_file.write_text(
        "\n".join(
            (
                f"username={username}",
                f"password={password}",
                f"url={public_url}",
                "",
            )
        ),
        encoding="utf-8",
    )
    secret_file.chmod(
        stat.S_IRUSR | stat.S_IWUSR
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create or recover local Profilarr admin "
            "credentials without manual first-run setup."
        )
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
    )
    parser.add_argument(
        "--public-url",
        default=None,
    )
    parser.add_argument(
        "--container",
        default=DEFAULT_CONTAINER,
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
    )
    parser.add_argument(
        "--secret-file",
        type=Path,
        default=DEFAULT_SECRET_FILE,
    )
    parser.add_argument(
        "--username",
        default=DEFAULT_USERNAME,
    )
    parser.add_argument(
        "--force-reset",
        action="store_true",
        help=(
            "Reset the configured user's password even "
            "if the credentials file already exists."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    args = parser.parse_args()

    public_url = (
        args.public_url
        or detect_public_url(args.base_url)
    )

    if (
        args.secret_file.exists()
        and not args.force_reset
    ):
        print(
            f"PROFILE_CREDENTIALS_OK: "
            f"{args.secret_file}"
        )
        return 0

    password = generate_password()

    if args.dry_run:
        mode = (
            "setup"
            if setup_required(args.base_url)
            else "reset"
        )
        print(
            f"WOULD_{mode.upper()}_PROFILE_USER: "
            f"{args.username}"
        )
        print(
            f"WOULD_WRITE_CREDENTIALS: "
            f"{args.secret_file}"
        )
        print(
            f"PUBLIC_URL: {public_url}"
        )
        return 0

    if setup_required(args.base_url):
        create_initial_user(
            args.base_url,
            args.username,
            password,
        )
        write_credentials_file(
            args.secret_file,
            args.username,
            password,
            public_url,
        )
        print(
            f"PROFILE_USER_CREATED: {args.username}"
        )
        print(
            f"PROFILE_CREDENTIALS_FILE: "
            f"{args.secret_file}"
        )
        print(
            f"PUBLIC_URL: {public_url}"
        )
        return 0

    password_hash = hash_password_with_container(
        args.container,
        password,
    )
    reset_admin_password(
        args.db_path,
        args.username,
        password_hash,
    )
    write_credentials_file(
        args.secret_file,
        args.username,
        password,
        public_url,
    )
    print(
        f"PROFILE_USER_RESET: {args.username}"
    )
    print(
        f"PROFILE_CREDENTIALS_FILE: "
        f"{args.secret_file}"
    )
    print(
        f"PUBLIC_URL: {public_url}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
