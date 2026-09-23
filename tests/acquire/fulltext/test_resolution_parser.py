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
    assert any(
        link.tag == "embed" and link.type_attr == "application/pdf"
        for link in parsed.links
    )


def test_parser_excludes_script_style_and_template_text_from_visible_text():
    parsed = parse_html(
        "<html><body>Actual article content"
        "<script>const warning = 'cloudflare captcha access denied';</script>"
        "<style>.notice::before { content: 'forbidden'; }</style>"
        "<template>verify you are human</template>"
        "</body></html>"
    )

    assert parsed.visible_text == "Actual article content"


def test_parser_keeps_json_ld_while_excluding_it_from_visible_text():
    parsed = parse_html(
        '<script type="application/ld+json">'
        '{"contentUrl":"paper.pdf","fileFormat":"application/pdf"}'
        "</script>"
        "<body>Article text</body>"
    )

    assert len(parsed.json_ld) == 1
    assert "paper.pdf" in parsed.json_ld[0]
    assert parsed.visible_text == "Article text"


def test_parser_extracts_explicit_pdf_path_from_inline_script_state():
    parsed = parse_html(
        '<script>window.state={"pdfPath":"\\/iel7\\/123\\/456\\/05366888.pdf"};</script>'
        "<body>Article text</body>"
    )

    assert any(
        link.tag == "script" and link.url == "/iel7/123/456/05366888.pdf"
        for link in parsed.links
    )
    assert parsed.visible_text == "Article text"


def test_parser_extracts_unicode_escaped_pdf_url_from_inline_script_state():
    parsed = parse_html(
        '<script>window.state={"pdfUrl":"https\\u003A\\u002F\\u002Ffiles.example.org\\u002Fpaper.pdf?download=1\\u0026x=2"};</script>'
    )

    assert any(
        link.tag == "script"
        and link.url == "https://files.example.org/paper.pdf?download=1&x=2"
        for link in parsed.links
    )


def test_parser_does_not_promote_non_pdf_inline_script_values():
    parsed = parse_html(
        '<script>window.state={"article":"/document/5366888/","format":"application/pdf"};</script>'
    )

    assert not any(link.tag == "script" for link in parsed.links)


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
