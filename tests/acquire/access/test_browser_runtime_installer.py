import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from aletheia_nexus.acquire.access.browser_engine import installer


@pytest.mark.parametrize(
    "url",
    [
        "http://storage.googleapis.com/chrome-for-testing-public/155/win64/chrome-win64.zip",
        "https://evil.example/chrome-for-testing-public/155/win64/chrome-win64.zip",
        "https://storage.googleapis.com/other/155/win64/chrome-win64.zip",
        "https://storage.googleapis.com/chrome-for-testing-public/155/win64/chrome-win64.zip?secret=x",
    ],
)
def test_installer_rejects_unexpected_download_origins(url):
    with pytest.raises(ValueError, match="Unexpected"):
        installer._trusted_archive_url(url)


class _Response(BytesIO):
    def __init__(self, body, url):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url


@pytest.mark.skipif(installer.os.name != "nt", reason="Windows runtime provisioning")
@pytest.mark.parametrize("unsafe", [False, True])
def test_installer_provisions_only_new_private_runtime(monkeypatch, tmp_path, unsafe):
    url = "https://storage.googleapis.com/chrome-for-testing-public/155.0.1.2/win64/chrome-win64.zip"
    manifest = json.dumps(
        {
            "channels": {
                "Stable": {
                    "version": "155.0.1.2",
                    "downloads": {"chrome": [{"platform": "win64", "url": url}]},
                }
            }
        }
    ).encode()
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "../escape.exe" if unsafe else "chrome-win64/chrome.exe", b"fixture binary"
        )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        installer,
        "urlopen",
        lambda address, **kw: _Response(
            manifest if address == installer._MANIFEST else buffer.getvalue(), address
        ),
    )
    monkeypatch.setattr(installer, "windows_browser_major", lambda path: 155)
    root = tmp_path / ".aletheia-nexus/browser-runtimes"
    if unsafe:
        with pytest.raises(ValueError, match="unsafe path"):
            installer.main()
        assert not (root / "chrome-155.0.1.2").exists()
        assert not (root / "escape.exe").exists()
    else:
        assert installer.main() == 0
        binary = root / "chrome-155.0.1.2/chrome-win64/chrome.exe"
        assert binary.read_bytes() == b"fixture binary"
        assert installer.main() == 0  # Existing runtime is not replaced.
        assert binary.read_bytes() == b"fixture binary"
    assert not list(root.glob("an-runtime-*"))
