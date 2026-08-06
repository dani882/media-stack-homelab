from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ServarrError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppConfig:
    name: str
    base_url: str
    config_file: Path
    data_path: Path


class ApiClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
    ) -> Any:
        data = None

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=self.headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else None

        except urllib.error.HTTPError as error:
            body = error.read().decode(
                "utf-8",
                errors="replace",
            )
            raise ServarrError(
                f"{method} {path} failed with HTTP "
                f"{error.code}:\n{body}"
            ) from error

        except urllib.error.URLError as error:
            raise ServarrError(
                f"{method} {path} failed: {error.reason}"
            ) from error

        except (ConnectionError, OSError) as error:
            raise ServarrError(
                f"{method} {path} failed: {error}"
            ) from error


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ServarrError(
            f"Unable to read {path}: {error}"
        ) from error


def read_api_key(config_file: Path) -> str:
    try:
        root = ET.parse(config_file).getroot()
    except (ET.ParseError, OSError) as error:
        raise ServarrError(
            f"Unable to read {config_file}: {error}"
        ) from error

    element = root.find("ApiKey")

    if element is None or not element.text:
        raise ServarrError(
            f"No ApiKey found in {config_file}"
        )

    return element.text.strip()


def wait_until_ready(
    client: ApiClient,
    app_name: str,
    attempts: int = 30,
    delay_seconds: int = 2,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            status = client.request(
                "GET",
                "/api/v3/system/status",
            )
            print(
                f"{app_name} is ready. "
                f"Version: {status.get('version', 'unknown')}"
            )
            return

        except ServarrError:
            if attempt == attempts:
                raise

            time.sleep(delay_seconds)
