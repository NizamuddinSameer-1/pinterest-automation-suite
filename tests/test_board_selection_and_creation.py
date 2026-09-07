"""
Unit and integration tests for automatic Pinterest board selection and creation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch
import pytest

from app.services import board_catalog as bc
from app.services import pinterest_publisher as pp


def test_find_best_board_match_exact():
    boards = ["Pumpkin Patch Outfits", "Cozy Fall & Halloween Finds", "Recipes"]
    
    # Exact normalized
    assert bc.find_best_board_match("Pumpkin Patch Outfits", boards) == "Pumpkin Patch Outfits"
    assert bc.find_best_board_match("pumpkin patch outfits", boards) == "Pumpkin Patch Outfits"
    
    # Ampersand vs and
    assert bc.find_best_board_match("Cozy Fall and Halloween Finds", boards) == "Cozy Fall & Halloween Finds"


def test_find_best_board_match_containment_and_fuzzy():
    boards = ["Pumpkin Patch Outfits", "Aesthetic Cozy Living", "Home Bar Ideas"]

    # Substring / extra words
    match1 = bc.find_best_board_match("Pumpkin Patch Outfit Ideas", boards)
    assert match1 == "Pumpkin Patch Outfits"

    match2 = bc.find_best_board_match("Cozy Living Aesthetic", boards)
    assert match2 == "Aesthetic Cozy Living"

    # Completely different niche should return None
    assert bc.find_best_board_match("Automotive Engine Repair", boards) is None


def test_check_board_resolves_fuzzy(tmp_path):
    cache_file = tmp_path / "boards.json"
    with patch.object(bc, "CATALOG_PATH", cache_file):
        bc.write_catalog(["Pumpkin Patch Outfits", "Aesthetic Living"], source="test")
        
        # Exact match
        check_exact = bc.check_board("Pumpkin Patch Outfits")
        assert check_exact.verdict == bc.OK
        assert check_exact.resolved == "Pumpkin Patch Outfits"
        assert not check_exact.blocks_publish

        # Fuzzy match resolves to existing board
        check_fuzzy = bc.check_board("Pumpkin Patch Outfit Ideas")
        assert check_fuzzy.verdict == bc.OK
        assert check_fuzzy.resolved == "Pumpkin Patch Outfits"
        assert not check_fuzzy.blocks_publish


def test_check_board_will_create_vs_unknown(tmp_path):
    cache_file = tmp_path / "boards.json"
    with patch.object(bc, "CATALOG_PATH", cache_file):
        bc.write_catalog(["Pumpkin Patch Outfits"], source="test")
        
        # When auto_create is True -> verdict WILL_CREATE, does not block
        check_create = bc.check_board("Retro Futurism Outfits", auto_create=True)
        assert check_create.verdict == bc.WILL_CREATE
        assert not check_create.blocks_publish
        assert "will be automatically created" in check_create.message

        # When auto_create is False -> verdict UNKNOWN_BOARD, blocks publish
        check_blocked = bc.check_board("Retro Futurism Outfits", auto_create=False)
        assert check_blocked.verdict == bc.UNKNOWN_BOARD
        assert check_blocked.blocks_publish
        assert "was not in your Pinterest board list" in check_blocked.message


class FakeCreateLocator:
    def __init__(self, page: "FakeCreatePage", kind: str, texts=(), checked: bool = False):
        self.page = page
        self.kind = kind
        self.texts = list(texts)
        self.checked = checked
        self.filled_value = ""

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return len(self.texts) if self.texts else (1 if self.kind else 0)

    def nth(self, i: int):
        return FakeCreateLocator(self.page, self.kind, [self.texts[i]])

    async def is_visible(self) -> bool:
        return bool(self.texts or self.kind)

    async def inner_text(self, timeout=None) -> str:
        if self.kind == "button":
            return self.page.selected
        return self.texts[0] if self.texts else ""

    async def is_checked(self) -> bool:
        return self.checked

    async def uncheck(self, timeout=None) -> None:
        self.checked = False

    async def fill(self, value: str, timeout=None) -> None:
        self.filled_value = value

    async def click(self, timeout=None) -> None:
        if self.kind == "row":
            self.page.selected = pp._board_row_name(self.texts[0])


class FakeCreatePage:
    def __init__(self, existing_boards):
        self.boards = list(existing_boards)
        self.selected = "Select a board"
        self.created_name = None
        self.menu_open = False

    def on(self, *a, **k):
        pass

    def get_by_role(self, role: str, name=None, exact: bool = False):
        return FakeCreateLocator(self, "other", [])

    def locator(self, sel: str):
        if sel in pp.SEL_BOARD_BUTTON:
            return FakeCreateLocator(self, "button", [self.selected])
        if sel in pp.SEL_BOARD_SEARCH:
            return FakeCreateLocator(self, "search", ["search"])
        if sel in pp.SEL_BOARD_OPTION:
            return FakeCreateLocator(self, "row", [f"{b}\n10 pins" for b in self.boards])
        if sel in pp.SEL_CREATE_BOARD_BTN:
            return FakeCreateLocator(self, "create_btn", ["Create board"])
        if sel in pp.SEL_CREATE_BOARD_INPUT:
            loc = FakeCreateLocator(self, "input", [""])
            self.input_loc = loc
            return loc
        if sel in pp.SEL_CREATE_BOARD_SECRET_CHECKBOX:
            return FakeCreateLocator(self, "secret", [""], checked=True)
        if sel in pp.SEL_CREATE_BOARD_SUBMIT:
            return FakeCreateLocator(self, "submit", ["Create"])
        return FakeCreateLocator(self, "", [])

    async def wait_for_timeout(self, ms: int) -> None:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_choose_board_fuzzy_and_auto_create(tmp_path):
    cache_file = tmp_path / "boards_test.json"
    with patch.object(bc, "CATALOG_PATH", cache_file):
        bc.write_catalog(["Cozy Fall Fashion"], source="test")

        # 1. Test fuzzy matching in dropdown
        page = FakeCreatePage(["Cozy Fall Fashion"])
        builder = pp.PinterestBuilder(page)
        
        chosen = await builder.choose_board("Cozy Fall Fashion Ideas", auto_create=True)
        assert chosen == "Cozy Fall Fashion"

        # 2. Test auto-creation when totally absent
        page2 = FakeCreatePage(["Cozy Fall Fashion"])
        builder2 = pp.PinterestBuilder(page2)

        # Mock _create_board success
        with patch.object(builder2, "_create_board", return_value=True) as mock_create:
            chosen2 = await builder2.choose_board("Vintage Cyberpunk Style", auto_create=True)
            assert chosen2 == "Vintage Cyberpunk Style"
            assert mock_create.called
