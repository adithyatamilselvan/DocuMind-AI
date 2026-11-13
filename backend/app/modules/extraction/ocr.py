import asyncio
import shutil
import subprocess  # noqa: S404
from typing import Protocol


class OCRUnavailableError(Exception):
    """The OCR engine is not installed/configured."""


class OCREngine(Protocol):
    def available(self) -> bool: ...

    def recognize(self, png_bytes: bytes) -> str:
        """Return the text found in a rendered page image."""
        ...


class TesseractOCR:
    """Calls the `tesseract` CLI (installed in the Docker image; see docs/setup-windows.md)."""

    def __init__(self, cmd: str = "tesseract", langs: str = "eng", timeout_s: int = 120) -> None:
        self.cmd = shutil.which(cmd) or cmd
        self.langs = langs
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return shutil.which(self.cmd) is not None or shutil.which("tesseract") is not None

    def recognize(self, png_bytes: bytes) -> str:
        if not self.available():
            raise OCRUnavailableError("Tesseract is not installed")
        try:
            proc = subprocess.run(  # noqa: S603
                [self.cmd, "stdin", "stdout", "-l", self.langs, "--psm", "3"],
                input=png_bytes, capture_output=True, timeout=self.timeout_s, check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired as e:
            raise TimeoutError("OCR timed out") from e
        if proc.returncode != 0:
            raise RuntimeError(f"tesseract failed: {proc.stderr.decode(errors='replace')[:200]}")
        return proc.stdout.decode("utf-8", errors="replace")


async def recognize_async(engine: OCREngine, png_bytes: bytes) -> str:
    return await asyncio.to_thread(engine.recognize, png_bytes)
