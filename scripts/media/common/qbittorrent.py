
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class QBittorrentError(RuntimeError):
    pass


def read_credentials(
    secret_file: Path,
) -> tuple[str, str]:
    if not secret_file.is_file():
        raise QBittorrentError(
            f"qBittorrent secret file not found: {secret_file}"
        )

    try:
        payload = json.loads(
            secret_file.read_text()
        )
    except (OSError, json.JSONDecodeError) as error:
        raise QBittorrentError(
            f"Unable to read {secret_file}: {error}"
        ) from error

    username = str(
        payload.get("username", "")
    ).strip()

    password = str(
        payload.get("password", "")
    )

    if not username or not password:
        raise QBittorrentError(
            f"Missing qBittorrent credentials in {secret_file}"
        )

    return username, password


class QBittorrentClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

        cookie_jar = http.cookiejar.CookieJar()

        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(
                cookie_jar
            )
        )

        self.headers = {
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "User-Agent": "homelab-cleanup/1.0",
        }

    def request(
        self,
        method: str,
        path: str,
        form: dict[str, Any] | None = None,
    ) -> bytes:
        data = None

        if form is not None:
            normalized = {
                key: (
                    json.dumps(value)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                for key, value in form.items()
            }

            data = urllib.parse.urlencode(
                normalized
            ).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=self.headers,
            method=method,
        )

        try:
            with self.opener.open(
                request,
                timeout=30,
            ) as response:
                return response.read()

        except urllib.error.HTTPError as error:
            body = error.read().decode(
                "utf-8",
                errors="replace",
            )

            raise QBittorrentError(
                f"{method} {path} failed with HTTP "
                f"{error.code}: {body}"
            ) from error

        except urllib.error.URLError as error:
            raise QBittorrentError(
                f"{method} {path} failed: {error.reason}"
            ) from error

    def login(self) -> None:
        body = self.request(
            "POST",
            "/api/v2/auth/login",
            {
                "username": self.username,
                "password": self.password,
            },
        ).decode("utf-8")

        if body and body != "Ok.":
            raise QBittorrentError(
                f"qBittorrent authentication failed: {body}"
            )

    def get_json(self, path: str) -> Any:
        body = self.request("GET", path)

        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise QBittorrentError(
                f"Invalid JSON returned by {path}"
            ) from error

    def post_form(
        self,
        path: str,
        form: dict[str, Any],
    ) -> None:
        self.request(
            "POST",
            path,
            form,
        )

    def post_multipart(
        self,
        path: str,
        fields: dict[str, Any],
        filename: str,
        payload: bytes,
        file_field: str = "torrents",
    ) -> None:
        """Post one in-memory file without putting a credentialed URL in qBit logs."""
        boundary = f"----homelab-{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    (
                        f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                    ).encode(),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        safe_filename = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{safe_filename}"\r\n'
                ).encode(),
                b"Content-Type: application/x-bittorrent\r\n\r\n",
                payload,
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=b"".join(chunks),
            headers={
                **self.headers,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                response.read()
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise QBittorrentError(
                f"POST {path} failed with HTTP {error.code}: {body}"
            ) from error
        except urllib.error.URLError as error:
            raise QBittorrentError(
                f"POST {path} failed: {error.reason}"
            ) from error
