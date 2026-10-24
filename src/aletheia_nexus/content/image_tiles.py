"""Identify contiguous painted image strips without filling gaps or overlaps."""

from __future__ import annotations


def vertical_tile_groups(boxes, *, tolerance):
    """Return source indices, top first, for equal-width edge-touching strips.

    A column with overlapping resources is left untouched. This deliberately
    does not infer a figure boundary from whitespace, captions or subject matter.
    """
    columns = []
    for index in sorted(range(len(boxes)), key=lambda i: (boxes[i][0], boxes[i][2])):
        box = boxes[index]
        matches = [
            column
            for column in columns
            if abs(box[0] - boxes[column[0]][0]) <= tolerance
            and abs(box[2] - boxes[column[0]][2]) <= tolerance
        ]
        if len(matches) == 1:
            matches[0].append(index)
        else:
            columns.append([index])
    groups = []
    for column in columns:
        ordered = sorted(column, key=lambda i: -boxes[i][3])
        if any(
            boxes[lower][3] > boxes[upper][1] + tolerance
            for upper, lower in zip(ordered, ordered[1:])
        ):
            groups.extend([i] for i in ordered)
            continue
        group = []
        for index in ordered:
            if group and abs(boxes[group[-1]][1] - boxes[index][3]) > tolerance:
                groups.append(group)
                group = []
            group.append(index)
        if group:
            groups.append(group)
    return sorted(groups, key=min)


def union_box(boxes):
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
