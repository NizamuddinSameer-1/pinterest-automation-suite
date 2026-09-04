import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
from app.services.anti_ai_processor import postprocess_image, postprocess_batch


def test_postprocess_image_skip_colab(tmp_path: Path):
    # Create dummy test image
    img_path = tmp_path / "test_pin.jpg"
    img = Image.new("RGB", (1000, 1500), color=(200, 100, 50))
    img.save(img_path, format="JPEG")

    with patch("app.services.anti_ai_processor._try_colab_upscale") as mock_colab:
        with patch("app.services.anti_ai_processor._resolve_colab_url", return_value="https://test-colab.trycloudflare.com"):
            # With skip_colab=True, it should NEVER call _try_colab_upscale
            out = postprocess_image(img_path, skip_colab=True)
            assert Path(out).exists()
            assert mock_colab.call_count == 0

            # With skip_colab=False, it SHOULD call _try_colab_upscale
            mock_colab.return_value = None  # simulate fallback
            out2 = postprocess_image(img_path, skip_colab=False)
            assert Path(out2).exists()
            assert mock_colab.call_count == 1


def test_postprocess_batch_skip_colab(tmp_path: Path):
    p1 = tmp_path / "p1.jpg"
    p2 = tmp_path / "p2.jpg"
    Image.new("RGB", (800, 1200), color=(10, 20, 30)).save(p1)
    Image.new("RGB", (800, 1200), color=(30, 40, 50)).save(p2)

    with patch("app.services.anti_ai_processor._try_colab_upscale") as mock_colab:
        with patch("app.services.anti_ai_processor._resolve_colab_url", return_value="https://test-colab.trycloudflare.com"):
            results = postprocess_batch([p1, p2], skip_colab=True)
            assert len(results) == 2
            assert mock_colab.call_count == 0
