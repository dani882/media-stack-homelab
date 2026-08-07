from __future__ import annotations

import json
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class ArrError(RuntimeError):
    pass


def read_api_key(config_file: Path) -> str:
    if not config_file.is_file():
        raise ArrError(
            f"Configuration file not found: {config_file}"
        )

    try:
        root = ET.parse(config_file).getroot()
    except (ET.ParseError, OSError) as error:
        raise ArrError(
            f"Unable to read {config_file}: {error}"
        ) from error

    api_key = root.findtext("ApiKey", "").strip()

    if not api_key:
        raise ArrError(
            f"ApiKey was not found in {config_file}"
        )

    return api_key


class ArrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-Api-Key": api_key,
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
    ) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}/api/v3{path}",
            headers=self.headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=60,
            ) as response:
                body = response.read()

                if not body:
                    return None

                return json.loads(body)

        except urllib.error.HTTPError as error:
            body = error.read().decode(
                "utf-8",
                errors="replace",
            )

            raise ArrError(
                f"{method} {path} failed with HTTP "
                f"{error.code}: {body}"
            ) from error

        except urllib.error.URLError as error:
            raise ArrError(
                f"{method} {path} failed: {error.reason}"
            ) from error

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def delete(self, path: str) -> None:
        self.request("DELETE", path)
