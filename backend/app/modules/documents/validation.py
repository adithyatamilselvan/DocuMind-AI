import re
import unicodedata
import zipfile
from dataclasses import dataclass

from app.core.errors import AppError

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT = "text/plain"

EXT_TO_MIME = {"pdf": PDF, "docx": DOCX, "txt": TXT}

MAX_ZIP_ENTRIES = 5000
MAX_ZIP_UNCOMPRESSED = 500 * 1024 * 1024
MAX_ZIP_RATIO = 200


@dataclass(frozen=True)
class DetectedType:
    ext: str
    mime: str


def rejected(code: str, message: str, status: int = 415) -> AppError:
    return AppError(status, code, message)


def sanitize_filename(name: str | None) -> str:
    """Display-only filename: no path components, control characters or odd whitespace.
    The stored object key never contains it."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if not name:
        return "document"
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 195 - len(ext)] + dot + ext) if dot else name[:200]
    return name


def _is_pdf(path: str) -> bool:
    with open(path, "rb") as f:
        return b"%PDF-" in f.read(1024)


def _is_docx(path: str) -> bool:
    if not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise rejected("zip_too_many_entries", "Document archive has too many parts")
            total = sum(i.file_size for i in infos)
            compressed = max(1, sum(i.compress_size for i in infos))
            if total > MAX_ZIP_UNCOMPRESSED or total / compressed > MAX_ZIP_RATIO:
                raise rejected("zip_bomb", "Document expands to an unsafe size")
            names = {i.filename for i in infos}
            return "[Content_Types].xml" in names and "word/document.xml" in names
    except zipfile.BadZipFile:
        return False


def _is_text(path: str) -> bool:
    with open(path, "rb") as f:
        head = f.read(65536)
    if head.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")):
        return True
    if b"\x00" in head:
        return False
    if not head:
        return True
    ctrl = sum(1 for b in head if b < 9 or (13 < b < 32))
    return ctrl / len(head) < 0.02


def detect_type(path: str, filename: str) -> DetectedType:
    """Decide the type from file CONTENT and require it to match the extension.
    Client-declared MIME types are never trusted."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in EXT_TO_MIME:
        raise rejected("unsupported_type", "Only PDF, DOCX and TXT files are supported")
    checks = {"pdf": _is_pdf, "docx": _is_docx, "txt": _is_text}
    if not checks[ext](path):
        raise rejected(
            "content_mismatch", f"The file content does not look like a valid .{ext} file"
        )
    return DetectedType(ext=ext, mime=EXT_TO_MIME[ext])
