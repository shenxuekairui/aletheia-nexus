from aletheia_nexus.acquire.access.browser import (
    _install_context_event_capture,
    _install_context_request_guard,
)


class _Request:
    def __init__(self, url):
        self.url = url


class _Route:
    def __init__(self, url):
        self.request = _Request(url)
        self.continued = False
        self.aborted = None

    def continue_(self):
        self.continued = True

    def abort(self, reason):
        self.aborted = reason


class _Page:
    def __init__(self):
        self.handlers = {}

    def on(self, event, callback):
        self.handlers[event] = callback


class _Context:
    def __init__(self):
        self.handlers = {}
        self.route_handler = None
        self.pages = []

    def route(self, pattern, callback):
        assert pattern == "**/*"
        self.route_handler = callback

    def on(self, event, callback):
        self.handlers[event] = callback


class _Response:
    def __init__(self, url, content_type):
        self.url = url
        self.headers = {"content-type": content_type}


def test_context_request_guard_protects_popup_and_main_page_requests():
    context = _Context()
    blocked = _install_context_request_guard(context)

    public = _Route("https://publisher.example/article")
    context.route_handler(public)
    assert public.continued is True
    assert public.aborted is None

    local = _Route("http://127.0.0.1/private")
    context.route_handler(local)
    assert local.continued is False
    assert local.aborted == "blockedbyclient"
    assert blocked == ["http://127.0.0.1/private"]


def test_context_event_capture_observes_popup_pdf_and_download():
    context = _Context()
    first_page = _Page()
    context.pages.append(first_page)
    pdf_responses = []
    downloads = []

    _install_context_event_capture(
        context,
        pdf_responses=pdf_responses,
        downloads=downloads,
    )

    assert "download" in first_page.handlers

    context.handlers["response"](
        _Response("https://publisher.example/page", "text/html")
    )
    assert pdf_responses == []

    pdf = _Response("https://cdn.example/article.pdf", "application/pdf")
    context.handlers["response"](pdf)
    assert pdf_responses == [pdf]

    popup = _Page()
    context.handlers["page"](popup)
    assert "download" in popup.handlers

    download = object()
    popup.handlers["download"](download)
    assert downloads == [download]
