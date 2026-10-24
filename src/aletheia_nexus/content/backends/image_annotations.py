"""Read small length labels in uniform image footers, retaining their geometry."""

from __future__ import annotations

import re

from aletheia_nexus.content.geometry import PageGeometry
from aletheia_nexus.content.image_tiles import union_box, vertical_tile_groups

LENGTH_LABEL = re.compile(r"\d+(?:\.\d+)?\s*(?:[uμµnpmck]?m)")


def length_label_words(rows):
    """Return one unqualified length; do not strip a legend's comparisons."""
    labels = []
    for offset, word in enumerate(rows):
        group = [word]
        text = word["text"].strip()
        if re.fullmatch(r"\d+(?:\.\d+)?", text) and offset + 1 < len(rows):
            group.append(rows[offset + 1])
            text += " " + group[-1]["text"].strip()
        if LENGTH_LABEL.fullmatch(text):
            labels.append((offset, group))
    if len(labels) != 1:
        return []
    offset, group = labels[0]
    if offset and re.search(r"[<>=≤≥≈~±]\s*$", rows[offset - 1]["text"]):
        return []
    return [group]


def footer_band(image):
    """Find the last separated text band above a uniform light/dark bottom edge.

    This deliberately excludes a bar touching the edge and textured image
    regions. No value, unit substitution, or microscopy magnification is used.
    """
    from PIL import ImageOps

    gray = image.convert("L")
    width, height = gray.size
    if width < 100 or height < 80:
        return None
    edge = gray.crop((0, height - 2, width, height)).histogram()
    dark = sum(edge[:64]) / (width * 2)
    light = sum(edge[192:]) / (width * 2)
    if max(dark, light) < 0.95:
        return None
    top = int(height * 0.88)
    footer = gray.crop((0, top, width, height))
    if dark > light:
        footer = ImageOps.invert(footer)
    fractions = [
        sum(footer.crop((0, y, width, y + 1)).histogram()[:150]) / width
        for y in range(footer.height)
    ]
    bands = []
    start = None
    for y, fraction in enumerate([*fractions, 0]):
        if 0.008 < fraction < 0.55:
            if start is None:
                start = y
        elif start is not None:
            if 4 <= y - start <= height * 0.08 and y < footer.height:
                bands.append((start, y))
            start = None
    if not bands:
        return None
    start, end = bands[-1]
    box = (0, top + max(0, start - 1), width, top + end + 1)
    return footer.crop((0, max(0, start - 1), width, end + 1)), box


def upright_images(page, geometry: PageGeometry, max_pixels=50_000_000):
    """Decode only painted, upright, unmirrored painted raster resources."""
    if geometry.rotation:
        return []
    from aletheia_nexus.content.backends.pdf_images import painted_images

    result = []
    for path, raw, matrix, visible, full in painted_images(page):
        a, b, c, d, e, f = matrix
        if abs(b) > 1e-6 or abs(c) > 1e-6 or a <= 0 or d <= 0:
            continue
        try:
            area = (full[2] - full[0]) * (full[3] - full[1])
            if area >= geometry.width * geometry.height * 0.65:
                continue
            if int(raw.get("/Width", 0)) * int(raw.get("/Height", 0)) > max_pixels:
                continue
            resource = page.images[list(path) if len(path) > 1 else path[0]]
            image = resource.image
            if image is None:
                continue
            if any(abs(v - f) > 0.01 for v, f in zip(visible, full)):
                # Crop in image coordinates. Even a sub-point rectangular trim
                # is common in publisher PDFs and must not suppress a figure.
                box = (
                    (visible[0] - full[0]) / (full[2] - full[0]) * image.width,
                    (full[3] - visible[3]) / (full[3] - full[1]) * image.height,
                    (visible[2] - full[0]) / (full[2] - full[0]) * image.width,
                    (full[3] - visible[1]) / (full[3] - full[1]) * image.height,
                )
                image = image.crop(box)
                if not image.width or not image.height:
                    continue
            bounds = geometry.box_points(visible)
            if not (
                0 <= bounds[0] < bounds[2] <= geometry.width
                and 0 <= bounds[1] < bounds[3] <= geometry.height
            ):
                continue
            name = "/".join(item.lstrip("/") for item in path)
            result.append((name, image, bounds))
        except (KeyError, TypeError, ValueError, OSError):
            continue
    return _join_painted_strips(result, max_pixels)


def _join_painted_strips(images, max_pixels):
    """Paste continuous, equally sampled strips; never resize or invent pixels."""
    from PIL import Image

    result = []
    for indices in vertical_tile_groups([i[2] for i in images], tolerance=0.002):
        group = [images[i] for i in indices]
        first = group[0][1]
        width = first.width
        height = sum(image.height for _, image, _ in group)
        sx = (group[0][2][2] - group[0][2][0]) / width
        sy = (group[0][2][3] - group[0][2][1]) / first.height
        if (
            len(group) == 1
            or width * height > max_pixels
            or any(
                image.width != width
                or abs((box[2] - box[0]) / image.width - sx) > sx * 0.005
                or abs((box[3] - box[1]) / image.height - sy) > sy * 0.005
                for _, image, box in group
            )
        ):
            result.extend(group)
            continue
        combined = Image.new("RGB", (width, height))
        y = 0
        for _, image, _ in group:
            combined.paste(image.convert("RGB"), (0, y))
            y += image.height
        result.append(
            (
                "+".join(name for name, _, _ in group),
                combined,
                union_box([box for _, _, box in group]),
            )
        )
    return result
