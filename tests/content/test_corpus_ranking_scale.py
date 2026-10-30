"""Ranking comparisons stay local to one source without losing context hits."""

from collections import Counter
from copy import deepcopy
from pathlib import Path

from aletheia_nexus.content import parse_document
from aletheia_nexus.content.corpus import Corpus, CorpusDocument, search_corpus
from aletheia_nexus.content.local import register_local_pdf


def test_context_ranking_never_compares_unrelated_parsed_sources(tmp_path):
    pdf = register_local_pdf(
        Path(__file__).resolve().parents[2]
        / "benchmarks/v07_fixtures/native_article.pdf",
        output_dir=tmp_path,
        title="Ranking fixture",
    )
    template = parse_document(pdf).document
    block, anchor = template["blocks"][0], template["anchors"][0]
    template["blocks"] = [
        {
            **block,
            "id": f"paragraph-{index}",
            "anchor_id": f"anchor-{index}",
            "kind": "paragraph",
            "content_region": "body",
            "order": index,
            "text": f"A source-linked reading in paragraph {index}.",
        }
        for index in range(4)
    ]
    template["anchors"] = [{**anchor, "id": f"anchor-{index}"} for index in range(4)]
    template["tables"], template["figures"], template["sections"] = [], [], []
    comparisons = Counter()

    class TrackedId(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            same = str.__eq__(self, other)
            if same is False:
                comparisons["different_sources"] += 1
            return same

    entries = []
    for number in range(80):
        document = deepcopy(template)
        document["artifact_id"] = TrackedId(f"parsed-ranking-fixture-{number:03}")
        document["source"] = {
            **document["source"],
            "title": f"Ranking fixture {number:03}",
            "pdf_sha256": f"{number:064x}",
        }
        entries.append(
            CorpusDocument(
                tmp_path / f"fixture-{number}.parsed.json", pdf, None, document
            )
        )
    corpus = Corpus(tmp_path, entries, [], [])
    report = search_corpus(corpus, "source-linked", limit=100000)
    assert report["coverage"]["searched_documents"] == 80
    assert report["total_hits"] > 80
    assert comparisons["different_sources"] == 0
    # Reusing block IDs in independent sources cannot suppress another paper.
    for entry in entries:
        hits = [
            h
            for h in report["hits"]
            if str(h["parsed_artifact_id"]) == str(entry.document["artifact_id"])
        ]
        direct = [h for h in hits if h["kind"] not in {"context", "figure"}]
        contexts = [h for h in hits if h["kind"] == "context"]
        assert direct and contexts
        assert hits.index(direct[0]) < hits.index(contexts[-1])
