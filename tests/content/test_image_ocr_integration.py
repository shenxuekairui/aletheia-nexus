"""Exercise the optional bundled image models without publisher content/network."""

import os
import socket

import pytest


@pytest.mark.skipif(
    os.environ.get("AN_RUN_IMAGE_OCR_SMOKE") != "1",
    reason="Set AN_RUN_IMAGE_OCR_SMOKE=1 with the image-ocr extra installed",
)
def test_bundled_image_models_read_a_local_measurement_without_network(monkeypatch):
    from PIL import Image, ImageDraw, ImageFont

    from aletheia_nexus.content.backends.rapid_images import (
        _engine,
        execution_identity,
        read_image,
    )

    def no_network(*args, **kwargs):
        raise AssertionError("Installed image OCR must use its bundled local models")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    image = Image.new("RGB", (720, 150), "white")
    ImageDraw.Draw(image).text(
        (24, 40), "Current 12.5 mA", font=ImageFont.load_default(size=48), fill="black"
    )
    identity = execution_identity()
    assert len(identity["models_sha256"]) == 3
    readings = read_image(_engine(), image)
    assert any("12.5 ma" in r["text"].casefold() for r in readings)
    assert all(
        0 <= r["box"][0] < r["box"][2] <= image.width
        and 0 <= r["box"][1] < r["box"][3] <= image.height
        for r in readings
    )
