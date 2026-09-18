"""The chart templates as data: internally consistent before they touch a database (R6, NFR3)."""

import pytest

from app.coa.defaults import DEFAULT_SUBTYPES
from app.coa.templates import SAUDI, TEMPLATES
from app.ledger.api import ACCOUNT_SUBTYPES, JOURNAL_TYPES


@pytest.mark.parametrize("template", TEMPLATES.values(), ids=lambda t: t.key)
class TestEveryTemplate:
    def test_account_codes_are_unique(self, template) -> None:
        codes = [entry.code for entry in template.accounts]
        assert len(codes) == len(set(codes))

    def test_every_parent_exists_and_is_a_group_of_the_same_type(self, template) -> None:
        by_code = {entry.code: entry for entry in template.accounts}
        for entry in template.accounts:
            if entry.parent is None:
                continue
            parent = by_code.get(entry.parent)
            assert parent is not None, f"{entry.code} has no parent {entry.parent}"
            assert parent.is_group, f"{parent.code} must be a group to parent {entry.code}"
            assert parent.type == entry.type, f"{entry.code} and {parent.code} differ in type"

    def test_parents_are_defined_before_their_children(self, template) -> None:
        """The loader creates them in order, so a parent must come first."""
        seen: set[str] = set()
        for entry in template.accounts:
            if entry.parent is not None:
                assert entry.parent in seen, f"{entry.code} comes before its parent"
            seen.add(entry.code)

    def test_every_subtype_belongs_to_its_type(self, template) -> None:
        for entry in template.accounts:
            assert entry.subtype in ACCOUNT_SUBTYPES[entry.type], entry.code

    def test_every_account_has_both_languages(self, template) -> None:
        """NFR3 — a Saudi tax invoice needs Arabic, so the chart carries it from the start."""
        for entry in template.accounts:
            assert entry.name.strip(), entry.code
            assert entry.name_ar.strip(), entry.code
            assert any("؀" <= character <= "ۿ" for character in entry.name_ar), entry.code

    def test_journals_are_valid_and_bank_journals_have_an_account(self, template) -> None:
        by_code = {entry.code: entry for entry in template.accounts}
        codes = {journal.code for journal in template.journals}
        assert len(codes) == len(template.journals)

        for journal in template.journals:
            assert journal.type in JOURNAL_TYPES
            if journal.type in ("bank", "cash"):
                assert journal.default_account, f"{journal.code} needs an account"
                assert by_code[journal.default_account].subtype == "bank_cash"

    def test_every_default_is_filled_and_suitable(self, template) -> None:
        """R6.AC2 — a template that leaves defaults unset has not finished the job."""
        by_code = {entry.code: entry for entry in template.accounts}
        assert set(template.defaults) == set(DEFAULT_SUBTYPES)

        for key, code in template.defaults.items():
            entry = by_code.get(code)
            assert entry is not None, f"{key} points at missing account {code}"
            assert not entry.is_group, f"{key} points at a group account"
            assert entry.subtype in DEFAULT_SUBTYPES[key], f"{key} points at {entry.subtype}"


class TestSaudiChart:
    @pytest.mark.parametrize(
        "code", ["1300", "2200", "2300", "2400", "2500", "2700", "4400", "5700", "5900"]
    )
    def test_the_accounts_saudi_compliance_needs_are_present(self, code: str) -> None:
        """R6.AC4 — VAT in and out, withholding, Zakat, end of service, GOSI."""
        assert code in {entry.code for entry in SAUDI.accounts}

    def test_the_five_journals_are_there(self) -> None:
        """R6.AC3"""
        assert {journal.type for journal in SAUDI.journals} == {
            "sales",
            "purchases",
            "bank",
            "cash",
            "general",
        }

    def test_it_is_described_for_a_chooser(self) -> None:
        assert SAUDI.key == "sa"
        assert "Saudi" in SAUDI.name
        assert len(SAUDI.description) > 40
