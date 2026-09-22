"""
HTTP helpers. The pinned Starlette's FileResponse doesn't answer Range
requests, and browsers need them to seek inside a <video> -- without this,
scrubbing the source preview or a rendered clip just doesn't work.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import Response, StreamingResponse

CHUNK = 1024 * 512


def _content_disposition(filename: str, attachment: bool) -> str:
    kind = "attachment" if attachment else "inline"
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def ranged_file_response(
    request: Request,
    path: Path,
    media_type: str | None = None,
    download_name: str | None = None,
) -> Response:
    size = os.path.getsize(path)
    media_type = media_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
        "Last-Modified": str(int(os.path.getmtime(path))),
    }
    if download_name:
        headers["Content-Disposition"] = _content_disposition(download_name, True)

    range_header = request.headers.get("range")
    start, end = 0, size - 1
    status = 200
    if range_header and range_header.startswith("bytes="):
        try:
            spec = range_header.split("=", 1)[1].split(",")[0].strip()
            s, e = spec.split("-", 1)
            if s:
                start = int(s)
                end = int(e) if e else size - 1
            else:  # suffix range: last N bytes
                n = int(e)
                start, end = max(size - n, 0), size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
            status = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        except ValueError:
            start, end, status = 0, size - 1, 200

    length = end - start + 1
    headers["Content-Length"] = str(length)

    def iterfile():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                data = f.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    if request.method == "HEAD":
        return Response(status_code=status, headers=headers, media_type=media_type)
    return StreamingResponse(iterfile(), status_code=status, headers=headers, media_type=media_type)
