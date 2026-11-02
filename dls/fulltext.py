"""On-demand OA PDF reading. Fallible operations return (value, reason)."""
from __future__ import annotations

import io
import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import requests

from .models import Paper

MAX_PDF_BYTES = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT = 30


def _check_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid PDF URL: HTTP(S) without credentials required")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("PDF URL targets a local/private network")


def download_pdf(paper: Paper) -> tuple[bytes | None, str | None]:
    """Stream at most 20 MiB, checking each redirect; never raise on failure."""
    if not paper.open_access_pdf:
        return None, "no open_access_pdf URL"
    started = time.monotonic()
    try:
        url = paper.open_access_pdf
        with requests.Session() as session:
            session.trust_env = False
            for _ in range(6):
                if time.monotonic() - started > DOWNLOAD_TIMEOUT:
                    return None, "PDF download timeout"
                _check_url(url)
                with session.get(url, stream=True, allow_redirects=False,
                                 timeout=(5, DOWNLOAD_TIMEOUT),
                                 headers={"User-Agent": "DLS/0.1 (OA research PDF reader)"}) as response:
                    if response.is_redirect:
                        location = response.headers.get("Location")
                        if not location:
                            return None, "PDF redirect missing Location"
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    if mime not in {"", "application/pdf", "application/octet-stream", "binary/octet-stream"}:
                        return None, f"not a PDF content type: {mime}"
                    if int(response.headers.get("Content-Length", "0")) > MAX_PDF_BYTES:
                        return None, "PDF exceeds 20MB limit"
                    chunks, size = [], 0
                    for chunk in response.iter_content(64 * 1024):
                        if time.monotonic() - started > DOWNLOAD_TIMEOUT:
                            return None, "PDF download timeout"
                        size += len(chunk)
                        if size > MAX_PDF_BYTES:
                            return None, "PDF exceeds 20MB limit"
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if not data.lstrip().startswith(b"%PDF-"):
                        return None, "invalid PDF signature"
                    return data, None
            return None, "too many PDF redirects"
    except Exception as exc:
        return None, f"PDF download failed: {type(exc).__name__}: {exc}"


def extract_text(pdf_bytes: bytes) -> tuple[str | None, str | None]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "pypdf not installed"
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if not text:
            return None, "PDF contains no extractable text (needs_ocr)"
        return text, None
    except Exception as exc:
        return None, f"PDF extraction failed: {type(exc).__name__}: {exc}"


_HEADINGS = {
    "abstract": "abstract", "introduction": "introduction", "background": "background",
    "methods": "methods", "method": "methods", "methodology": "methods",
    "materials and methods": "methods", "experimental methods": "methods",
    "results": "results", "results and discussion": "results",
    "discussion": "discussion", "conclusion": "conclusion", "conclusions": "conclusion",
    "references": "references", "bibliography": "references", "related work": "related work",
}
_HEADING = re.compile(r"^\s*(?:#{1,6}\s*)?(?:(?:\d+(?:\.\d+)*\.?|[IVX]+)[.)]?\s+)?("
                      + "|".join(sorted(_HEADINGS, key=len, reverse=True))
                      + r")\s*[:.]?\s*$", re.I)


def extract_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = "_full"
    for line in text.splitlines(keepends=True):
        match = _HEADING.match(line)
        if match:
            current = _HEADINGS[match[1].lower()]
            sections.setdefault(current, "")
        else:
            sections[current] = sections.get(current, "") + line
    if not any(k != "_full" for k in sections):
        return {"_full": text}
    return {k: v.strip() for k, v in sections.items() if v.strip()}
