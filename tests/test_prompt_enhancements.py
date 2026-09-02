"""
Tests for Prompt System Enhancements (Items 1 through 7):
  • Deterministic PIL image measurements (palette, luminance, contrast, sharpness)
  • Measured facts grounding in lighting & prompt compilation
  • Per-class module allowlist (tech/kitchen clean photography vs apparel UGC)
  • Module attribution in CompileResult and PromptVersion
  • Multi-concept prompt compilation and PromptVersion attribution
"""

import json
from pathlib import Path
from PIL import Image
import pytest

from app.models.models import PromptVersion
from app.pipeline.product_taxonomy import resolve_class
from app.pipeline.prompt_compiler import compile_prompt
from app.pipeline.prompt_modules import (
    CLEAN_PRODUCT_CLASSES,
    MESSY_UGC_MODULES,
    get_relevant_module_items,
    get_relevant_modules,
)
from app.services.image_measurements import measure_image


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """Create a temporary test image with known dimensions and colors."""
    img_path = tmp_path / "test_ref.png"
    img = Image.new("RGB", (300, 300), color=(180, 120, 80))
    img.save(img_path)
    return img_path


def test_image_measurements_deterministic(sample_image: Path):
    """Test that physical metrics (palette, luminance, contrast, sharpness) are computed accurately."""
    metrics = measure_image(sample_image)
    assert metrics["exists"] is True
    assert metrics["width"] == 300
    assert metrics["height"] == 300
    assert metrics["aspect_ratio"] == "1:1"
    assert len(metrics["dominant_palette"]) > 0
    assert 0 <= metrics["mean_luminance"] <= 255
    assert metrics["rms_contrast"] >= 0
    assert metrics["laplacian_variance"] >= 0
    assert "optical_summary" in metrics


def test_clean_class_module_filtering():
    """Verify that tech/kitchen products exclude messy bed/apparel UGC modules."""
    tech_class = resolve_class("tech")
    scene = {
        "human_presence": "none",
        "creative_format": "flat_lay",
        "framing": "medium",
        "location": "clean studio desk",
    }

    items = get_relevant_module_items(scene, tech_class)
    keys = [k for k, _ in items]

    assert tech_class.key in CLEAN_PRODUCT_CLASSES
    # Ensure none of the messy bedroom/clearance tags appear on tech products
    for messy in MESSY_UGC_MODULES:
        assert messy not in keys, f"Found messy module {messy} in clean tech pin"


def test_apparel_allows_ugc_modules():
    """Verify that apparel/lifestyle pins retain lived-in UGC textures."""
    apparel_class = resolve_class("apparel")
    scene = {
        "human_presence": "holding_product",
        "creative_format": "bedroom_home",
        "framing": "medium",
        "location": "cozy bedroom",
    }

    items = get_relevant_module_items(scene, apparel_class)
    keys = [k for k, _ in items]

    assert "WRINKLED_LINEN_DUVET" in keys or "HAND_PRESSURE_GRIP" in keys


def test_prompt_compiler_records_module_keys_and_measured_palette():
    """Test that CompileResult includes module_keys and lighting grounds in measured facts."""
    product_class = resolve_class("kitchen")
    visual_dna = {
        "capture_identity": {"camera_position": "eye_level", "framing": "medium"},
        "composition_dna": {"subject_placement": "center"},
        "lighting_dna": {"source": "morning sun", "contrast": "soft", "warmth": "warm neutral"},
        "camera_dna": {"sharpness": "crisp focus", "noise": "fine", "hdr": "balanced"},
        "realism_dna": {"anti_studio": True},
        "measured_facts": {
            "dominant_palette": ["#c2a688", "#543e2e", "#eae4dc"],
            "mean_luminance": 140.5,
            "rms_contrast": 55.2,
        },
    }
    product = {
        "name": "Ceramic Pour-Over Mug",
        "merchant": "KitchenStyle",
        "brand": "KitchenStyle",
    }
    product_truth = {
        "must_preserve": ["stoneware ceramic", "earthy matte finish"],
        "key_attributes": ["stoneware ceramic", "earthy matte finish"],
        "must_not_invent": [],
    }
    scene = {
        "capture_motivation": "A coffee lover showing their morning pour-over setup on counter",
        "subject_action": "resting on oak table",
        "creative_format": "styled_surface",
        "framing": "closeup",
        "human_presence": "none",
        "location": "sunlit kitchen counter",
    }

    result = compile_prompt(
        visual_dna=visual_dna,
        product=product,
        product_truth=product_truth,
        scene=scene,
    )

    assert result.is_valid is True
    assert len(result.module_keys) > 0
    # Check that module keys are tracked for critique attribution
    assert all(isinstance(k, str) for k in result.module_keys)
    # Check that dominant tones are grounded in prompt lighting text
    assert "#c2a688" in result.prompt


def test_prompt_version_attribution_model():
    """Test that PromptVersion fields concept_index, concept_json, and modules_json work correctly."""
    modules = ["RAW_OAK_WOOD_GRAIN", "NATURAL_OPTICAL_FALLOFF"]
    concept = {"hook": "Aesthetic morning ritual", "angle": "Pour-over moment"}

    pv = PromptVersion(
        job_id="job_test_123",
        version=1,
        prompt_text="A clean morning photograph of a ceramic mug on oak grain.",
        concept_index=0,
        concept_json=json.dumps(concept),
        modules_json=json.dumps(modules),
    )

    assert pv.concept_index == 0
    assert json.loads(pv.concept_json)["hook"] == "Aesthetic morning ritual"
    assert json.loads(pv.modules_json) == modules
