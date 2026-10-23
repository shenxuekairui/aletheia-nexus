"""Optional local OCR of painted figures at their original pixel resolution.

No chemistry-based substitutions or value inference is performed. Models are
loaded from the installed wheel, and their hashes are part of parse identity.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from importlib import metadata, util
from pathlib import Path

from aletheia_nexus.content.backends.image_annotations import upright_images
from aletheia_nexus.content.backends.image_axes import associate_axes
from aletheia_nexus.content.backends.image_bars import associate_bars
from aletheia_nexus.content.backends.image_panels import (
    associate_scales,
    join_length_fragments,
    length_key,
    read_panel_markers,
)
from aletheia_nexus.content.backends.image_readings import (
    complete_edge_scripts,
    ink_colour,
    merge_complete_reading,
    reading_key,
    reread_formula_markup,
    reread_uncertain_lines,
)
from aletheia_nexus.content.backends.image_tick_crops import read_tick_margins
from aletheia_nexus.content.backends.image_vertical import read_vertical_labels
from aletheia_nexus.content.geometry import PageGeometry
from aletheia_nexus.content.models import LayoutLine, PageLayout

_MODELS = {
    "Det": "PP-OCRv6_det_small.onnx",
    "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "Rec": "PP-OCRv6_rec_small.onnx",
}


def model_paths():
    spec = util.find_spec("rapidocr")
    if spec is None or not spec.origin:
        raise RuntimeError("Figure OCR requires the optional 'image-ocr' dependencies")
    root = Path(spec.origin).parent / "models"
    paths = {kind: root / name for kind, name in _MODELS.items()}
    if not all(p.is_file() for p in paths.values()):
        raise RuntimeError(
            "Figure OCR bundled models are missing; reinstall image-ocr dependencies"
        )
    return paths


@lru_cache(maxsize=1)
def execution_identity():
    try:
        paths = model_paths()
        return {
            "adapter_version": "1.5.3",
            "rapidocr": metadata.version("rapidocr"),
            "onnxruntime": metadata.version("onnxruntime"),
            "models_sha256": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in paths.values()
            },
        }
    except (RuntimeError, metadata.PackageNotFoundError) as exc:
        return {"unavailable": str(exc)}


@lru_cache(maxsize=1)
def _engine():
    from rapidocr import RapidOCR

    params = {f"{kind}.model_path": str(p) for kind, p in model_paths().items()}
    params["Global.log_level"] = "error"
    return RapidOCR(params=params)


def extract_image_annotations(page, page_number, max_pixels):
    geometry = PageGeometry.from_page(page)
    engine = _engine()
    lines = []
    warnings = []
    for name, image, bounds in upright_images(page, geometry, max_pixels):
        if image.width < 80 or image.height < 40:
            continue
        records = read_image(engine, image)
        sx = (bounds[2] - bounds[0]) / image.width
        sy = (bounds[3] - bounds[1]) / image.height
        for record in associate_axes(
            associate_scales(associate_bars(records, image), image)
        ):
            text, score = record["text"], record["score"]
            colour = record.get("ink_colour")
            if colour and record.get("method") not in {
                "positioned-panel-scale",
                "positioned-axis-label-ticks",
            }:
                text = f"Image text ({colour}): {text}"
            x0, y0, x1, y1 = record["box"]
            if record.get("warning"):
                warnings.append(
                    {
                        "code": record["warning"],
                        "page": page_number,
                        "bbox": [
                            (bounds[0] + x0 * sx) / geometry.width,
                            (bounds[3] - y1 * sy) / geometry.height,
                            (bounds[0] + x1 * sx) / geometry.width,
                            (bounds[3] - y0 * sy) / geometry.height,
                        ],
                        "detail": (
                            "The source-image scale label and two agreeing crop readings differ in unit. Inspect the local glyphs; both readings are retained and no unit was inferred or silently corrected."
                            if record["warning"] == "IMAGE_SCALE_UNIT_CONFLICT"
                            else "Observed axis tick readings are not monotonic; inspect the local signs/digits or source axis convention. No value was inferred or corrected."
                        ),
                    }
                )
            # Single characters are usually curve markers or atom labels. Keep
            # reliable panel letters; do not promote other isolated symbols.
            minimum = (
                0.65
                if record.get("method") == "rapidocr-corroborated-formula-script"
                else 0.85
            )
            if score < minimum or not text.strip():
                continue
            if len(text.strip()) == 1 and not re.fullmatch(
                r"[a-zA-Z0-9]", text.strip()
            ):
                continue
            lines.append(
                LayoutLine(
                    text=text.strip(),
                    x0=max(bounds[0], bounds[0] + x0 * sx),
                    x1=min(bounds[2], bounds[0] + x1 * sx),
                    y0=max(bounds[1], bounds[3] - y1 * sy),
                    y1=min(bounds[3], bounds[3] - y0 * sy),
                    font_size=max(1, min((x1 - x0) * sx, (y1 - y0) * sy)),
                    extraction_method=record.get("method", "rapidocr-source-image"),
                    extraction_confidence=float(score),
                    source_engines=(
                        f"rapidocr@{metadata.version('rapidocr')}+image-label",
                    ),
                    content_region="ocr-alternative"
                    if record.get("alternative")
                    else "figure",
                    uncertain=True,
                )
            )
    return PageLayout(
        page=page_number,
        width=geometry.width,
        height=geometry.height,
        media_box=geometry.media_box,
        crop_box=geometry.crop_box,
        rotation=geometry.rotation,
        lines=tuple(lines),
        warnings=tuple(warnings),
    )


def read_image(engine, image):
    from PIL import ImageChops, ImageOps

    def read(prepared, factor=1):
        # Small embedded figures often contain labels only a few pixels tall.
        # Enlarge uniformly, retaining source-space coordinates.
        result = engine(
            prepared.resize((prepared.width * factor, prepared.height * factor))
            if factor > 1
            else prepared,
            use_det=True,
            use_cls=True,
        )
        if result.boxes is None or result.txts is None:
            return []
        return [
            dict(
                text=t.strip(),
                score=float(s),
                box=(
                    float(min(p[0] for p in b)) / factor,
                    float(min(p[1] for p in b)) / factor,
                    float(max(p[0] for p in b)) / factor,
                    float(max(p[1] for p in b)) / factor,
                ),
            )
            for t, s, b in zip(result.txts, result.scores, result.boxes)
        ]

    rgb = image.convert("RGB")
    red, green, blue = rgb.split()
    spread = ImageChops.subtract(
        ImageChops.lighter(red, ImageChops.lighter(green, blue)),
        ImageChops.darker(red, ImageChops.darker(green, blue)),
    )
    hist = spread.histogram()
    colored = sum(hist[71:]) / (image.width * image.height)
    sparse_labels = 0.0005 < colored < 0.08
    factor = (
        2
        if sparse_labels
        and min(image.size) < 1000
        and image.width * image.height < 1_500_000
        else 1
    )
    records = join_length_fragments(read(rgb, factor))
    for record in records:
        if not record.get("alternative"):
            colour = ink_colour(rgb, record["box"])
            if colour:
                record["ink_colour"] = colour
    # Colour plots can print pale labels and tiny exponents which disappear
    # under a luminance threshold. Isolate existing saturated ink; two scales
    # must agree before completing an existing source reading.
    light = sum(rgb.convert("L").histogram()[216:]) / (image.width * image.height)
    if 0.0005 < colored < 0.8:
        mask = ImageOps.invert(spread.point(lambda v: 255 if v > 70 else 0)).convert(
            "RGB"
        )
        first = read(mask)
        second = read(mask, 2) if image.width * image.height < 1_500_000 else first
        for candidate in first + second:
            if candidate["score"] < 0.85 or not (
                re.search(r"\d", candidate["text"])
                and re.search(r"[A-Za-z%]", candidate["text"])
            ):
                continue
            if not any(
                reading_key(other["text"]) == reading_key(candidate["text"])
                and other["score"] >= 0.8
                for other in (second if candidate in first else first)
            ):
                continue
            candidate["method"] = "rapidocr-colour-completed-reading"
            merge_complete_reading(records, candidate)
    # Sparse coloured annotations on an otherwise grey micrograph can be
    # isolated without altering their glyphs. Plot curves do not become text.
    if sparse_labels:
        mask = ImageOps.invert(spread.point(lambda v: 255 if v > 70 else 0)).convert(
            "RGB"
        )
        for record in read(mask, factor):
            if record["score"] < 0.9 or not (
                length_key(record["text"]) or re.fullmatch("[A-Za-z]", record["text"])
            ):
                continue
            x0, y0, x1, y1 = record["box"]
            near = [
                r
                for r in records
                if max(x0, r["box"][0]) < min(x1, r["box"][2])
                and max(y0, r["box"][1]) < min(y1, r["box"][3])
                and not r.get("alternative")
            ]
            same = [
                r
                for r in near
                if (
                    length_key(r["text"])
                    and length_key(r["text"]) == length_key(record["text"])
                )
                or r["text"] == record["text"]
            ]
            partial = [
                r
                for r in near
                if length_key(record["text"])
                and not length_key(r["text"])
                and re.fullmatch(r"(?:\d+(?:\.\d+)?|[uμµnpmc]?m)", r["text"])
                and r["text"].replace(" ", "") in record["text"].replace(" ", "")
            ]
            if near and not same and len(partial) != len(near):
                record["alternative"] = True
            else:
                for old in [*same, *partial]:
                    old["alternative"] = True
            record["method"] = "rapidocr-colour-isolated-image-label"
            records.append(record)

    def recognize(crop):
        result = engine(crop, use_det=False, use_cls=False)
        if result.txts is None or len(result.txts) != 1:
            return None
        return result.txts[0], float(result.scores[0])

    records = complete_edge_scripts(records, rgb, recognize)
    records = reread_formula_markup(records, rgb, recognize)
    records = reread_uncertain_lines(records, rgb, recognize)
    records = read_tick_margins(records, rgb, read, recognize)
    for record in list(records):
        if re.search(r"°\s*℃", record["text"]):
            records.append({**record, "alternative": True})
            record["text"] = re.sub(r"°\s*℃", "°C", record["text"])
            record["method"] = "rapidocr-compatibility-unit-normalized"
        if (
            not record.get("alternative")
            and light > 0.5
            and (re.search(r"[A-Za-z]", record["text"]))
        ):
            colour = ink_colour(rgb, record["box"])
            if colour:
                record["ink_colour"] = colour
    return read_vertical_labels(read_panel_markers(records, rgb, recognize), rgb, read)
