"""Serving selected files must not widen local filesystem authority."""

import pytest

from aletheia_nexus.workbench.ui_common import FileRegistry
from aletheia_nexus.workbench.ui_research import page_numbers


def test_capability_rejects_outside_private_and_changed_bytes(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    pdf = root / "paper.pdf"
    pdf.write_bytes(b"selected PDF bytes")
    registry = FileRegistry([root])
    url = registry.register(pdf)
    token = url.rsplit("/", 1)[-1]
    assert registry.resolve(token) == pdf
    with pytest.raises(KeyError):
        registry.resolve("invented-token")
    outside = tmp_path / "private.pdf"
    outside.write_bytes(b"private")
    with pytest.raises(ValueError):
        registry.register(outside)
    grants = root / ".authorizations"
    grants.mkdir()
    grant = grants / "secret.json"
    grant.write_bytes(b"grant")
    with pytest.raises(ValueError, match="Private"):
        registry.register(grant)
    pdf.write_bytes(b"replacement PDF bytes")
    with pytest.raises(ValueError, match="bytes changed"):
        registry.resolve(token)


def test_symlink_ancestor_does_not_gain_access(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "paper.pdf").write_bytes(b"outside")
    link = root / "linked"
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege is unavailable")
    registry = FileRegistry([tmp_path])
    with pytest.raises(ValueError, match="Symbolic"):
        registry.register(link / "paper.pdf")


def test_physical_pages_are_explicit_bounded_and_unique():
    assert page_numbers("1,3,5-7,3") == [1, 3, 5, 6, 7]
    assert page_numbers("") == []
    for invalid in ("0", "-1", "7-3", "1-100000", "abc", "1-2-3"):
        with pytest.raises((ValueError, TypeError)):
            page_numbers(invalid)
