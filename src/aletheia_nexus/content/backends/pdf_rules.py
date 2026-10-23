"""Read painted straight PDF rules, retaining page-space geometry."""

from __future__ import annotations

from pypdf.generic import ContentStream

from aletheia_nexus.content.backends.pdf_images import _box, _compose, _intersect
from aletheia_nexus.content.models import PageObject


def painted_rules(page, geometry):
    identity = (1, 0, 0, 1, 0, 0)
    rules = []

    def point(p, m):
        x, y = map(float, p)
        a, b, c, d, e, f = m
        return a * x + c * y + e, b * x + d * y + f

    def walk(stream, resources, matrix, clip, ancestors):
        stack = []
        segments = []
        rectangles = []
        current = start = None
        pending_clip = False
        for args, op in ContentStream(stream, page.pdf).operations:
            if op == b"q":
                stack.append((matrix, clip))
            elif op == b"Q" and stack:
                matrix, clip = stack.pop()
            elif op == b"cm":
                matrix = _compose(tuple(map(float, args)), matrix)
            elif op == b"m":
                current = start = point(args, matrix)
            elif op == b"l":
                end = point(args, matrix)
                if current is not None:
                    segments.append((current, end))
                current = end
            elif op == b"h" and current is not None and start is not None:
                segments.append((current, start))
                current = start
            elif op in {b"c", b"v", b"y"}:
                current = None
            elif op == b"re":
                x, y, w, h = map(float, args)
                p = [
                    point(t, matrix)
                    for t in [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                ]
                segments.extend(zip(p, p[1:] + p[:1]))
                rectangles.append(_box((x, y, x + w, y + h), matrix))
            elif op in {b"W", b"W*"}:
                pending_clip = True
            elif op in {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"n"}:
                if op in {b"S", b"s", b"B", b"B*", b"b", b"b*"}:
                    for a, b in segments:
                        if abs(a[0] - b[0]) < 0.1 or abs(a[1] - b[1]) < 0.1:
                            bounds = (
                                min(a[0], b[0]) - 0.05,
                                min(a[1], b[1]) - 0.05,
                                max(a[0], b[0]) + 0.05,
                                max(a[1], b[1]) + 0.05,
                            )
                            rules.append(_intersect(bounds, clip))
                elif op in {b"f", b"F", b"f*"}:
                    rules.extend(
                        _intersect(b, clip)
                        for b in rectangles
                        if min(b[2] - b[0], b[3] - b[1]) < 2
                    )
                if pending_clip and len(rectangles) == 1:
                    clip = _intersect(clip, rectangles[0])
                segments = []
                rectangles = []
                current = start = None
                pending_clip = False
            elif op == b"Do" and args:
                ref = resources.get("/XObject", {}).get(str(args[0]))
                obj = ref.get_object() if ref else None
                if (
                    obj is not None
                    and obj.get("/Subtype") == "/Form"
                    and id(obj) not in ancestors
                ):
                    m = _compose(
                        tuple(map(float, obj.get("/Matrix", identity))), matrix
                    )
                    childclip = _intersect(clip, _box(obj["/BBox"], m))
                    walk(
                        obj,
                        obj.get("/Resources", resources),
                        m,
                        childclip,
                        {*ancestors, id(obj)},
                    )

    if page.get_contents() is not None:
        walk(
            page.get_contents(),
            page.get("/Resources", {}),
            identity,
            tuple(map(float, page.cropbox)),
            set(),
        )
    output = []
    seen = set()
    for box in rules:
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        x0, y0, x1, y1 = geometry.box_points(box)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(geometry.width, x1), min(geometry.height, y1)
        w, h = x1 - x0, y1 - y0
        if min(w, h) <= 0 or max(w, h) < 12 or min(w, h) > 2:
            continue
        key = tuple(round(v, 1) for v in (x0, y0, x1, y1))
        if key in seen:
            continue
        seen.add(key)
        output.append(
            PageObject(
                object_type="horizontal-rule" if w > h else "vertical-rule",
                name=f"rule-{len(output) + 1}",
                bbox=(
                    x0 / geometry.width,
                    y0 / geometry.height,
                    x1 / geometry.width,
                    y1 / geometry.height,
                ),
            )
        )
    merged = []
    for kind in ("horizontal-rule", "vertical-rule"):
        horizontal = kind == "horizontal-rule"
        axis = 1 if horizontal else 0
        cross_tolerance = 0.5 / (geometry.height if horizontal else geometry.width)
        gap_tolerance = 0.75 / (geometry.width if horizontal else geometry.height)
        groups = []
        for obj in sorted(
            (o for o in output if o.object_type == kind),
            key=lambda o: (o.bbox[axis] + o.bbox[axis + 2]) / 2,
        ):
            center = (obj.bbox[axis] + obj.bbox[axis + 2]) / 2
            if (
                not groups
                or abs(
                    center
                    - (groups[-1][0].bbox[axis] + groups[-1][0].bbox[axis + 2]) / 2
                )
                > cross_tolerance
            ):
                groups.append([])
            groups[-1].append(obj)
        along = 1 - axis
        for group in groups:
            intervals = []
            for obj in sorted(group, key=lambda o: o.bbox[along]):
                b = obj.bbox
                if intervals and b[along] <= intervals[-1][along + 2] + gap_tolerance:
                    a = intervals[-1]
                    intervals[-1] = (
                        min(a[0], b[0]),
                        min(a[1], b[1]),
                        max(a[2], b[2]),
                        max(a[3], b[3]),
                    )
                else:
                    intervals.append(b)
            for box in intervals:
                merged.append(
                    PageObject(
                        object_type=kind, name=f"rule-{len(merged) + 1}", bbox=box
                    )
                )
    return tuple(merged)
