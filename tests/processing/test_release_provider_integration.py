"""Merged UI operations and scientific phases retain their own wire prompts."""

import json

import httpx
import pytest

from aletheia_nexus.processing.contracts import PROMPT, PROMPT_VERSION, TEXT, obj
from aletheia_nexus.processing.provider import CallBudget, DeepSeekProvider
from aletheia_nexus.processing.source_first import (
    ASSEMBLY_PROMPT,
    INVENTORY_PHASE,
    INVENTORY_PROMPT,
    SOURCE_FIRST_VERSION,
    assembly_request,
)


@pytest.mark.parametrize("custom", [False, True])
@pytest.mark.parametrize("phase", ["inventory", "assembly", "direct"])
def test_scientific_phases_and_custom_operations_keep_matching_prompt_history(
    monkeypatch, custom, phase
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-release-key")
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"value":"ok"}'}],
                    }
                ],
            },
        )

    provider = DeepSeekProvider(
        {"name": "synthetic-model", "min_interval_seconds": 0, "max_retries": 0},
        enabled=True,
        transport=httpx.MockTransport(handler),
        **(
            {"instructions": "Translate only titles.", "prompt_version": "title-test/1"}
            if custom
            else {}
        ),
    )
    request = {"phase": "document_extraction"}
    if phase == "inventory":
        request = {"phase": INVENTORY_PHASE}
    elif phase == "assembly":
        request = assembly_request(request, {"items": []})
    budget = CallBudget(1)
    assert provider.generate(request, obj({"value": TEXT}), [], budget, 100) == {
        "value": "ok"
    }
    expected_prompt, expected_version = {
        "inventory": (INVENTORY_PROMPT, SOURCE_FIRST_VERSION + ":inventory"),
        "assembly": (ASSEMBLY_PROMPT, SOURCE_FIRST_VERSION + ":assembly"),
        "direct": (PROMPT, PROMPT_VERSION),
    }[phase]
    if custom:
        expected_prompt, expected_version = "Translate only titles.", "title-test/1"
    assert payloads[0]["instructions"].startswith(expected_prompt)
    assert budget.calls[0]["prompt_version"] == expected_version
