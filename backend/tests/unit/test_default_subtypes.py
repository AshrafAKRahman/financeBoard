"""The default-account rules line up with the ledger's own subtypes (R5.AC3)."""

from app.coa.accounts import DEFAULT_COLUMNS
from app.coa.defaults import COLUMN_OF, DEFAULT_SUBTYPES
from app.ledger.api import ACCOUNT_SUBTYPES

ALL_SUBTYPES = {subtype for subtypes in ACCOUNT_SUBTYPES.values() for subtype in subtypes}


def test_every_default_accepts_only_real_subtypes() -> None:
    for key, subtypes in DEFAULT_SUBTYPES.items():
        assert subtypes, key
        assert set(subtypes) <= ALL_SUBTYPES, key


def test_open_item_defaults_point_at_open_item_accounts() -> None:
    assert DEFAULT_SUBTYPES["receivable"] == ("receivable",)
    assert DEFAULT_SUBTYPES["payable"] == ("payable",)


def test_every_default_has_a_column_and_every_column_a_default() -> None:
    assert set(COLUMN_OF.values()) == set(DEFAULT_COLUMNS)
    assert set(COLUMN_OF) == set(DEFAULT_SUBTYPES)
