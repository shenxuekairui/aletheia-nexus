"""Optional SI save scope cannot select or collect another tab's PDF webview."""

import json
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access.browser_engine import viewer

EXTENSION = "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html"


def target(identity, parent, *, kind="iframe", url=EXTENSION):
    return {
        "targetId": identity,
        "type": kind,
        "parentId": parent,
        "url": url,
        "title": "same.pdf",
    }


def test_owned_selection_follows_exact_parent_target_not_matching_title_or_url():
    targets = [
        target("user-viewer", "user-page"),
        target("owned-viewer", "owned-page"),
        target("owned-pdf-child", "owned-viewer", url="https://pubs.acs.org/same.pdf"),
    ]
    assert viewer._owned_pdf_viewer_targets(
        targets, owner_target_id="owned-page", owner_frame_ids={"owned-frame"}
    ) == [targets[1]]


def test_owned_selection_refuses_unrelated_opener_or_extension_name_in_web_url():
    wrong = target("unrelated", "user-page")
    wrong["openerId"] = "owned-page"
    evil = target(
        "owned-remote",
        "owned-page",
        url="https://example.org/mhjfbmdgcfjbbpaeojofohoefgiehjai",
    )
    assert not viewer._owned_pdf_viewer_targets(
        [wrong, evil], owner_target_id="owned-page", owner_frame_ids={"owned-frame"}
    )


def test_legacy_webview_needs_explicit_owner_frame_when_parent_target_is_absent():
    owned = {
        "targetId": "legacy",
        "type": "webview",
        "parentFrameId": "owned-frame",
        "url": EXTENSION,
    }
    assert viewer._owned_pdf_viewer_targets(
        [owned], owner_target_id="owned-page", owner_frame_ids={"owned-frame"}
    ) == [owned]
    assert not viewer._owned_pdf_viewer_targets(
        [owned], owner_target_id="owned-page", owner_frame_ids={"other-frame"}
    )


def fixture(tmp_path, targets):
    commands = []

    class Session:
        callback = None

        def on(self, _event, callback):
            self.callback = callback

        def remove_listener(self, _event, callback):
            assert self.callback == callback
            self.callback = None

        def send(self, method, params=None):
            commands.append((method, params))
            if method == "Target.getTargets":
                return {"targetInfos": targets}
            if method == "Target.attachToTarget":
                return {"sessionId": params["targetId"]}
            if method == "Target.sendMessageToTarget":
                command = json.loads(params["message"])
                result = (
                    {
                        "frameTree": {
                            "frame": {"id": "owned-viewer-frame"},
                            "childFrames": [{"frame": {"id": "owned-pdf-frame"}}],
                        }
                    }
                    if command["method"] == "Page.getFrameTree"
                    else {"result": {"value": {"clicked": True, "ready": True}}}
                )
                self.callback(
                    {
                        "sessionId": params["sessionId"],
                        "message": json.dumps({"id": command["id"], "result": result}),
                    }
                )
            return {}

    class Capture:
        session = Session()
        staging_dir = tmp_path

        def close(self, **kwargs):
            pytest.fail("Injected native capture belongs to the SI caller")

    class Owner:
        def send(self, method):
            return (
                {"targetInfo": {"targetId": "owned-page"}}
                if method == "Target.getTargetInfo"
                else {"frameTree": {"frame": {"id": "owned-frame"}}}
            )

        def detach(self):
            pass

    page = SimpleNamespace(
        url="https://pubs.acs.org/same.pdf", wait_for_timeout=lambda *_: None
    )
    context = SimpleNamespace(new_cdp_session=lambda p: Owner())
    return context, page, Capture(), commands


def test_owned_save_reuses_capture_and_passes_only_its_frame_scope_to_waiter(tmp_path):
    targets = [target("user-viewer", "user-page"), target("owned-viewer", "owned-page")]
    context, page, capture, commands = fixture(tmp_path, targets)
    frames = set()
    saved = tmp_path / "owned.pdf"
    saved.write_bytes(b"%PDF-owned-file")
    waits = []

    def wait(owner, seconds):
        assert (
            owner is page
            and {"owned-frame", "owned-viewer-frame", "owned-pdf-frame"} <= frames
        )
        waits.append(seconds)
        return saved, page.url

    result = viewer.trigger_pdf_viewer_save(
        context,
        page,
        doi="10.1000/same",
        output_dir=tmp_path,
        expected_title=None,
        timeout=1,
        max_bytes=100,
        owned_page_only=True,
        native_capture=capture,
        owned_frame_ids=frames,
        download_wait=wait,
    )
    assert result == (saved, tmp_path) and waits
    attached = [
        params["targetId"]
        for method, params in commands
        if method == "Target.attachToTarget"
    ]
    assert attached == ["owned-viewer"]
    assert not any(method == "Browser.setDownloadBehavior" for method, _ in commands)


def test_two_owned_viewers_are_ambiguous_and_no_save_control_is_clicked(tmp_path):
    context, page, capture, commands = fixture(
        tmp_path, [target("one", "owned-page"), target("two", "owned-page")]
    )
    assert (
        viewer.trigger_pdf_viewer_save(
            context,
            page,
            doi="10.1000/same",
            output_dir=tmp_path,
            expected_title=None,
            timeout=0,
            max_bytes=100,
            owned_page_only=True,
            native_capture=capture,
            owned_frame_ids=set(),
            download_wait=lambda *a: pytest.fail("Ambiguous owner must not download"),
        )
        is None
    )
    assert not any(method == "Target.attachToTarget" for method, _ in commands)


@pytest.mark.parametrize("kind", ["budget", "cancel"])
def test_owned_wait_errors_and_control_signal_are_not_swallowed(tmp_path, kind):
    context, page, capture, _ = fixture(
        tmp_path, [target("owned-viewer", "owned-page")]
    )

    class Cancel(BaseException):
        pass

    error = ValueError("local byte budget exhausted") if kind == "budget" else Cancel()

    def wait(*_):
        raise error

    with pytest.raises(type(error)):
        viewer.trigger_pdf_viewer_save(
            context,
            page,
            doi="10.1000/same",
            output_dir=tmp_path,
            expected_title=None,
            timeout=1,
            max_bytes=100,
            owned_page_only=True,
            native_capture=capture,
            owned_frame_ids=set(),
            download_wait=wait,
        )
