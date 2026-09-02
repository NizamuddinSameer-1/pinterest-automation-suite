from app.pipeline.commerce_modules import COMMERCE_MODULES, get_commerce_triggers

def test_commerce_modules_count():
    assert len(COMMERCE_MODULES) >= 20
    assert "PRODUCT_FRONT_FOCUS" in COMMERCE_MODULES

def test_get_triggers_for_leather_jacket():
    triggers = get_commerce_triggers({"hero_prominence":"high","must_show":["zipper"]}, {"key":"apparel"})
    assert any("PRODUCT_FRONT_FOCUS" in t or "leather" in t.lower() for t in triggers)
