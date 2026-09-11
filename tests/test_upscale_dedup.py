"""
Tests for the pin enhancement pipeline.

The regression these guard against: the pipeline used to run on save
(flow_automator) and again at publish (output_service). Because the watermark
crop was proportional to the *current* height, the second run cropped a second,
larger band — pins ended up on four different aspect ratios — and the unsharp
mask was applied twice, which is what produced the ringing halos.
"""

from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.services.anti_ai_processor import (
    _watermark_crop,
    postprocess_batch,
    postprocess_image,
)


def _write(path: Path, size=(1000, 1500), color=(200, 100, 50)) -> Path:
    Image.new("RGB", size, color=color).save(path, format="JPEG")
    return path


def test_postprocess_image_skip_colab(tmp_path: Path):
    img_path = _write(tmp_path / "test_pin.jpg")

    with patch("app.services.anti_ai_processor._try_colab_upscale") as mock_colab:
        with patch(
            "app.services.anti_ai_processor._resolve_colab_url",
            return_value="https://test-colab.trycloudflare.com",
        ):
            # skip_colab=True must never reach the upscaler.
            out = postprocess_image(img_path, skip_colab=True)
            assert Path(out).exists()
            assert mock_colab.call_count == 0

            # A fresh, unenhanced render with skip_colab=False must reach it.
            raw_path = _write(tmp_path / "raw_pin.jpg")
            mock_colab.return_value = None  # simulate the local fallback
            out2 = postprocess_image(raw_path, skip_colab=False)
            assert Path(out2).exists()
            assert mock_colab.call_count == 1


def test_already_enhanced_image_is_not_processed_again(tmp_path: Path):
    """A second pass over an enhanced file must change nothing at all."""
    img_path = _write(tmp_path / "pin.jpg")
    postprocess_image(img_path)
    first = img_path.read_bytes()

    with patch("app.services.anti_ai_processor._try_colab_upscale") as mock_colab:
        with patch(
            "app.services.anti_ai_processor._resolve_colab_url",
            return_value="https://test-colab.trycloudflare.com",
        ):
            postprocess_image(img_path)
            assert mock_colab.call_count == 0

    assert img_path.read_bytes() == first, "the second pass rewrote an enhanced file"


def test_watermark_crop_is_idempotent():
    """
    A file cropped before the marker existed must not be cropped again. The
    guard is the aspect ratio the crop targets, so this holds even for files
    written by the old code.
    """
    raw = Image.new("RGB", (768, 1376), color=(120, 120, 120))
    cropped, did_crop = _watermark_crop(raw)
    assert did_crop, "the raw render should be cropped"
    assert cropped.size[0] == 768 and cropped.size[1] < 1376

    again, did_crop_again = _watermark_crop(cropped)
    assert not did_crop_again, "the crop ran twice on the same image"
    assert again.size == cropped.size


def test_pipeline_never_upscales_past_the_target(tmp_path: Path):
    """Target width is a ceiling; a larger image comes down to it."""
    img_path = _write(tmp_path / "big.jpg", (1440, 2150))
    postprocess_image(img_path)
    assert Image.open(img_path).size[0] == 1080


def test_postprocess_batch_skip_colab(tmp_path: Path):
    p1 = _write(tmp_path / "p1.jpg", (800, 1200), (10, 20, 30))
    p2 = _write(tmp_path / "p2.jpg", (800, 1200), (30, 40, 50))

    with patch("app.services.anti_ai_processor._try_colab_upscale") as mock_colab:
        with patch(
            "app.services.anti_ai_processor._resolve_colab_url",
            return_value="https://test-colab.trycloudflare.com",
        ):
            results = postprocess_batch([p1, p2], skip_colab=True)
            assert len(results) == 2
            assert mock_colab.call_count == 0
