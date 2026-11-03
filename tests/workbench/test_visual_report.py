import tempfile
import unittest
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path

from aletheia_nexus.workbench.visual_report import write_visual_report


class TextReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


class VisualReportTests(unittest.TestCase):
    def result(self):
        return {
            "artifact_id": "result-identity",
            "package": {
                "documents": [
                    {
                        "id": "paper",
                        "source": {"title": "论文甲"},
                        "pages_requested": [1, 2],
                    }
                ]
            },
            "provider": {"model": "test-model"},
            "task": {
                "objective": "总结",
                "fields": [{"id": "finding", "label": "研究结果"}],
                "budget": {"max_input_characters": 200000, "max_cost": 2},
                "model": {"currency": "CNY"},
            },
            "response": {
                "records": [
                    {
                        "subject": "对象",
                        "fields": {
                            "finding": {
                                "value": "第一句。第二句。",
                                "context": "限于仿真",
                                "citations": [
                                    {
                                        "source_id": "paper",
                                        "page": 2,
                                        "quote": "原文证据",
                                    }
                                ],
                            }
                        },
                    }
                ],
                "claims": [{"text": "主张仍需核对", "citations": []}],
                "issues": [{"detail": "图表未解读"}],
                "requests": [
                    {"source_id": "paper", "pages": [2], "reason": "需看原图"}
                ],
            },
        }

    def render(self, result):
        with tempfile.TemporaryDirectory() as directory:
            output = write_visual_report([result], Path(directory) / "report.html")
            return output.read_text(encoding="utf-8")

    def test_all_native_content_and_review_state_remain_visible(self):
        content = self.render(self.result())
        reader = TextReader()
        reader.feed(content)
        text = "".join(reader.parts)
        for value in [
            "第一句。第二句。",
            "限于仿真",
            "原文证据",
            "主张仍需核对",
            "图表未解读",
            "需看原图",
            "待核对",
        ]:
            self.assertIn(value, text)
        self.assertIn('href="#ref-1"', content)
        self.assertIn('id="ref-1"', content)

    def test_model_text_is_escaped_instead_of_executed(self):
        result = self.result()
        result["response"]["records"][0]["fields"]["finding"]["value"] = (
            "<script>alert(1)</script><img src=x onerror=alert(1)>"
        )
        result["package"]["documents"][0]["source"]["title"] = "<unsafe-title>"
        content = self.render(result)
        self.assertNotIn("<script>", content)
        self.assertNotIn("<img src=x", content)
        self.assertIn("&lt;script&gt;", content)
        self.assertIn("&lt;unsafe-title&gt;", content)

    def test_same_document_ids_in_different_results_do_not_merge_sources(self):
        first = self.result()
        second = deepcopy(first)
        second["artifact_id"] = "other-result"
        second["package"]["documents"][0]["source"]["title"] = "论文乙"
        with tempfile.TemporaryDirectory() as directory:
            output = write_visual_report(
                [first, second], Path(directory) / "report.html"
            )
            content = output.read_text(encoding="utf-8")
        self.assertIn('id="ref-1"', content)
        self.assertIn('id="ref-2"', content)
        self.assertIn("[1] 论文甲", content)
        self.assertIn("[2] 论文乙", content)


if __name__ == "__main__":
    unittest.main()
