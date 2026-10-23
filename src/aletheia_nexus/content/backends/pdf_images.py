"""Painted image placements, including nested PDF Forms and their clipping."""

from __future__ import annotations

from pypdf.generic import ContentStream


def _compose(local, parent):
    a, b, c, d, e, f = local
    A, B, C, D, E, F = parent
    return (
        a * A + b * C,
        a * B + b * D,
        c * A + d * C,
        c * B + d * D,
        e * A + f * C + E,
        e * B + f * D + F,
    )


def _box(bounds, matrix):
    a, b, c, d, e, f = matrix
    points = [
        (a * x + c * y + e, b * x + d * y + f)
        for x in (bounds[0], bounds[2])
        for y in (bounds[1], bounds[3])
    ]
    return (
        min(x for x, y in points),
        min(y for x, y in points),
        max(x for x, y in points),
        max(y for x, y in points),
    )


def _intersect(first, second):
    return (
        max(first[0], second[0]),
        max(first[1], second[1]),
        min(first[2], second[2]),
        min(first[3], second[3]),
    )


def painted_images(page):
    """Yield resource paths, streams, transforms and visible page-space boxes.

    Resolve resources in each Form's scope. Track q/Q, cm and rectangular
    clipping, never confuse identically named images in different Forms.
    Nonrectangular clips retain their bounding region for local review.
    """
    identity = (1, 0, 0, 1, 0, 0)
    crop = tuple(float(x) for x in page.cropbox)

    def walk(stream, resources, matrix, clip, path, ancestors):
        stack, rectangles, pending_clip = [], [], False
        content = ContentStream(stream, page.pdf)
        for operands, operator in content.operations:
            if operator == b"q":
                stack.append((matrix, clip))
            elif operator == b"Q" and stack:
                matrix, clip = stack.pop()
            elif operator == b"cm":
                matrix = _compose(tuple(float(x) for x in operands), matrix)
            elif operator == b"re":
                x, y, w, h = (float(v) for v in operands)
                rectangles.append(_box((x, y, x + w, y + h), matrix))
            elif operator in {b"W", b"W*"}:
                pending_clip = True
            elif operator in {
                b"n",
                b"S",
                b"s",
                b"f",
                b"F",
                b"f*",
                b"B",
                b"B*",
                b"b",
                b"b*",
            }:
                if pending_clip and len(rectangles) == 1:
                    clip = _intersect(clip, rectangles[0])
                rectangles, pending_clip = [], False
            elif operator == b"Do" and operands:
                name = str(operands[0])
                reference = resources.get("/XObject", {}).get(name)
                if reference is None:
                    continue
                value = reference.get_object()
                resource_path = (*path, name)
                if value.get("/Subtype") == "/Image":
                    full = _box((0, 0, 1, 1), matrix)
                    visible = _intersect(full, clip)
                    if visible[2] > visible[0] and visible[3] > visible[1]:
                        yield resource_path, value, matrix, visible, full
                elif value.get("/Subtype") == "/Form" and id(value) not in ancestors:
                    child_matrix = _compose(
                        tuple(float(x) for x in value.get("/Matrix", identity)), matrix
                    )
                    child_clip = _intersect(clip, _box(value["/BBox"], child_matrix))
                    if child_clip[2] > child_clip[0] and child_clip[3] > child_clip[1]:
                        yield from walk(
                            value,
                            value.get("/Resources", resources),
                            child_matrix,
                            child_clip,
                            resource_path,
                            {*ancestors, id(value)},
                        )

    contents = page.get_contents()
    if contents is not None:
        yield from walk(contents, page.get("/Resources", {}), identity, crop, (), set())
