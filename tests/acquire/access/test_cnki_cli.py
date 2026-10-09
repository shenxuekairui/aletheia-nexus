"""CNKI CLI session ownership without launching or authenticating a browser."""

import importlib.util
import sys
from pathlib import Path

import pytest

from aletheia_nexus.acquire.access.cnki_provider import _source_candidate
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAttemptStatus,
)


def test_batch_cli_accepts_mixed_bibliographic_inputs_and_serializes_report(tmp_path):
    import json
    from types import SimpleNamespace

    from aletheia_nexus.acquire.access import (
        BatchAcquisitionItem,
        BatchItemStatus,
        PaperRequest,
    )

    script = Path(__file__).parents[3] / "scripts/batch_v06_download.py"
    spec = importlib.util.spec_from_file_location("batch_cli_bibliographic", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    path = tmp_path / "inputs.json"
    path.write_text(
        json.dumps(
            [
                "10.1000/old",
                {"doi": "10.1000/title", "title": "Old DOI title"},
                {
                    "title": "无 DOI 的研究论文",
                    "authors": ["张三"],
                    "journal": "测试学报",
                    "year": 2024,
                },
            ]
        ),
        encoding="utf-8",
    )
    values, titles = cli._load_inputs(path)
    assert values[:2] == ["10.1000/old", "10.1000/title"]
    assert titles == {"10.1000/title": "Old DOI title"}
    assert isinstance(values[2], PaperRequest) and values[2].doi is None
    item = BatchAcquisitionItem(
        input_value=values[2],
        doi=None,
        status=BatchItemStatus.AMBIGUOUS,
        request_key=values[2].key,
    )
    output = tmp_path / "report.json"
    cli._write_report(
        output,
        SimpleNamespace(
            elapsed_seconds=0,
            halted_for_interaction=False,
            status_counts={"AMBIGUOUS": 1},
            items=(item,),
        ),
    )
    saved = json.loads(output.read_text(encoding="utf-8"))["items"][0]
    assert saved["input"]["authors"] == ["张三"] and saved["doi"] is None
    assert saved["status"] == "AMBIGUOUS"


@pytest.mark.parametrize(
    "options,keeps_open",
    [
        ([], True),
        (["--no-keep-browser-open"], False),
        (["--non-interactive"], False),
        (["--cdp-endpoint", "http://127.0.0.1:9222"], False),
    ],
)
def test_cli_owns_session_and_preserves_interactive_window(
    monkeypatch, tmp_path, capsys, options, keeps_open
):
    script = Path(__file__).parents[3] / "scripts/download_cnki.py"
    spec = importlib.util.spec_from_file_location("cnki_cli_fixture", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    events = []

    class Session:
        def __init__(self, config):
            self.config = config
            events.append("created")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("closed")

        def wait_until_closed(self):
            events.append("kept open")

    def acquire(**kwargs):
        assert "config" not in kwargs
        config = kwargs["browser_session"].config
        assert config.cnki_context_request and not config.direct_connection
        events.append("acquired")
        return BrowserAccessAttempt(
            source_candidate=_source_candidate("10.1000/target"),
            final_url="https://login.cnki.net/login/",
            status=BrowserAttemptStatus.INTERACTION_REQUIRED,
        )

    monkeypatch.setattr(cli, "BrowserSession", Session)
    monkeypatch.setattr(cli, "acquire_cnki_pdf", acquire)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--doi",
            "10.1000/target",
            "--output-dir",
            str(tmp_path),
            *options,
        ],
    )
    assert cli.main() == 2
    assert events == [
        "created",
        "acquired",
        *(["kept open"] if keeps_open else []),
        "closed",
    ]
    assert '"status": "INTERACTION_REQUIRED"' in capsys.readouterr().out


@pytest.mark.parametrize(
    "statuses,closed_index,expected_count,expected_code",
    [
        ([BrowserAttemptStatus.VERIFIED] * 3, None, 3, 0),
        (
            [
                BrowserAttemptStatus.NO_FILE_CANDIDATES,
                BrowserAttemptStatus.VERIFIED,
                BrowserAttemptStatus.VERIFIED,
            ],
            None,
            3,
            1,
        ),
        (
            [
                BrowserAttemptStatus.VERIFIED,
                BrowserAttemptStatus.INTERACTION_REQUIRED,
                BrowserAttemptStatus.VERIFIED,
            ],
            None,
            2,
            2,
        ),
        (
            [
                BrowserAttemptStatus.VERIFIED,
                BrowserAttemptStatus.RETRIEVAL_FAILED,
                BrowserAttemptStatus.VERIFIED,
            ],
            1,
            2,
            1,
        ),
    ],
)
def test_cli_multiple_dois_share_one_session_and_stop_only_on_handoff_or_closure(
    monkeypatch, tmp_path, statuses, closed_index, expected_count, expected_code
):
    script = Path(__file__).parents[3] / "scripts/download_cnki.py"
    spec = importlib.util.spec_from_file_location("cnki_batch_cli_fixture", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    sessions, calls = [], []

    class Session:
        def __init__(self, config):
            sessions.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def acquire(**kwargs):
        index = len(calls)
        calls.append(kwargs)
        return BrowserAccessAttempt(
            source_candidate=_source_candidate(kwargs["doi"]),
            final_url=None,
            status=statuses[index],
            download_started=index == closed_index,
            evidence=("CNKI browser target closed",) if index == closed_index else (),
        )

    monkeypatch.setattr(cli, "BrowserSession", Session)
    monkeypatch.setattr(cli, "acquire_cnki_pdf", acquire)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--doi",
            "10.1000/first",
            "--doi",
            "10.1000/second",
            "--doi",
            "10.1000/third",
            "--no-keep-browser-open",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert cli.main() == expected_code
    assert len(sessions) == 1 and len(calls) == expected_count
    assert all(call["browser_session"] is sessions[0] for call in calls)


@pytest.mark.parametrize("direct", [False, True])
def test_batch_cdp_launcher_only_forces_direct_network_when_requested(
    monkeypatch, tmp_path, direct
):
    script = Path(__file__).parents[3] / "scripts/batch_v06_download.py"
    spec = importlib.util.spec_from_file_location("batch_network_fixture", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    commands = []
    monkeypatch.setattr(cli, "_find_browser", lambda: Path("C:/fixture/msedge.exe"))
    monkeypatch.setattr(cli, "_cdp_ready", lambda endpoint: True)
    monkeypatch.setattr(
        cli.subprocess, "Popen", lambda args, **kwargs: commands.append(args)
    )
    cli._start_cdp_browser(
        "http://127.0.0.1:9222", tmp_path / "profile", direct_connection=direct
    )
    assert ("--no-proxy-server" in commands[0]) == direct
