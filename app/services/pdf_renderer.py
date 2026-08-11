from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class PdfRenderError(RuntimeError):
    pass


def find_chromium_browser() -> Path | None:
    candidates = (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for executable in ("msedge", "chrome", "chromium"):
        resolved = shutil.which(executable)
        if resolved:
            return Path(resolved)
    return None


def render_html_to_pdf(
    html_path: str | Path,
    pdf_path: str | Path | None = None,
    *,
    browser_path: str | Path | None = None,
) -> Path:
    source = Path(html_path).resolve()
    destination = Path(pdf_path).resolve() if pdf_path else source.with_suffix(".pdf")
    browser = Path(browser_path).resolve() if browser_path else find_chromium_browser()
    if not source.is_file():
        raise FileNotFoundError(source)
    if not browser or not browser.is_file():
        raise PdfRenderError("Microsoft Edge, Chrome ou Chromium não encontrado")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="seven-pdf-") as profile:
        completed = subprocess.run(
            [
                str(browser),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--no-pdf-header-footer",
                "--run-all-compositor-stages-before-draw",
                f"--user-data-dir={profile}",
                f"--print-to-pdf={destination}",
                source.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    if completed.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        detail = (completed.stderr or completed.stdout or "falha desconhecida").strip()
        raise PdfRenderError(f"Não foi possível gerar o PDF: {detail[-500:]}")
    return destination
