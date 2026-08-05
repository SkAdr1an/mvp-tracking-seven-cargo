"""Capture sanitized visual validations for the latest Edge public-trip URL."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def main(history_copy: str, output_directory: str) -> None:
    connection = sqlite3.connect(f"file:{history_copy}?mode=ro", uri=True)
    row = connection.execute(
        "SELECT url FROM urls WHERE url LIKE '%/viagem/%' ORDER BY last_visit_time DESC LIMIT 1"
    ).fetchone()
    if not row or len(urlparse(str(row[0])).path.rstrip("/").rsplit("/", 1)[-1]) < 43:
        raise SystemExit("No recent public-trip URL found")
    url = str(row[0])
    output = Path(output_directory).resolve()
    for width, height in ((390, 844), (1440, 1000)):
        target = output / f"public-trip-{width}.png"
        subprocess.run(
            [
                str(EDGE), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                f"--window-size={width},{height}", "--virtual-time-budget=10000",
                f"--screenshot={target}", url,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    print("Captured public-trip-390.png and public-trip-1440.png")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
