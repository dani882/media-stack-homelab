FROM python:3.13-alpine

RUN apk add --no-cache ca-certificates ffmpeg

COPY dominican-iptv.py /app/dominican-iptv.py
COPY dominican-iptv-sources.json /app/sources.json

ENTRYPOINT ["python", "/app/dominican-iptv.py"]
