"""Resolve extensionless downloads from a bounded file, never trust HTML as SI."""

from email.message import Message
from pathlib import Path
from zipfile import BadZipFile, ZipFile

MIME_SUFFIXES = {
    "application/pdf": ".pdf",
    "text/csv": ".csv",
    "text/tab-separated-values": ".tsv",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "image/tiff": ".tiff",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "text/plain": ".txt",
    "text/rtf": ".rtf",
    "application/rtf": ".rtf",
    "application/json": ".json",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "image/gif": ".gif",
    "application/gzip": ".gz",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
}


def response_filename_suffix(value):
    """Keep only a type hint, never a remote path or token-bearing filename."""
    if not value or len(value) > 2048:
        return ""
    message = Message()
    message["content-disposition"] = value
    try:
        filename = message.get_filename()
    except (LookupError, ValueError, TypeError):
        return ""
    return Path(filename).suffix.lower() if isinstance(filename, str) else ""


def resolve_extension(path, declared, content_type=None):
    if declared:
        return declared
    path = Path(path)
    with path.open("rb") as handle:
        prefix = handle.read(1024)
    if b"%PDF-" in prefix:
        return ".pdf"
    if prefix.startswith(b"PK\x03\x04"):
        try:
            with ZipFile(path) as archive:
                names = set(archive.namelist())
                for member, suffix in (
                    ("xl/workbook.xml", ".xlsx"),
                    ("word/document.xml", ".docx"),
                    ("ppt/presentation.xml", ".pptx"),
                ):
                    if member in names and "[Content_Types].xml" in names:
                        return suffix
                if {"mimetype", "content.xml"} <= names:
                    member = archive.getinfo("mimetype")
                    if member.file_size <= 256:
                        mime = (
                            archive.read(member)
                            .decode("ascii", errors="replace")
                            .strip()
                        )
                        if mime in MIME_SUFFIXES:
                            return MIME_SUFFIXES[mime]
        except BadZipFile:
            pass
        return ".zip"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if prefix.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    if prefix.startswith(b"{\\rtf"):
        return ".rtf"
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if prefix.startswith(b"\x1f\x8b"):
        return ".gz"
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in MIME_SUFFIXES:
        return MIME_SUFFIXES[mime]
    raise ValueError("attachment_type_not_confirmed")
