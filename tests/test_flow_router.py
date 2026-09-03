import pytest
from pathlib import Path
from app.services import flow_router

def test_get_project_pool():
    pool = flow_router.get_project_pool()
    assert len(pool) >= 10
    assert all('labs.google/fx/tools/flow/project/' in url for url in pool)

def test_round_robin_rotation():
    pool = flow_router.get_project_pool()
    flow_router.set_router_strategy('round_robin')
    
    # Run two full cycles of sequential rotation
    picks = []
    for _ in range(len(pool)):
        candidates = flow_router.get_all_project_candidates(strategy='round_robin')
        picks.append(candidates[0])
    
    # All picks in one cycle must be unique
    assert len(set(picks)) == len(pool)
    
    # Next pick should wrap around to the first one
    next_candidates = flow_router.get_all_project_candidates(strategy='round_robin')
    assert next_candidates[0] == picks[0]

def test_random_strategy():
    flow_router.set_router_strategy('random')
    candidates = flow_router.get_all_project_candidates(strategy='random')
    assert len(candidates) >= 10
    # First candidate is in pool
    assert candidates[0] in flow_router.get_project_pool()

def test_router_status():
    status = flow_router.get_router_status()
    assert 'projects' in status
    assert 'strategy' in status
    assert 'current_index' in status
    assert 'usage_counts' in status

def test_add_and_remove_project():
    test_uuid = 'test-unit-test-uuid-99999'
    test_url = f'https://labs.google/fx/tools/flow/project/{test_uuid}'
    
    ok, msg = flow_router.add_project(test_url)
    assert ok
    assert test_url in flow_router.get_project_pool()
    
    ok, msg = flow_router.remove_project(test_uuid)
    assert ok
    assert test_url not in flow_router.get_project_pool()
