"""Synthetic public metadata + existing synthetic acquisition; actual SDK stdio."""

import runpy
import sys
from pathlib import Path

from aletheia_nexus.acquire.metadata import crossref

fixture, metadata_marker, download_marker = sys.argv[1:4]


def metadata(url, **kwargs):
    assert url == crossref.CROSSREF_API + "/works"
    assert set(kwargs["params"]) == {"query.bibliographic", "rows"}
    with Path(metadata_marker).open("a", encoding="utf-8") as stream:
        stream.write(kwargs["params"]["query.bibliographic"] + "\n")
    return {
        "message": {
            "items": [
                {"DOI": "10.5555/unselected", "title": ["Other candidate"]},
                {
                    "DOI": "10.5555/title-sdk",
                    "title": ["Self-authored discovery fixture"],
                },
            ]
        }
    }


crossref.get_json = metadata
helper = Path(__file__).with_name("mcp_public_acquisition_server.py")
sys.argv = [str(helper), fixture, download_marker, *sys.argv[4:]]
runpy.run_path(str(helper), run_name="__main__")
