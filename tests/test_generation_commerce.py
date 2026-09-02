from app.models.models import Job

def test_job_has_commerce_dna_field():
    assert hasattr(Job, 'commerce_dna_json')
    assert hasattr(Job, 'concepts_json')
