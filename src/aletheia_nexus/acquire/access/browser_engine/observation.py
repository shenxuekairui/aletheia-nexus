"""Deadline-bound, read-only observations on Playwright's existing event loop.

title(), content(), evaluate() and frame_element() do not accept a timeout.
Keep the private sync/async bridge here, rather than using a worker thread
(Playwright sync objects are thread-affine) or changing browser-wide defaults.
"""

import asyncio


def _consume_result(task):
    if not task.cancelled():
        task.exception()


async def _with_deadline(operation, seconds):
    task = asyncio.create_task(operation)
    try:
        done, _ = await asyncio.wait({task}, timeout=max(0.001, seconds))
        if task in done:
            return task.result()
        # Do not await cancellation here: even transport cleanup must not hold
        # the caller past its read budget. Playwright aborts the protocol call.
        task.cancel()
        task.add_done_callback(_consume_result)
        raise TimeoutError("Browser observation exceeded its read deadline")
    finally:
        if not task.done() and not task.cancelling():
            task.cancel()
            task.add_done_callback(_consume_result)


def bounded_read(target, method, *args, timeout=2.0, **kwargs):
    """Run a read with a wall-clock deadline, without touching the page state."""
    impl = getattr(target, "_impl_obj", None)
    sync = getattr(target, "_sync", None)
    if impl is None or not callable(sync):
        # Lightweight non-Playwright adapters used by the unit tests.
        return getattr(target, method)(*args, **kwargs)
    return sync(_with_deadline(getattr(impl, method)(*args, **kwargs), timeout))


def frame_visible(frame, *, timeout=2.0):
    impl = getattr(frame, "_impl_obj", None)
    sync = getattr(frame, "_sync", None)
    if impl is None or not callable(sync):
        return frame.frame_element().is_visible()

    async def observe():
        element = await impl.frame_element()
        try:
            return await element.is_visible()
        finally:
            await element.dispose()

    return sync(_with_deadline(observe(), timeout))


def native_pdf_url(page, *, frame=None, timeout=2.0):
    """Read the browser's document MIME without using the page JS context.

    This only identifies a viewer; the acquisition pipeline still validates the
    downloaded bytes and article identity before declaring delivery successful.
    """
    impl = getattr(page, "_impl_obj", None)
    sync = getattr(page, "_sync", None)
    if impl is None or not callable(sync):
        return ""

    async def observe():
        session = await impl.context.new_cdp_session(impl)
        try:
            tree = await session.send("Page.getFrameTree")
            target = (
                getattr(frame, "_impl_obj", None)
                if frame is not None
                else impl.main_frame
            )
            pending = [tree.get("frameTree", {})]
            documents = []
            while pending:
                node = pending.pop()
                candidate = node.get("frame", {})
                if frame is None:
                    documents.append(candidate)
                    break
                if (
                    candidate.get("url", "").split("#", 1)[0]
                    == target.url.split("#", 1)[0]
                ):
                    documents.append(candidate)
                pending.extend(node.get("childFrames", []))
            if not documents or any(
                d.get("mimeType", "").lower() != "application/pdf" for d in documents
            ):
                return ""
            document = documents[0]
            url = document.get("url", "")
            if (
                document.get("mimeType", "").lower() == "application/pdf"
                and url.split("#", 1)[0] == target.url.split("#", 1)[0]
            ):
                return url
            return ""
        finally:
            await session.detach()

    try:
        return sync(_with_deadline(observe(), timeout))
    except Exception:
        # Non-Chromium contexts or a target in transition use the ordinary
        # bounded DOM observation. Failure is not evidence of a PDF or login.
        return ""
