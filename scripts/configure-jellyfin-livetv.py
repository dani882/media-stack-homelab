#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


DEFAULT_CONFIG = Path(
    "/volume1/docker/media-stack/config/jellyfin/config/config/livetv.xml"
)
DEFAULT_CONTAINER = "jellyfin"
DEFAULT_BASE_URL = "http://127.0.0.1:8899"
DEFAULT_SEERR_SETTINGS = Path(
    "/volume1/docker/media-stack/config/jellyseerr/settings.json"
)
DEFAULT_M3U_URL = "http://dispatcharr:9191/output/m3u"
DEFAULT_EPG_URL = "http://dispatcharr:9191/output/epg"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
XSD = "http://www.w3.org/2001/XMLSchema"
ET.register_namespace("xsi", XSI)


class JellyfinLiveTvError(RuntimeError):
    pass


def read_jellyfin_api_key(path: Path) -> str:
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise JellyfinLiveTvError(
            f"Unable to read Jellyfin integration credentials: {error}"
        ) from error

    api_key = str(settings.get("jellyfin", {}).get("apiKey", "")).strip()
    if not api_key:
        raise JellyfinLiveTvError(
            "Seerr does not contain a Jellyfin integration API key"
        )
    return api_key


def jellyfin_request(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
) -> object | None:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"X-Emby-Token": api_key},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    except (OSError, urllib.error.URLError) as error:
        raise JellyfinLiveTvError(
            f"Jellyfin API request failed: {error}"
        ) from error
    return json.loads(body) if body else None


def wait_until_jellyfin_ready(
    base_url: str,
    attempts: int = 30,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(
                f"{base_url.rstrip('/')}/health",
                timeout=5,
            ) as response:
                if response.getcode() == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        if attempt < attempts:
            time.sleep(2)
    raise JellyfinLiveTvError("Jellyfin did not become healthy in time")


def refresh_guide(
    base_url: str,
    api_key: str,
    timeout: int = 300,
) -> None:
    tasks = jellyfin_request(base_url, api_key, "GET", "/ScheduledTasks")
    if not isinstance(tasks, list):
        raise JellyfinLiveTvError("Jellyfin returned an invalid task list")

    task = next(
        (item for item in tasks if item.get("Key") == "RefreshGuide"),
        None,
    )
    if task is None or not task.get("Id"):
        raise JellyfinLiveTvError("Jellyfin Refresh Guide task was not found")

    task_id = str(task["Id"])
    if task.get("State") != "Running":
        jellyfin_request(
            base_url,
            api_key,
            "POST",
            f"/ScheduledTasks/Running/{task_id}",
        )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(2)
        tasks = jellyfin_request(base_url, api_key, "GET", "/ScheduledTasks")
        if not isinstance(tasks, list):
            continue
        current = next(
            (item for item in tasks if str(item.get("Id")) == task_id),
            None,
        )
        if current is not None and current.get("State") != "Running":
            print("JELLYFIN GUIDE REFRESHED")
            return
    raise JellyfinLiveTvError("Jellyfin Refresh Guide task timed out")


def text_child(parent: ET.Element, name: str, value: str) -> ET.Element:
    child = parent.find(name)
    if child is None:
        child = ET.SubElement(parent, name)
    child.text = value
    return child


def find_managed_entry(
    parent: ET.Element,
    element_name: str,
    type_name: str,
    location_name: str,
) -> ET.Element | None:
    for entry in parent.findall(element_name):
        entry_type = (entry.findtext("Type") or "").lower()
        location = entry.findtext(location_name) or ""
        if entry_type == type_name and "dispatcharr:9191/output/" in location:
            return entry
    return None


def update_tree(
    root: ET.Element,
    m3u_url: str = DEFAULT_M3U_URL,
    epg_url: str = DEFAULT_EPG_URL,
) -> None:
    tuner_hosts = root.find("TunerHosts")
    if tuner_hosts is None:
        tuner_hosts = ET.SubElement(root, "TunerHosts")

    tuner = find_managed_entry(
        tuner_hosts, "TunerHostInfo", "m3u", "Url"
    )
    if tuner is None:
        tuner = ET.SubElement(tuner_hosts, "TunerHostInfo")
        text_child(tuner, "Id", uuid.uuid5(uuid.NAMESPACE_URL, m3u_url).hex)

    tuner_values = {
        "Url": m3u_url,
        "Type": "m3u",
        "ImportFavoritesOnly": "false",
        "AllowHWTranscoding": "false",
        "AllowFmp4TranscodingContainer": "false",
        "AllowStreamSharing": "true",
        "FallbackMaxStreamingBitrate": "30000000",
        "EnableStreamLooping": "false",
        "TunerCount": "0",
        "IgnoreDts": "true",
    }
    for name, value in tuner_values.items():
        text_child(tuner, name, value)

    providers = root.find("ListingProviders")
    if providers is None:
        providers = ET.SubElement(root, "ListingProviders")

    provider = find_managed_entry(
        providers, "ListingsProviderInfo", "xmltv", "Path"
    )
    if provider is None:
        provider = ET.SubElement(providers, "ListingsProviderInfo")
        text_child(provider, "Id", uuid.uuid5(uuid.NAMESPACE_URL, epg_url).hex)

    text_child(provider, "Type", "xmltv")
    text_child(provider, "Path", epg_url)
    enabled_tuners = provider.find("EnabledTuners")
    if enabled_tuners is None:
        ET.SubElement(provider, "EnabledTuners")
    text_child(provider, "EnableAllTuners", "true")

    categories = {
        "NewsCategories": ["news", "journalism", "documentary", "current affairs"],
        "SportsCategories": ["sports", "basketball", "baseball", "football"],
        "KidsCategories": ["kids", "family", "children", "childrens", "disney"],
        "MovieCategories": ["movie"],
    }
    for section_name, values in categories.items():
        section = provider.find(section_name)
        if section is None:
            section = ET.SubElement(provider, section_name)
        section.clear()
        for value in values:
            text_child(section, "string", value)

    if provider.find("ChannelMappings") is None:
        ET.SubElement(provider, "ChannelMappings")


def new_tree() -> ET.ElementTree:
    root = ET.Element(
        "LiveTvOptions",
        {
            "xmlns:xsd": XSD,
        },
    )
    guide_days = ET.SubElement(root, "GuideDays")
    guide_days.set(f"{{{XSI}}}nil", "true")
    text_child(root, "EnableRecordingSubfolders", "false")
    text_child(root, "EnableOriginalAudioWithEncodedRecordings", "false")
    ET.SubElement(root, "TunerHosts")
    ET.SubElement(root, "ListingProviders")
    text_child(root, "PrePaddingSeconds", "0")
    text_child(root, "PostPaddingSeconds", "0")
    ET.SubElement(root, "MediaLocationsCreated")
    text_child(root, "RecordingPostProcessorArguments", '"{path}"')
    text_child(root, "SaveRecordingNFO", "true")
    text_child(root, "SaveRecordingImages", "true")
    return ET.ElementTree(root)


def load_tree(path: Path) -> ET.ElementTree:
    if path.exists():
        return ET.parse(path)
    return new_tree()


def tree_bytes(tree: ET.ElementTree) -> bytes:
    return ET.tostring(tree.getroot(), encoding="utf-8")


def element_signature(element: ET.Element) -> tuple:
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        (element.text or "").strip(),
        tuple(element_signature(child) for child in element),
    )


def configuration_changed(
    path: Path,
    m3u_url: str,
    epg_url: str,
) -> bool:
    tree = load_tree(path)
    before = element_signature(tree.getroot())
    update_tree(tree.getroot(), m3u_url, epg_url)
    return before != element_signature(tree.getroot())


def write_configuration(path: Path, m3u_url: str, epg_url: str) -> None:
    tree = load_tree(path)
    update_tree(tree.getroot(), m3u_url, epg_url)
    ET.indent(tree, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)

    original_mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix="livetv.",
        suffix=".xml",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
        tree.write(temporary, encoding="utf-8", xml_declaration=True)

    temporary_path.chmod(original_mode)
    os.replace(temporary_path, path)


def container_running(container: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def configure(
    path: Path,
    container: str,
    m3u_url: str,
    epg_url: str,
    dry_run: bool,
) -> bool:
    if not configuration_changed(path, m3u_url, epg_url):
        print("JELLYFIN LIVE TV OK")
        return False

    if dry_run:
        print("WOULD CONFIGURE JELLYFIN LIVE TV")
        return True

    was_running = container_running(container)
    try:
        if was_running:
            subprocess.run(["docker", "stop", container], check=True)
        write_configuration(path, m3u_url, epg_url)
    except (OSError, ET.ParseError, subprocess.CalledProcessError) as error:
        raise JellyfinLiveTvError(str(error)) from error
    finally:
        if was_running:
            subprocess.run(["docker", "start", container], check=True)

    print("CONFIGURED JELLYFIN LIVE TV")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure Jellyfin Live TV for Dispatcharr."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--seerr-settings",
        type=Path,
        default=DEFAULT_SEERR_SETTINGS,
    )
    parser.add_argument("--m3u-url", default=DEFAULT_M3U_URL)
    parser.add_argument("--epg-url", default=DEFAULT_EPG_URL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-guide-refresh", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        configure(
            args.config,
            args.container,
            args.m3u_url,
            args.epg_url,
            args.dry_run,
        )
        if args.dry_run:
            if not args.skip_guide_refresh:
                print("WOULD REFRESH JELLYFIN GUIDE")
        elif not args.skip_guide_refresh:
            wait_until_jellyfin_ready(args.base_url)
            refresh_guide(
                args.base_url,
                read_jellyfin_api_key(args.seerr_settings),
            )
    except JellyfinLiveTvError as error:
        print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
