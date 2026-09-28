from scripts import evaluate_v07_parser as evaluator


def _report(*, deletions=0, insertions=0, substitutions=0):
    return {
        "metrics": {
            "doi_hash_gate": {"correct": 1, "total": 1},
            "anchored_block_coverage": {"correct": 1, "total": 1},
            "character_accuracy": {
                "expected_characters": 10,
                "actual_characters": 10,
                "deletions": deletions,
                "insertions": insertions,
                "substitutions": substitutions,
                "information_loss_rate": 0.0,
                "character_error_rate": 0.0,
            },
            "duplicate_text_rate": {
                "duplicate_characters": 1,
                "parsed_characters": 100,
                "ratio": 0.01,
            },
            "table_figure_link_omissions": 0,
            "table_figure_false_associations": 0,
        },
        "records": [{"status_correct": True, "warnings_correct": True}],
    }


def test_evaluator_accepts_non_count_diagnostic_metrics(monkeypatch, capsys):
    monkeypatch.setattr(evaluator, "evaluate_manifest", lambda path: _report())

    assert evaluator.main([]) == 0
    assert '"character_accuracy"' in capsys.readouterr().out


def test_evaluator_rejects_character_errors_when_gold_text_exists(monkeypatch, capsys):
    monkeypatch.setattr(
        evaluator,
        "evaluate_manifest",
        lambda path: _report(deletions=1),
    )

    assert evaluator.main([]) == 1
    capsys.readouterr()
