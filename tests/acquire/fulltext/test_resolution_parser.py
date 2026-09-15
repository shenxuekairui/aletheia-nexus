from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html


def test_parser_collects_scholarly_metadata_links_and_json_ld():
    html = """
    <html>
      <head>
        <title>Example Article</title>
        <base href="https://example.org/articles/123/">
        <meta name="citation_doi" content="10.1000/example">
        <meta name="citation_pdf_url" content="paper.pdf">
        <link rel="canonical" href="https://doi.org/10.1000/example">
        <script type="application/ld+json">
          {"encoding": {"contentUrl": "json-paper.pdf", "fileFormat": "application/pdf"}}
        </script>
      </head>
      <body>
        <a href="download/main.pdf"><span>Download</span> PDF</a>
        <embed src="viewer.pdf" type="application/pdf">
      </body>
    </html>
    """

    parsed = parse_html(html)

    assert parsed.title == "Example Article"
    assert parsed.base_href == "https://example.org/articles/123/"
    assert parsed.metadata_values("citation_doi") == ("10.1000/example",)
    assert parsed.metadata_values("citation_pdf_url") == ("paper.pdf",)
    assert len(parsed.json_ld) == 1
    assert any(link.text == "Download PDF" for link in parsed.links)
    assert any(link.tag == "embed" and link.type_attr == "application/pdf" for link in parsed.links)


def test_parser_tolerates_incomplete_html():
    parsed = parse_html(
        '<html><head><meta name="citation_title" content="Paper"><body>'
        '<a href="paper.pdf">PDF'
    )

    assert parsed.metadata_values("citation_title") == ("Paper",)
    assert any(link.url == "paper.pdf" for link in parsed.links)


def test_parser_rejects_non_string_input():
    try:
        parse_html(b"<html></html>")
    except TypeError as exc:
        assert "string" in str(exc)
    else:
        raise AssertionError("parse_html should reject non-string input")
