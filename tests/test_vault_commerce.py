from pathlib import Path
from app.services.vault_sync import sync_commerce_node

def test_sync_writes_commerce_md(tmp_path):
    path = sync_commerce_node(job_id="test", commerce_dna={"hero_prominence": "high"})
    assert Path(path).exists()
    assert "hero_prominence" in Path(path).read_text()
