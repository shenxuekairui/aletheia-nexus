"""Conservative CNKI routing, independent of retrieval and browser lifetime."""

import re
from urllib.parse import urlsplit


def cnki_route_reason(
    *, doi, metadata, expected_title, config, source_urls=(), request=None
):
    """Return a routing reason, or None. Ordinary route failure is not evidence."""
    if not config.cnki_enabled:
        return None
    for url in source_urls:
        try:
            host = (urlsplit(url).hostname or "").lower()
        except ValueError:
            continue
        if host == "cnki.net" or host.endswith(".cnki.net"):
            return "observed_cnki_source"
    if request and request.cnki_id:
        return "explicit_cnki_record"
    normalized = doi.casefold()
    if ".cnki." in normalized or normalized.startswith("10.7503/cjcu"):
        return "cnki_doi_family"
    if config.cnki_search_all_titles:
        return "explicit_all_titles_opt_in"

    def chinese(text):
        return bool(text and re.search(r"[\u3400-\u9fff]", text))

    journal = (metadata.journal if metadata else None) or (
        request.journal if request else None
    )
    if chinese(journal):
        return "chinese_journal"
    metadata_title = metadata.title if metadata else None
    if chinese(metadata_title):
        return "chinese_metadata_title"
    # A translated user title must not redirect a known English-language paper.
    if metadata_title and not chinese(metadata_title):
        return None
    publisher = (metadata.publisher or "").casefold() if metadata else ""
    if normalized.startswith(
        (
            "10.1016/",
            "10.1021/",
            "10.1038/",
            "10.1002/",
            "10.1007/",
            "10.1109/",
            "10.1126/",
        )
    ) or any(
        name in publisher
        for name in (
            "elsevier",
            "springer",
            "wiley",
            "ieee",
            "american chemical society",
            "nature publishing",
        )
    ):
        return None
    if chinese(expected_title):
        return "chinese_title_fallback"
    return None
