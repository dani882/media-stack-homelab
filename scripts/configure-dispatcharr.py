#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "http://127.0.0.1:9191"
DEFAULT_CONTAINER = "dispatcharr"
DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_PLAYLIST_URL = "http://dominican-iptv:8080/playlist.m3u"
DEFAULT_ACCOUNT_NAME = "Republica Dominicana (combinada)"
DEFAULT_EPG_NAME = "Republica Dominicana (EPGShare01)"
DEFAULT_EPG_URL = "https://epgshare01.online/epgshare01/epg_ripper_DO1.xml.gz"
DEFAULT_CATALOG = Path("/volume1/docker/media-stack/dominican-iptv-sources.json")
DEFAULT_USERNAME = "admin"


class DispatcharrError(RuntimeError):
    pass


def generate_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits + "-_@#%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def read_or_create_credentials(
    secret_file: Path,
    username: str,
    public_url: str,
) -> tuple[str, str]:
    if secret_file.exists():
        values: dict[str, str] = {}
        for line in secret_file.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip()

        password = values.get("password", "")
        stored_username = values.get("username", username)
        if password:
            return stored_username, password

    secret_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    password = generate_password()
    secret_file.write_text(
        f"username={username}\npassword={password}\nurl={public_url}\n",
        encoding="utf-8",
    )
    secret_file.chmod(0o600)
    return username, password


def wait_until_ready(base_url: str, attempts: int = 60) -> None:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(base_url, timeout=5) as response:
                if response.getcode() == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass

        if attempt < attempts:
            time.sleep(2)

    raise DispatcharrError(f"Dispatcharr is not ready at {base_url}")


def run_manage_code(
    container: str,
    code: str,
    environment: dict[str, str] | None = None,
    timeout: int = 300,
) -> str:
    command = ["docker", "exec"]
    for key, value in (environment or {}).items():
        command.extend(["--env", f"{key}={value}"])
    command.extend(
        [container, "python", "manage.py", "shell", "-c", code]
    )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        stderr = getattr(error, "stderr", "") or ""
        raise DispatcharrError(
            "Dispatcharr configuration command failed.\n" + stderr.strip()
        ) from error

    return result.stdout.strip()


def ensure_admin(container: str, username: str, password: str) -> None:
    code = """
import os
from django.contrib.auth import get_user_model
from django.core.management import call_command

username = os.environ['DISPATCHARR_ADMIN_USERNAME']
password = os.environ['DJANGO_SUPERUSER_PASSWORD']
User = get_user_model()

if User.objects.filter(username=username).exists():
    print('DISPATCHARR ADMIN OK')
else:
    call_command(
        'createsuperuser',
        username=username,
        email=f'{username}@localhost',
        interactive=False,
    )
    print('DISPATCHARR ADMIN CREATED')
"""
    output = run_manage_code(
        container,
        code,
        {
            "DISPATCHARR_ADMIN_USERNAME": username,
            "DJANGO_SUPERUSER_PASSWORD": password,
        },
    )
    print(output)


def configure_playlist(
    container: str,
    account_name: str,
    playlist_url: str,
    epg_name: str = DEFAULT_EPG_NAME,
    epg_url: str = DEFAULT_EPG_URL,
    epg_aliases: dict[str, list[str]] | None = None,
) -> None:
    code = """
import hashlib
import json
import os
import re
import unicodedata
import urllib.request
from apps.channels.models import (
    Channel, ChannelGroupM3UAccount, ChannelProfile,
    ChannelProfileMembership, ChannelStream, Stream,
)
from apps.epg.models import EPGData, EPGSource
from apps.epg.tasks import refresh_epg_data
from apps.m3u.models import M3UAccount
from apps.m3u.signals import refresh_account_on_save
from apps.m3u.tasks import refresh_m3u_groups, refresh_single_m3u_account
from core.models import StreamProfile, UserAgent
from django.db.models.signals import post_save

name = os.environ['DISPATCHARR_ACCOUNT_NAME']
url = os.environ['DISPATCHARR_PLAYLIST_URL']
epg_name = os.environ['DISPATCHARR_EPG_NAME']
epg_url = os.environ['DISPATCHARR_EPG_URL']
epg_aliases = json.loads(os.environ.get('DISPATCHARR_EPG_ALIASES', '{}'))
legacy_name = 'Republica Dominicana (IPTV-org)'
preferences = {
    'enable_vod': False,
    'auto_enable_new_groups_live': True,
    'auto_enable_new_groups_vod': False,
    'auto_enable_new_groups_series': False,
}

# The deploy performs the first discovery synchronously. Avoid racing the
# normal post-save Celery discovery that is useful for UI-created accounts.
post_save.disconnect(refresh_account_on_save, sender=M3UAccount)
try:
    account = M3UAccount.objects.filter(name=name).first()
    if account is None:
        account = M3UAccount.objects.filter(name=legacy_name).first()
    if account is None:
        account = M3UAccount(name=name)
    account.name = name
    account.server_url = url
    account.account_type = M3UAccount.Types.STADNARD
    account.max_streams = 0
    account.is_active = True
    account.refresh_interval = 24
    account.stale_stream_days = 7
    account.custom_properties = preferences
    account.save()
finally:
    post_save.connect(refresh_account_on_save, sender=M3UAccount)

discovery = refresh_m3u_groups(account.id, full_refresh=False)
if not discovery or discovery[1] is None:
    raise RuntimeError('Unable to discover groups from the Dominican playlist')

group_settings = {
    'channel_numbering_mode': 'fixed',
    'channel_sort_order': 'name',
    'channel_sort_reverse': False,
}
relations = ChannelGroupM3UAccount.objects.filter(m3u_account=account)
for relation in relations:
    relation.enabled = True
    relation.auto_channel_sync = True
    relation.auto_sync_channel_start = 1
    relation.custom_properties = group_settings
    relation.save(update_fields=[
        'enabled',
        'auto_channel_sync',
        'auto_sync_channel_start',
        'custom_properties',
    ])

refresh_single_m3u_account(account.id)
account.refresh_from_db()
stream_count = Stream.objects.filter(m3u_account=account).count()
channel_count = Channel.objects.filter(auto_created_by=account).count()

if account.status != M3UAccount.Status.SUCCESS:
    raise RuntimeError(
        f'Dispatcharr refresh did not finish successfully: '
        f'{account.status}: {account.last_message}'
    )
if stream_count == 0 or channel_count == 0:
    raise RuntimeError('Dispatcharr created no streams or channels')


def normalized(value):
    value = re.sub(r'\\s*\\(\\d{3,4}[pi]\\)', '', value, flags=re.I)
    value = re.sub(r'\\s*\\[[^]]+\\]', '', value)
    value = unicodedata.normalize('NFKD', value)
    value = ''.join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r'[^a-z0-9]+', ' ', value.casefold())
    return ' '.join(value.split())


def health_key(stream_url):
    match = re.search(r'/iptvcat/([a-f0-9]{32})\\.m3u8', stream_url)
    if match:
        return f'iptvcat:{match.group(1)}'
    digest = hashlib.sha256(stream_url.encode()).hexdigest()[:24]
    return f'url:{digest}'


try:
    with urllib.request.urlopen(
        'http://dominican-iptv:8080/status.json', timeout=10
    ) as response:
        health = json.load(response)
except Exception:
    health = {}

default_agent = UserAgent.objects.first()
compat, _ = StreamProfile.objects.get_or_create(
    name='IPTV - Compatibilidad AAC',
    defaults={
        'command': 'ffmpeg',
        'parameters': (
            '-user_agent {userAgent} -i {streamUrl} '
            '-map 0:v:0? -map 0:a:0? -c:v copy '
            '-c:a aac -b:a 128k -ac 2 -f mpegts pipe:1'
        ),
        'locked': False,
        'is_active': True,
        'user_agent': default_agent,
    },
)

streams = list(
    Stream.objects.filter(m3u_account=account)
    .select_related('channel_group', 'stream_profile')
)
by_name = {}
for stream in streams:
    by_name.setdefault(normalized(stream.name), []).append(stream)

status_rank = {
    'stable': 0, 'silent': 1, 'intermittent': 2,
    'testing': 3, 'geo-blocked': 4, 'dead': 5,
}
source_rank = {'official': 0, 'iptv-org': 1, 'iptvcat': 2}
canonical_channels = []
channel_status = {}
fallback_count = 0

for key, candidates in by_name.items():
    def candidate_rank(stream):
        record = health.get(health_key(stream.url), {})
        status = record.get('status', 'testing')
        source = (stream.custom_properties or {}).get('x-source', '')
        if not source:
            source = 'iptvcat' if '/iptvcat/' in stream.url else 'iptv-org'
        return (status_rank.get(status, 3), source_rank.get(source, 3), stream.id)

    candidates.sort(key=candidate_rank)
    linked = list(
        Channel.objects.filter(
            auto_created_by=account,
            channelstream__stream__in=candidates,
        ).distinct().order_by('channel_number', 'id')
    )
    if not linked:
        continue
    primary = candidates[0]
    canonical = linked[0]
    record = health.get(health_key(primary.url), {})
    status = record.get('status', 'testing')
    canonical.name = primary.name
    canonical.tvg_id = primary.tvg_id or canonical.tvg_id
    canonical.channel_group = primary.channel_group
    canonical.hidden_from_output = False
    canonical.save(update_fields=[
        'name', 'tvg_id', 'channel_group', 'hidden_from_output', 'updated_at'
    ])
    for order, stream in enumerate(candidates):
        ChannelStream.objects.update_or_create(
            channel=canonical, stream=stream, defaults={'order': order}
        )
        stream_record = health.get(health_key(stream.url), {})
        audio_codec = stream_record.get('audio_codec')
        needs_audio_compat = stream_record.get('ok') and audio_codec not in {
            None, 'aac', 'mp2', 'mp3'
        }
        desired_profile = compat if needs_audio_compat else None
        if stream.stream_profile_id != (
            desired_profile.id if desired_profile else None
        ):
            stream.stream_profile = desired_profile
            stream.save(update_fields=['stream_profile'])
    fallback_count += max(0, len(candidates) - 1)
    for duplicate in linked[1:]:
        if not duplicate.hidden_from_output:
            duplicate.hidden_from_output = True
            duplicate.save(update_fields=['hidden_from_output', 'updated_at'])
    canonical_channels.append(canonical)
    statuses = [
        health.get(health_key(stream.url), {}).get('status', 'testing')
        for stream in candidates
    ]
    channel_status[canonical.id] = min(statuses, key=lambda item: status_rank.get(item, 3))

number_starts = {
    'stable': 1, 'silent': 501, 'intermittent': 501,
    'testing': 501, 'dead': 501, 'geo-blocked': 901,
}
next_numbers = {1: 1, 501: 501, 901: 901}
for channel in sorted(canonical_channels, key=lambda item: normalized(item.name)):
    status = channel_status[channel.id]
    start = number_starts.get(status, 501)
    channel.channel_number = float(next_numbers[start])
    next_numbers[start] += 1
    channel.save(update_fields=['channel_number', 'updated_at'])

stable_profile, _ = ChannelProfile.objects.get_or_create(name='Dominicana - Estables')
all_profile, _ = ChannelProfile.objects.get_or_create(name='Dominicana - Todos')
for channel in canonical_channels:
    ChannelProfileMembership.objects.update_or_create(
        channel_profile=all_profile, channel=channel, defaults={'enabled': True}
    )
    ChannelProfileMembership.objects.update_or_create(
        channel_profile=stable_profile,
        channel=channel,
        defaults={'enabled': channel_status[channel.id] == 'stable'},
    )

source, created = EPGSource.objects.get_or_create(
    name=epg_name,
    defaults={
        'source_type': 'xmltv', 'url': epg_url, 'is_active': True,
        'refresh_interval': 24, 'priority': 100,
    },
)
EPGSource.objects.filter(id=source.id).update(
    source_type='xmltv', url=epg_url, is_active=True,
    refresh_interval=24, priority=100,
)
refresh_epg_data(source.id, force=True)
source.refresh_from_db()

epg_by_name = {}
for entry in EPGData.objects.filter(epg_source=source):
    epg_by_name.setdefault(normalized(entry.name), entry)
mapped_epg = 0
for channel in canonical_channels:
    keys = [normalized(channel.name)]
    keys.extend(normalized(alias) for alias in epg_aliases.get(keys[0], []))
    match = next((epg_by_name.get(key) for key in keys if epg_by_name.get(key)), None)
    if match and channel.epg_data_id != match.id:
        channel.epg_data = match
        channel.save(update_fields=['epg_data', 'updated_at'])
        mapped_epg += 1

print(
    f'DISPATCHARR IPTV OK: account={account.id} groups={relations.count()} '
    f'streams={stream_count} channels={len(canonical_channels)} '
    f'fallbacks={fallback_count} epg={source.status} mapped={mapped_epg}'
)
"""
    output = run_manage_code(
        container,
        code,
        {
            "DISPATCHARR_ACCOUNT_NAME": account_name,
            "DISPATCHARR_PLAYLIST_URL": playlist_url,
            "DISPATCHARR_EPG_NAME": epg_name,
            "DISPATCHARR_EPG_URL": epg_url,
            "DISPATCHARR_EPG_ALIASES": json.dumps(epg_aliases or {}),
        },
        timeout=600,
    )
    print(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure Dispatcharr for Dominican Republic IPTV."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--playlist-url", default=DEFAULT_PLAYLIST_URL)
    parser.add_argument("--account-name", default=DEFAULT_ACCOUNT_NAME)
    parser.add_argument("--epg-name", default=DEFAULT_EPG_NAME)
    parser.add_argument("--epg-url", default=DEFAULT_EPG_URL)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    secret_file = args.stack_dir / "secrets" / "dispatcharr-admin.txt"
    public_url = args.base_url.replace("127.0.0.1", "localhost")

    try:
        wait_until_ready(args.base_url)
        username, password = read_or_create_credentials(
            secret_file,
            args.username,
            public_url,
        )
        ensure_admin(args.container, username, password)
        catalog = {}
        if args.catalog.exists():
            catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        aliases = dict(catalog.get("epg_aliases", {}))
        for channel in catalog.get("channels", []):
            key = channel.get("name", "").casefold()
            if key and channel.get("epg_aliases"):
                aliases.setdefault(key, []).extend(channel["epg_aliases"])
        configure_playlist(
            args.container,
            args.account_name,
            args.playlist_url,
            args.epg_name,
            args.epg_url,
            aliases,
        )
    except DispatcharrError as error:
        print(f"ERROR: {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
