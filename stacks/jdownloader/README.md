# JDownloader 2

JDownloader runs as an independent Docker Compose stack on the UGREEN NAS. It
shares the repository and the family download storage with the media stack,
but it has its own lifecycle and configuration directory.

## NAS layout

```text
/volume1/docker/jdownloader/            Compose project and application state
/volume1/docker/jdownloader/config/     Persistent JDownloader configuration
/volume1/Family/Downloads/jdownloader/  Completed and in-progress downloads
```

Inside JDownloader, the download directory is `/output`. Create subfolders
under `/output` when different download types need to be separated.

## Deploy

The deployment reads the existing NAS connection and user/group settings from
`stacks/media/env/.env`, then installs this stack separately:

```bash
make deploy-jdownloader
```

After deployment, open:

```text
http://ugreen-nas:5800
```

The first startup may take a few minutes while JDownloader initializes and
updates itself. Configure MyJDownloader and any download-service accounts from
the JDownloader interface; never place those credentials in this repository.

## Security

Port `5800` provides an unencrypted web interface and is intended only for the
trusted home network. Do not expose it through router port forwarding. Remote
access should use the user's existing private-network access or
MyJDownloader. Raw VNC, the browser file manager, web audio, and the browser
terminal are disabled because they are not required.

## Operations

```bash
make status-jdownloader
make logs-jdownloader
make stop-jdownloader
```

The container image is pinned to a reviewed release. Change
`JDOWNLOADER_TAG` in the NAS-local `.env` only when intentionally testing a
newer upstream image.
