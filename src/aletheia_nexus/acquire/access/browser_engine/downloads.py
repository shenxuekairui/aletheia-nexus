"""Capture native Chromium downloads independently of publisher semantics."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class EmptyBrowserDownload(ValueError):
    """The transport exposed an empty placeholder, not a downloaded document."""


def save_browser_download(download, destination: Path) -> None:
    """Copy a completed transfer; never send a zero-byte placeholder to identity QA."""
    save_as = getattr(download, "save_as", None)
    if callable(save_as):
        save_as(str(destination))
    else:
        shutil.copyfile(Path(download.path()), destination)
    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise EmptyBrowserDownload("Browser download contained zero bytes")


@dataclass
class _NativeTransfer:
    url: str
    state: str = "inProgress"
    path: Path | None = None
    frame_id: str | None = None


class LocalBrowserDownload:
    def __init__(self, path: Path, url: str, suggested_filename: str = "") -> None:
        self._path = path
        self.url = url
        self.suggested_filename = suggested_filename

    def path(self) -> str:
        return str(self._path)

    def save_as(self, path: str | Path) -> None:
        shutil.copyfile(self._path, path)


class CdpDownloadCapture:
    """Route native Chromium downloads into a context-scoped AN staging directory.

    Playwright download objects are not reliable for every browser attached over
    CDP. In particular, an attachment response can be saved by Edge while
    ``Download.save_as`` exposes an incomplete temporary file. Browser-domain
    events provide the completion boundary and the final on-disk path instead.
    """

    def __init__(self, context, output_dir: str | Path) -> None:
        self._session = None
        self._staging_dir: Path | None = None
        self._transfers: dict[str, _NativeTransfer] = {}
        self._context_params: dict[str, str] = {}

        browser = getattr(context, "browser", None)
        if browser is None or not hasattr(browser, "new_browser_cdp_session"):
            return

        staging_dir = Path(output_dir) / "_browser-downloads" / uuid4().hex
        session = None
        try:
            session = browser.new_browser_cdp_session()
            pages = list(getattr(context, "pages", ()))
            if pages and hasattr(context, "new_cdp_session"):
                contexts = session.send("Target.getBrowserContexts")
                # Omitted browserContextId means the *default* context, not
                # whichever incognito context owns this page. Otherwise the
                # completed file can remain in Playwright's separate directory.
                if contexts.get("browserContextIds"):
                    target_session = context.new_cdp_session(pages[0])
                    try:
                        target = target_session.send("Target.getTargetInfo")
                    finally:
                        target_session.detach()
                    context_id = target.get("targetInfo", {}).get("browserContextId")
                    if context_id in contexts["browserContextIds"]:
                        self._context_params["browserContextId"] = context_id
            staging_dir.mkdir(parents=True, exist_ok=False)
            session.on("Browser.downloadWillBegin", self._on_begin)
            session.on("Browser.downloadProgress", self._on_progress)
            session.send(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allowAndName",
                    "downloadPath": str(staging_dir.resolve()),
                    "eventsEnabled": True,
                    **self._context_params,
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
        return bool(self._transfers)

    @property
    def cancelled_url(self) -> str | None:
        """Return only an unambiguous URL whose observed transfers all failed."""
        if not self._transfers or any(
            transfer.state != "canceled" for transfer in self._transfers.values()
        ):
            return None
        urls = {transfer.url for transfer in self._transfers.values() if transfer.url}
        return next(iter(urls)) if len(urls) == 1 else None

    def pending_for(self, url: str) -> bool:
        transfers = [t for t in self._transfers.values() if t.url == url]
        # No correlated native event yet is uncertain, not evidence of failure.
        return not transfers or any(t.state == "inProgress" for t in transfers)

    def has_unclaimed_downloads(self, frame_ids: set[str]) -> bool:
        """A page-scoped caller must preserve files belonging to other tabs."""
        return any(t.frame_id not in frame_ids for t in self._transfers.values())

    def _on_begin(self, event) -> None:
        guid = str(event.get("guid") or "")
        if guid and guid not in self._transfers:
            self._transfers[guid] = _NativeTransfer(
                str(event.get("url") or ""),
                frame_id=str(event["frameId"]) if event.get("frameId") else None,
            )

    def _on_progress(self, event) -> None:
        guid = str(event.get("guid") or "")
        transfer = self._transfers.get(guid)
        if transfer is None:
            return
        state = event.get("state")
        if state == "completed":
            file_path = event.get("filePath")
            if file_path:
                transfer.path = Path(str(file_path))
            transfer.state = "completed"
        elif state == "canceled":
            transfer.state = "canceled"

    def wait(
        self,
        page,
        timeout: float,
        *,
        expected_url: str | None = None,
        expected_guid: str | None = None,
        expected_frame_ids: set[str] | None = None,
        wait_for_start: bool = False,
    ) -> tuple[Path, str] | None:
        # A viewer click can acknowledge before downloadWillBegin is delivered.
        # Only an explicit save action opts into waiting for that first event;
        # passive delivery checks must still return immediately when idle.
        if not self.active or (not self.started and not wait_for_start):
            return None
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            selected = [
                (guid, transfer)
                for guid, transfer in self._transfers.items()
                if (expected_url is None or transfer.url == expected_url)
                and (expected_guid is None or guid == expected_guid)
                and (
                    expected_frame_ids is None
                    or transfer.frame_id in expected_frame_ids
                )
            ]
            for guid, transfer in selected:
                if transfer.state != "completed" or self._staging_dir is None:
                    continue
                path = transfer.path or self._staging_dir / guid
                # A completed event is necessary but not sufficient. Do not
                # guess from an unrelated file or accept partial/outside paths.
                try:
                    if (
                        not path.resolve().is_relative_to(self._staging_dir.resolve())
                        or path.suffix.casefold() in {".crdownload", ".part", ".tmp"}
                        or not path.is_file()
                        or path.stat().st_size == 0
                    ):
                        continue
                except OSError:
                    continue
                return path, transfer.url or str(getattr(page, "url", "") or "")
            if (
                time.monotonic() >= deadline
                or selected
                and all(t.state != "inProgress" for _, t in selected)
            ):
                return None
            page.wait_for_timeout(100)

    def close(self, *, remove_files: bool = True) -> None:
        session = self._session
        self._session = None
        if session is not None:
            try:
                session.send(
                    "Browser.setDownloadBehavior",
                    {"behavior": "default", **self._context_params},
                )
            except Exception:
                pass
            try:
                session.detach()
            except Exception:
                pass
        if remove_files and self._staging_dir is not None:
            shutil.rmtree(self._staging_dir, ignore_errors=True)
