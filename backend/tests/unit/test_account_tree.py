"""Nesting balances under their parents and subtotalling (R2.AC4, R3.AC7). Pure, no database.

The query hands `tree` every account in the chart, moved or not, so these lists include the
parents — a group account with no lines of its own still has to appear and carry a subtotal.
"""

from dataclasses import replace
from decimal import Decimal
from uuid import UUID

from app.reporting.balances import AccountBalance, flatten, tree
from app.shared.ids import uuid7


def d(value: str) -> Decimal:
    return Decimal(value)


def account(
    code: str, name: str, type_: str, parent: UUID | None = None, group: bool = False
) -> AccountBalance:
    """An account with nothing on it yet; `moved` gives it figures."""
    subtype = {"income": "income", "expense": "expense"}.get(type_, "current_asset")
    return AccountBalance(
        account_id=uuid7(),
        code=code,
        name=name,
        name_ar=None,
        type=type_,
        subtype=subtype,
        parent_id=parent,
        is_group=group,
        opening=d("0"),
        debit=d("0"),
        credit=d("0"),
    )


def moved(entry: AccountBalance, opening="0", debit="0", credit="0") -> AccountBalance:
    return replace(entry, opening=d(opening), debit=d(debit), credit=d(credit))


class TestNesting:
    def test_a_child_sits_under_its_parent(self) -> None:
        parent = account("4", "Income", "income", group=True)
        child = account("4100", "Sales", "income", parent=parent.account_id)

        roots = tree([parent, moved(child, credit="100")])

        assert [node.code for node in roots] == ["4"]
        assert [node.code for node in roots[0].children] == ["4100"]

    def test_a_parent_with_no_lines_still_appears(self) -> None:
        """A group account holds nothing itself; it exists to carry a subtotal."""
        parent = account("5", "Expenses", "expense", group=True)
        child = account("5100", "Rent", "expense", parent=parent.account_id)

        roots = tree([parent, moved(child, debit="250")])

        assert roots[0].is_group
        assert roots[0].debit == d("250")

    def test_three_levels_nest(self) -> None:
        top = account("1", "Assets", "asset", group=True)
        middle = account("11", "Current", "asset", parent=top.account_id, group=True)
        leaf = account("1110", "Bank", "asset", parent=middle.account_id)

        roots = tree([top, middle, moved(leaf, debit="90")])

        assert [node.level for node in flatten(roots)] == [0, 1, 2]
        assert roots[0].debit == d("90")

    def test_children_are_ordered_by_code(self) -> None:
        parent = account("4", "Income", "income", group=True)
        later = account("4200", "Other", "income", parent=parent.account_id)
        earlier = account("4100", "Sales", "income", parent=parent.account_id)

        roots = tree([parent, moved(later, credit="1"), moved(earlier, credit="2")])

        assert [node.code for node in roots[0].children] == ["4100", "4200"]

    def test_an_account_whose_parent_is_filtered_out_becomes_a_root(self) -> None:
        """A profit and loss asks only for income, so an asset parent is not there to nest under."""
        parent = account("1", "Assets", "asset", group=True)
        stray = account("4100", "Sales", "income", parent=parent.account_id)

        roots = tree([parent, moved(stray, credit="100")], types=("income",))

        assert [node.code for node in roots] == ["4100"]


class TestSubtotals:
    def test_a_parent_sums_its_children(self) -> None:
        parent = account("5", "Expenses", "expense", group=True)
        rent = account("5100", "Rent", "expense", parent=parent.account_id)
        power = account("5200", "Power", "expense", parent=parent.account_id)

        roots = tree([parent, moved(rent, debit="300"), moved(power, debit="120", credit="20")])

        assert roots[0].debit == d("420")
        assert roots[0].credit == d("20")
        assert roots[0].movement == d("400")

    def test_opening_balances_roll_up_too(self) -> None:
        parent = account("1", "Assets", "asset", group=True)
        child = account("1110", "Bank", "asset", parent=parent.account_id)

        roots = tree([parent, moved(child, opening="500", debit="100")])

        assert roots[0].opening == d("500")
        assert roots[0].closing == d("600")

    def test_a_subtotal_reaches_the_top_through_a_middle_level(self) -> None:
        top = account("1", "Assets", "asset", group=True)
        middle = account("11", "Current", "asset", parent=top.account_id, group=True)
        first = account("1110", "Bank", "asset", parent=middle.account_id)
        second = account("1120", "Cash", "asset", parent=middle.account_id)

        roots = tree([top, middle, moved(first, debit="60"), moved(second, debit="40")])

        assert roots[0].debit == d("100")


class TestFiltering:
    def test_only_the_wanted_types_appear(self) -> None:
        """R2.AC7 — a profit and loss has no place for a bank account."""
        income = account("4100", "Sales", "income")
        asset = account("1110", "Bank", "asset")

        roots = tree([moved(income, credit="100"), moved(asset, debit="100")], types=("income",))

        assert [node.code for node in roots] == ["4100"]

    def test_unused_accounts_can_be_hidden(self) -> None:
        """R1.AC6 — a 51-account chart with three accounts used is mostly noise."""
        used = account("4100", "Sales", "income")
        unused = account("4200", "Other", "income")

        roots = tree([moved(used, credit="100"), unused], hide_unused=True)

        assert [node.code for node in roots] == ["4100"]

    def test_by_default_every_account_is_listed(self) -> None:
        """A trial balance that omitted an account would hide the one worth asking about."""
        used = account("4100", "Sales", "income")
        unused = account("4200", "Other", "income")

        roots = tree([moved(used, credit="100"), unused])

        assert [node.code for node in roots] == ["4100", "4200"]

    def test_a_group_whose_children_are_all_unused_disappears_too(self) -> None:
        parent = account("4", "Income", "income", group=True)
        child = account("4100", "Sales", "income", parent=parent.account_id)

        assert tree([parent, child], hide_unused=True) == []

    def test_an_account_with_an_opening_balance_and_no_movement_is_kept(self) -> None:
        """It still has money in it; hiding it would lose the balance."""
        dormant = account("1110", "Bank", "asset")

        roots = tree([moved(dormant, opening="75")], hide_unused=True)

        assert [node.code for node in roots] == ["1110"]


def test_an_empty_chart_is_an_empty_tree() -> None:
    assert tree([]) == []
