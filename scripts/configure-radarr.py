#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT_FOLDERS = {
    "movies": "/media/Movies",
    "kids": "/media/Kids Movies",
}


class RadarrError(RuntimeError):
    pass


class RadarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = None

        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}/api/v3{path}",
            data=body,
            headers=self.headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=60,
            ) as response:
                content = response.read()

                if not content:
                    return None

                return json.loads(content)

        except urllib.error.HTTPError as error:
            response_body = error.read().decode(
                "utf-8",
                errors="replace",
            )

            raise RadarrError(
                f"{method} {path} failed with HTTP "
                f"{error.code}: {response_body}"
            ) from error

        except urllib.error.URLError as error:
            raise RadarrError(
                f"{method} {path} failed: {error.reason}"
            ) from error

        except (ConnectionError, OSError) as error:
            raise RadarrError(
                f"{method} {path} failed: {error}"
            ) from error


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Perform Radarr movie maintenance tasks."
    )

    parser.add_argument(
        "--stack-dir",
        default="/volume1/docker/media-stack",
    )

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:7878",
    )

    parser.add_argument(
        "--movie-id",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--destination",
        required=True,
        choices=sorted(ROOT_FOLDERS),
        help="Destination root: movies or kids.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the intended move without changing Radarr.",
    )

    return parser.parse_args()


def read_api_key(config_file: Path) -> str:
    try:
        text = config_file.read_text()
    except OSError as error:
        raise RadarrError(
            f"Unable to read {config_file}: {error}"
        ) from error

    match = re.search(
        r"<ApiKey>([^<]+)</ApiKey>",
        text,
    )

    if not match:
        raise RadarrError(
            f"Unable to find ApiKey in {config_file}"
        )

    return match.group(1)


def move_movie(
    client: RadarrClient,
    movie_id: int,
    destination: str,
    dry_run: bool,
) -> None:
    movie = client.request(
        "GET",
        f"/movie/{movie_id}",
    )

    current_path = Path(movie["path"])
    target_root = Path(ROOT_FOLDERS[destination])
    target_path = target_root / current_path.name

    print(f"Movie: {movie['title']} ({movie['year']})")
    print(f"Current path: {current_path}")
    print(f"Target path:  {target_path}")

    if (
        movie.get("rootFolderPath") == str(target_root)
        and current_path == target_path
    ):
        print("Movie root folder is already correct.")
        return

    if dry_run:
        print("WOULD MOVE MOVIE")
        return

    updated = dict(movie)
    updated["rootFolderPath"] = str(target_root)
    updated["path"] = str(target_path)

    query = urllib.parse.urlencode(
        {"moveFiles": "true"}
    )

    result = client.request(
        "PUT",
        f"/movie/{movie_id}?{query}",
        updated,
    )

    print("MOVED MOVIE")
    print(f"New path: {result['path']}")


def main() -> int:
    arguments = parse_arguments()
    stack_dir = Path(arguments.stack_dir)

    try:
        api_key = read_api_key(
            stack_dir / "config/radarr/config.xml"
        )

        client = RadarrClient(
            arguments.url,
            api_key,
        )

        move_movie(
            client,
            arguments.movie_id,
            arguments.destination,
            arguments.dry_run,
        )

        return 0

    except RadarrError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
