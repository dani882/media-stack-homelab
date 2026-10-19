#!/usr/bin/env python3

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_DUCKDNS_CONFIG = Path("/volume1/docker/duckdns/duckdns.env")
DEFAULT_SEERR_URL = "http://127.0.0.1:5055"
DEFAULT_JELLYFIN_URL = "http://127.0.0.1:8899"
DOMAIN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class PublicAccessError(RuntimeError):
    pass


def read_key_value_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise PublicAccessError(f"Unable to read configuration: {error}") from error

    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PublicAccessError("Invalid key/value configuration line.")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in values:
            raise PublicAccessError("Invalid or duplicate configuration key.")
        values[key] = value.strip()
    return values


def validate_domain(value: str) -> str:
    domain = value.strip().lower()
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise PublicAccessError("Invalid DuckDNS domain.")
    return domain


def duckdns_domain(path: Path) -> str:
    values = read_key_value_file(path)
    domains = values.get("DUCKDNS_DOMAINS", "").split(",")
    if not domains or not domains[0].strip():
        raise PublicAccessError("DuckDNS domain is not configured.")
    return validate_domain(domains[0])


def public_domain(path: Path) -> str:
    value = read_key_value_file(path).get("PUBLIC_MEDIA_DOMAIN", "")
    if not value:
        raise PublicAccessError("Public media domain is not prepared.")
    return validate_domain(value)


def update_env_value(path: Path, key: str, value: str) -> bool:
    try:
        original = path.read_text(encoding="utf-8")
        metadata = path.stat()
    except OSError as error:
        raise PublicAccessError(f"Unable to read media environment: {error}") from error

    replacement = f"{key}={value}"
    found = False
    output: list[str] = []
    for line in original.splitlines():
        if line.startswith(f"{key}="):
            if found:
                raise PublicAccessError(f"Duplicate {key} setting.")
            output.append(replacement)
            found = True
        else:
            output.append(line)
    if not found:
        output.extend(["", replacement])

    rendered = "\n".join(output).rstrip("\n") + "\n"
    if rendered == original:
        return False

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
        if os.geteuid() == 0:
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def prepare_environment(stack_dir: Path, duckdns_config: Path) -> None:
    domain = duckdns_domain(duckdns_config)
    changed = update_env_value(stack_dir / ".env", "PUBLIC_MEDIA_DOMAIN", domain)
    print("PUBLIC MEDIA DOMAIN UPDATED" if changed else "PUBLIC MEDIA DOMAIN OK")


def media_urls(domain: str) -> tuple[str, str]:
    suffix = f"{domain}.duckdns.org"
    return f"https://jellyfin.{suffix}", f"https://seerr.{suffix}"


def docker_network_subnet(network: str) -> str:
    try:
        result = subprocess.run(
            [
                "docker",
                "network",
                "inspect",
                network,
                "--format",
                "{{json .IPAM.Config}}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise PublicAccessError("Unable to inspect the Docker media network.") from error

    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict):
            continue
        subnet = str(entry.get("Subnet", ""))
        if subnet and ":" not in subnet:
            return subnet
    raise PublicAccessError("Docker media network has no IPv4 subnet.")


def read_integration_keys(stack_dir: Path) -> tuple[str, str]:
    settings_path = stack_dir / "config/jellyseerr/settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublicAccessError("Unable to read Seerr integration settings.") from error
    seerr_key = str(settings.get("main", {}).get("apiKey", "")).strip()
    jellyfin_key = str(settings.get("jellyfin", {}).get("apiKey", "")).strip()
    if not seerr_key or not jellyfin_key:
        raise PublicAccessError("Seerr or Jellyfin integration key is unavailable.")
    return seerr_key, jellyfin_key


class JsonClient:
    def __init__(self, base_url: str, header: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.header = header
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        headers = {self.header: self.token}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            raise PublicAccessError(
                f"Service request {method} {path} failed with HTTP {error.code}."
            ) from error
        except (OSError, urllib.error.URLError) as error:
            raise PublicAccessError("Service configuration request failed.") from error
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise PublicAccessError(
                "Service configuration returned an invalid response."
            ) from error


def configure_jellyfin(
    client: JsonClient,
    proxy_subnet: str,
    apply: bool,
) -> bool:
    current = client.request("GET", "/System/Configuration/network")
    if not isinstance(current, dict):
        raise PublicAccessError("Jellyfin returned invalid network settings.")
    desired = dict(current)
    known = [str(item) for item in current.get("KnownProxies", [])]
    if proxy_subnet not in known:
        known.append(proxy_subnet)
    desired.update(
        {
            "KnownProxies": known,
            "EnableRemoteAccess": True,
            "EnableUPnP": False,
            "PublicHttpPort": 80,
            "PublicHttpsPort": 443,
        }
    )
    if desired == current:
        print("JELLYFIN PUBLIC NETWORK SETTINGS OK")
        return False
    if not apply:
        print("WOULD CONFIGURE JELLYFIN PUBLIC NETWORK SETTINGS")
        return True
    client.request("POST", "/System/Configuration/network", desired)
    print("CONFIGURED JELLYFIN PUBLIC NETWORK SETTINGS")
    return True


def configure_seerr(
    client: JsonClient,
    jellyfin_url: str,
    seerr_url: str,
    apply: bool,
) -> bool:
    changed = False
    network = client.request("GET", "/api/v1/settings/network")
    if not isinstance(network, dict):
        raise PublicAccessError("Seerr returned invalid network settings.")
    if network.get("trustProxy") is not True:
        changed = True
        if apply:
            client.request(
                "POST",
                "/api/v1/settings/network",
                {"trustProxy": True},
            )

    main = client.request("GET", "/api/v1/settings/main")
    if not isinstance(main, dict):
        raise PublicAccessError("Seerr returned invalid main settings.")
    if str(main.get("applicationUrl", "")).rstrip("/") != seerr_url:
        changed = True
        if apply:
            client.request(
                "POST",
                "/api/v1/settings/main",
                {"applicationUrl": seerr_url},
            )

    jellyfin = client.request("GET", "/api/v1/settings/jellyfin")
    if not isinstance(jellyfin, dict):
        raise PublicAccessError("Seerr returned invalid Jellyfin settings.")
    if str(jellyfin.get("externalHostname", "")).rstrip("/") != jellyfin_url:
        changed = True
        if apply:
            client.request(
                "POST",
                "/api/v1/settings/jellyfin",
                {"externalHostname": jellyfin_url},
            )

    if not changed:
        print("SEERR PUBLIC ACCESS SETTINGS OK")
    elif apply:
        print("CONFIGURED SEERR PUBLIC ACCESS SETTINGS")
    else:
        print("WOULD CONFIGURE SEERR PUBLIC ACCESS SETTINGS")
    return changed


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure public HTTPS proxy settings for Jellyfin and Seerr."
    )
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument(
        "--duckdns-config",
        type=Path,
        default=DEFAULT_DUCKDNS_CONFIG,
    )
    parser.add_argument("--docker-network", default="media-stack")
    parser.add_argument("--proxy-subnet")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    try:
        if args.prepare:
            prepare_environment(args.stack_dir, args.duckdns_config)
            return 0

        domain = public_domain(args.stack_dir / ".env")
        jellyfin_url, seerr_url = media_urls(domain)
        proxy_subnet = args.proxy_subnet or docker_network_subnet(
            args.docker_network
        )
        seerr_key, jellyfin_key = read_integration_keys(args.stack_dir)
        jellyfin_client = JsonClient(
            DEFAULT_JELLYFIN_URL,
            "X-Emby-Token",
            jellyfin_key,
        )
        seerr_client = JsonClient(DEFAULT_SEERR_URL, "X-Api-Key", seerr_key)

        configure_jellyfin(jellyfin_client, proxy_subnet, args.apply)
        configure_seerr(
            seerr_client,
            jellyfin_url,
            seerr_url,
            args.apply,
        )
        return 0
    except PublicAccessError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
