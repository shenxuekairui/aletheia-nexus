"""Capture native Chromium downloads independently of publisher semantics."""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4


class LocalBrowserDownload:
    def __init__(self, path: Path, url: str) -> None:
        self._path = path
        self.url = url

    def path(self) -> str:
        return str(self._path)


class CdpDownloadCapture:
    """Route one native Chromium download into an AN-owned staging directory.

    Playwright download objects are not reliable for every browser attached over
    CDP. In particular, an attachment response can be saved by Edge while
    ``Download.save_as`` exposes an incomplete temporary file. Browser-domain
    events provide the completion boundary and the final on-disk path instead.
    """

    def __init__(self, context, output_dir: str | Path) -> None:
        self._session = None
        self._staging_dir: Path | None = None
        self._guid: str | None = None
        self._url: str | None = None
        self._file_path: Path | None = None
        self._completed = threading.Event()
        self._canceled = False

        browser = getattr(context, "browser", None)
        if browser is None or not hasattr(browser, "new_browser_cdp_session"):
            return

        staging_dir = Path(output_dir) / "_browser-downloads" / uuid4().hex
        session = browser.new_browser_cdp_session()
        try:
            staging_dir.mkdir(parents=True, exist_ok=False)
            session.on("Browser.downloadWillBegin", self._on_begin)
            session.on("Browser.downloadProgress", self._on_progress)
            session.send(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allowAndName",
                    "downloadPath": str(staging_dir.resolve()),
                    "eventsEnabled": True,
                },
            )
        except Exception:
            try:
                session.detach()
            except Exception:
                pass
            shutil.rmtree(staging_dir, ignore_errors=True)
            return

        self._session = session
        self._staging_dir = staging_dir

    @property
    def active(self) -> bool:
        return self._session is not None

    @property
    def session(self):
        return self._session

    @property
    def staging_dir(self) -> Path | None:
        return self._staging_dir

    @property
    def started(self) -> bool:
        return self._guid is not None

    def _on_begin(self, event) -> None:
        if self._guid is not None:
            return
        self._guid = str(event.get("guid") or "") or None
        self._url = str(event.get("url") or "") or None

    def _on_progress(self, event) -> None:
        guid = str(event.get("guid") or "")
        if self._guid is None or guid != self._guid:
            return
        state = event.get("state")
        if state == "completed":
            file_path = event.get("filePath")
            if file_path:
                self._file_path = Path(str(file_path))
            self._completed.set()
        elif state == "canceled":
            self._canceled = True
            self._completed.set()

    def wait(self, page, timeout: float) -> tuple[Path, str] | None:
        if not self.active or not self.started:
            return None
        deadline = time.monotonic() + max(0.0, timeout)
        while not self._completed.is_set() and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        if not self._completed.is_set() or self._canceled or self._staging_dir is None:
            return None

        path = self._file_path
        if path is None and self._guid is not None:
            path = self._staging_dir / self._guid
        if path is None or not path.is_file():
            files = [item for item in self._staging_dir.iterdir() if item.is_file()]
            if len(files) != 1:
                return None
            path = files[0]
        return path, self._url or str(getattr(page, "url", "") or "")

    def close(self, *, remove_files: bool = True) -> None:
        session = self._session
        self._session = None
        if session is not None:
            try:
                session.send("Browser.setDownloadBehavior", {"behavior": "default"})
            except Exception:
                pass
            try:
                session.detach()
            except Exception:
                pass
        if remove_files and self._staging_dir is not None:
            shutil.rmtree(self._staging_dir, ignore_errors=True)
