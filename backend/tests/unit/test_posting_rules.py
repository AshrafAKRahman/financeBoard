from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.ledger.posting import (
    ROUNDING_LINE_NAME,
    PostingLine,
    PostingRequest,
    convert_lines,
    validate_request,
)
from app.shared.errors import DomainError
from app.shared.ids import uuid7

A, B, C, ROUNDING = uuid7(), uuid7(), uuid7(), uuid7()


def request(*lines: PostingLine, **kwargs) -> PostingRequest:
    return PostingRequest(
        company_id=uuid7(),
        journal_id=uuid7(),
        date=date(2026, 3, 1),
        currency_code="SAR",
        lines=lines,
        **kwargs,
    )


def d(value: str) -> Decimal:
    return Decimal(value)


class TestValidateRequest:
    def test_balanced_request_passes(self) -> None:
        lines = (PostingLine(A, debit=d("100")), PostingLine(B, credit=d("100")))
        validate_request(request(*lines), 2)

    @pytest.mark.parametrize(
        ("lines", "code"),
        [
            ((PostingLine(A, debit=d("100")),), "ledger.too_few_lines"),
            (
                (PostingLine(A, debit=d("100")), PostingLine(B, credit=d("99.99"))),
                "ledger.unbalanced",
            ),
            (
                (PostingLine(A, debit=d("-5")), PostingLine(B, debit=d("5"))),
                "ledger.negative_amount",
            ),
            (
                (PostingLine(A, debit=d("5"), credit=d("5")), PostingLine(B, credit=d("0"))),
                "ledger.two_sided_line",
            ),
            ((PostingLine(A), PostingLine(B)), "ledger.zero_line"),
            (
                (PostingLine(A, debit=d("1.005")), PostingLine(B, credit=d("1.005"))),
                "ledger.unrounded",
            ),
        ],
    )
    def test_rejects(self, lines: tuple[PostingLine, ...], code: str) -> None:
        with pytest.raises(DomainError) as error:
            validate_request(request(*lines), 2)
        assert error.value.code == code

    def test_source_type_and_id_go_together(self) -> None:
        lines = (PostingLine(A, debit=d("1")), PostingLine(B, credit=d("1")))
        with pytest.raises(DomainError) as error:
            validate_request(request(*lines, source_type="invoice"), 2)
        assert error.value.code == "ledger.invalid_source"

    def test_three_decimal_currency(self) -> None:
        validate_request(
            request(PostingLine(A, debit=d("1.005")), PostingLine(B, credit=d("1.005"))), 3
        )


class TestConvertLines:
    def test_base_currency_is_unchanged(self) -> None:
        lines = [PostingLine(A, debit=d("115.00")), PostingLine(B, credit=d("115.00"))]
        values = convert_lines(lines, "SAR", Decimal(1), 2, ROUNDING)
        assert [(v.debit, v.credit, v.amount_currency) for v in values] == [
            (d("115.00"), 0, d("115.00")),
            (0, d("115.00"), d("-115.00")),
        ]

    def test_foreign_currency_converts_each_line(self) -> None:
        lines = [PostingLine(A, debit=d("100.00")), PostingLine(B, credit=d("100.00"))]
        values = convert_lines(lines, "USD", d("3.75"), 2, ROUNDING)
        assert [(v.debit, v.credit, v.currency_code) for v in values] == [
            (d("375.00"), 0, "USD"),
            (0, d("375.00"), "USD"),
        ]

    def test_rounding_difference_goes_to_rounding_account(self) -> None:
        # 3 x 0.01 USD at 3.755 -> each credit rounds 0.03755 up to 0.04, debit 0.11265 -> 0.11
        lines = [
            PostingLine(A, debit=d("0.03")),
            PostingLine(B, credit=d("0.01")),
            PostingLine(B, credit=d("0.01")),
            PostingLine(B, credit=d("0.01")),
        ]
        values = convert_lines(lines, "USD", d("3.755"), 2, ROUNDING)
        rounding = values[-1]
        assert rounding.account_id == ROUNDING
        assert rounding.name == ROUNDING_LINE_NAME
        assert rounding.amount_currency == 0
        assert (rounding.debit, rounding.credit) == (d("0.01"), 0)
        assert sum(v.debit for v in values) == sum(v.credit for v in values)

    def test_rounding_needs_an_account(self) -> None:
        lines = [
            PostingLine(A, debit=d("0.03")),
            PostingLine(B, credit=d("0.01")),
            PostingLine(B, credit=d("0.01")),
            PostingLine(B, credit=d("0.01")),
        ]
        with pytest.raises(DomainError) as error:
            convert_lines(lines, "USD", d("3.755"), 2, None)
        assert error.value.code == "ledger.rounding_account_missing"

    @given(
        amounts=st.lists(
            st.decimals(min_value=d("0.01"), max_value=d("9999999.99"), places=2),
            min_size=1,
            max_size=12,
        ),
        rate=st.decimals(min_value=d("0.000001"), max_value=d("5000"), places=6),
        base_places=st.sampled_from([0, 2, 3]),
    )
    def test_converted_entries_always_balance(
        self, amounts: list[Decimal], rate: Decimal, base_places: int
    ) -> None:
        total = sum(amounts, Decimal(0))
        lines = [PostingLine(A, debit=a) for a in amounts] + [PostingLine(C, credit=total)]
        values = convert_lines(lines, "USD", rate, base_places, ROUNDING)

        assert sum(v.debit for v in values) == sum(v.credit for v in values)
        assert sum(v.amount_currency for v in values) == 0
        for v in values:
            assert v.debit >= 0 and v.credit >= 0 and not (v.debit and v.credit)
            assert (v.debit - v.credit) * v.amount_currency >= 0


def test_uuid7_is_version_7_and_time_ordered() -> None:
    ids = [uuid7() for _ in range(50)]
    assert all(isinstance(i, UUID) and i.version == 7 for i in ids)
    assert [i.int >> 80 for i in ids] == sorted(i.int >> 80 for i in ids)
