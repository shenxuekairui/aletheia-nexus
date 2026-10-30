"""New engine parameters cannot silently leak untranslated internal field names."""

import re

from aletheia_nexus.workbench.acquisition import get_acquisition_defaults
from aletheia_nexus.workbench.labels import PARAMETER_HELP, PARAMETER_LABELS
from aletheia_nexus.workbench.research import WorkbenchResearch
from aletheia_nexus.workbench.translation import DEFAULT_OPTIONS


def leaves(values, prefix=""):
    for key, value in values.items():
        full = f"{prefix}.{key}" if prefix else key
        yield key, full
        if isinstance(value, dict):
            yield from leaves(value, full)


def test_supported_parameter_names_and_explanations_are_chinese():
    for values in (
        get_acquisition_defaults(),
        WorkbenchResearch.parser_options(),
        DEFAULT_OPTIONS,
    ):
        for key, full in leaves(values):
            title = PARAMETER_LABELS.get(full, PARAMETER_LABELS.get(key, ""))
            assert re.search(r"[\u4e00-\u9fff]", title), full
            if key not in {"model", "browser", "currency"}:
                help_text = PARAMETER_HELP.get(full, PARAMETER_HELP.get(key, ""))
                assert re.search(r"[\u4e00-\u9fff]", help_text), full
