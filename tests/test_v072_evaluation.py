import importlib.util
from pathlib import Path

import pytest

script = Path(__file__).resolve().parents[1] / "scripts" / "verify_v072_t0.py"
spec = importlib.util.spec_from_file_location("verify_v072_t0", script)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


@pytest.mark.parametrize(
    "text,value,present",
    [
        ("188.4", 88.4, False),
        ("-1.4", 1.4, False),
        ("1.4e-3", 1.4, False),
        ("1.4e-3", 0.0014, True),
        ("80.90%", 80.9, True),
        ("80–85%", 85, True),
        ("− 1.4 V", -1.4, True),
    ],
)
def test_numeric_presence_is_signed_numeric_equality(text, value, present):
    assert evaluation.numeric_presence(text, value) is present
