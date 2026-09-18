"""Reading a bank's statement (R7.AC1, R7.AC2, R7.AC5). No database, real bank formats."""

from datetime import date
from decimal import Decimal

import pytest

from app.shared.errors import DomainError
from app.shared.ids import uuid7
from app.treasury.statements import (
    CsvSource,
    Mt940Source,
    OfxSource,
    ParsedLine,
    line_hash,
)


def d(value: str) -> Decimal:
    return Decimal(value)


MAPPING = {
    "date": "Date",
    "amount": "Amount",
    "description": "Narrative",
    "counterparty": "Payee",
    "reference": "Ref",
}

CSV_FILE = b"""Date,Amount,Narrative,Payee,Ref
2026-03-01,1150.00,Invoice INV/2026/00001,Al Noor Est,TRX-1
2026-03-02,-500.00,Rent,Jeddah Properties,TRX-2
"""


class TestCsv:
    def test_one_line_per_row(self) -> None:
        """R7.AC1"""
        statement = CsvSource(MAPPING).parse(CSV_FILE)

        assert len(statement.lines) == 2
        assert statement.rejected == []
        assert statement.lines[0] == ParsedLine(
            date=date(2026, 3, 1),
            amount=d("1150.00"),
            description="Invoice INV/2026/00001",
            counterparty="Al Noor Est",
            bank_reference="TRX-1",
        )

    def test_money_out_is_negative(self) -> None:
        assert CsvSource(MAPPING).parse(CSV_FILE).lines[1].amount == d("-500.00")

    def test_separate_debit_and_credit_columns(self) -> None:
        """Most Saudi bank exports look like this rather than one signed column."""
        payload = b"Date,Money In,Money Out,Narrative\n2026-03-01,1150.00,,Receipt\n"
        payload += b"2026-03-02,,500.00,Rent\n"
        mapping = {
            "date": "Date",
            "credit": "Money In",
            "debit": "Money Out",
            "description": "Narrative",
        }

        lines = CsvSource(mapping).parse(payload).lines

        assert [line.amount for line in lines] == [d("1150.00"), d("-500.00")]

    def test_a_semicolon_file_needs_no_telling(self) -> None:
        payload = b"Date;Amount;Narrative\n01/03/2026;1.150,00;Receipt\n"
        statement = CsvSource(
            {"date": "Date", "amount": "Amount", "description": "Narrative"},
            decimal_separator=",",
        ).parse(payload)

        assert statement.lines[0].amount == d("1150.00")
        assert statement.lines[0].date == date(2026, 3, 1)

    def test_bracketed_amounts_are_negative(self) -> None:
        payload = b"Date,Amount\n2026-03-01,(500.00)\n"
        statement = CsvSource({"date": "Date", "amount": "Amount"}).parse(payload)
        assert statement.lines[0].amount == d("-500.00")

    def test_a_bad_row_is_rejected_and_the_rest_are_kept(self) -> None:
        """R7.AC6 — one unreadable row must not cost the accountant the whole file."""
        payload = CSV_FILE + b"not a date,nonsense,,,\n"
        statement = CsvSource(MAPPING).parse(payload)

        assert len(statement.lines) == 2
        assert len(statement.rejected) == 1
        row_no, reason = statement.rejected[0]
        assert row_no == 4
        assert "amount" in reason

    def test_a_row_with_no_amount_is_rejected(self) -> None:
        payload = b"Date,Amount\n2026-03-01,0.00\n"
        statement = CsvSource({"date": "Date", "amount": "Amount"}).parse(payload)

        assert statement.lines == []
        assert statement.rejected == [(2, "the row has no amount")]

    def test_a_row_that_is_both_ways_at_once_is_rejected(self) -> None:
        payload = b"Date,In,Out\n2026-03-01,100.00,50.00\n"
        statement = CsvSource({"date": "Date", "credit": "In", "debit": "Out"}).parse(payload)

        assert statement.rejected == [(2, "the row is both a debit and a credit")]

    def test_a_missing_column_is_the_mappings_fault_not_a_rows(self) -> None:
        """R7.AC5 — nothing is imported, and the message names the column."""
        with pytest.raises(DomainError) as caught:
            CsvSource({"date": "Date", "amount": "Total"}).parse(CSV_FILE)

        assert caught.value.code == "payments.unreadable_file"
        assert "Total" in caught.value.message

    def test_a_mapping_without_a_date_is_refused(self) -> None:
        with pytest.raises(DomainError):
            CsvSource({"amount": "Amount"}).parse(CSV_FILE)

    def test_a_mapping_without_an_amount_is_refused(self) -> None:
        with pytest.raises(DomainError):
            CsvSource({"date": "Date"}).parse(CSV_FILE)

    def test_an_empty_file_is_refused(self) -> None:
        """R7.AC5"""
        with pytest.raises(DomainError) as caught:
            CsvSource(MAPPING).parse(b"   ")
        assert caught.value.code == "payments.unreadable_file"

    def test_arabic_narratives_survive(self) -> None:
        payload = "Date,Amount,Narrative\n2026-03-01,1150.00,تحويل\n".encode()
        statement = CsvSource(
            {"date": "Date", "amount": "Amount", "description": "Narrative"}
        ).parse(payload)
        assert statement.lines[0].description == "تحويل"


MT940_FILE = b""":20:STATEMENT-1
:25:SA0380000000608010167519
:28C:00001/001
:60F:C260301SAR12500,00
:61:2603010301C1150,00NTRFINV/2026/00001//TRX-1
:86:?20Invoice INV/2026/00001?32AL NOOR EST
:61:2603020302D500,00NTRFRENT//TRX-2
:86:?20Rent for March?32JEDDAH PROPERTIES
:62F:C260302SAR13150,00
-
"""


class TestMt940:
    def test_no_mapping_is_needed(self) -> None:
        """R7.AC2"""
        statement = Mt940Source().parse(MT940_FILE)

        assert len(statement.lines) == 2
        assert statement.rejected == []

    def test_a_credit_is_money_in_and_a_debit_is_money_out(self) -> None:
        lines = Mt940Source().parse(MT940_FILE).lines
        assert [line.amount for line in lines] == [d("1150.00"), d("-500.00")]

    def test_the_comma_is_the_decimal_point(self) -> None:
        assert Mt940Source().parse(MT940_FILE).lines[0].amount == d("1150.00")

    def test_dates_counterparties_and_references_come_through(self) -> None:
        """R7.AC3"""
        line = Mt940Source().parse(MT940_FILE).lines[0]

        assert line.date == date(2026, 3, 1)
        assert line.bank_reference == "TRX-1"
        assert line.counterparty == "AL NOOR EST"
        assert line.description == "Invoice INV/2026/00001"

    def test_the_stated_balances_are_read(self) -> None:
        statement = Mt940Source().parse(MT940_FILE)

        assert statement.opening_balance == d("12500.00")
        assert statement.closing_balance == d("13150.00")
        assert statement.currency_code == "SAR"
        assert statement.account_reference == "SA0380000000608010167519"

    def test_a_reversal_points_the_other_way(self) -> None:
        payload = b":25:SA03\n:61:2603010301RD500,00NTRFREVERSAL//TRX-9\n"
        assert Mt940Source().parse(payload).lines[0].amount == d("500.00")

    def test_free_text_without_subfields_is_the_description(self) -> None:
        payload = b":61:2603010301C100,00NTRFREF\n:86:Salary transfer\n"
        assert Mt940Source().parse(payload).lines[0].description == "Salary transfer"

    def test_an_unreadable_statement_line_is_rejected_alone(self) -> None:
        """R7.AC6"""
        payload = MT940_FILE.replace(b":61:2603020302D500,00NTRFRENT//TRX-2", b":61:rubbish")
        statement = Mt940Source().parse(payload)

        assert len(statement.lines) == 1
        assert len(statement.rejected) == 1

    def test_a_file_with_no_statement_lines_is_refused(self) -> None:
        """R7.AC5"""
        with pytest.raises(DomainError) as caught:
            Mt940Source().parse(b":20:STATEMENT-1\n:25:SA03\n")
        assert caught.value.code == "payments.unreadable_file"


OFX_FILE = b"""OFXHEADER:100
DATA:OFXSGML

<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>SAR
<BANKACCTFROM><ACCTID>608010167519</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260301120000[3:AST]
<TRNAMT>1150.00
<FITID>TRX-1
<NAME>AL NOOR EST
<MEMO>Invoice INV/2026/00001
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260302
<TRNAMT>-500.00
<FITID>TRX-2
<NAME>JEDDAH PROPERTIES
<MEMO>Rent
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>13150.00<DTASOF>20260302</LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


class TestOfx:
    def test_no_mapping_is_needed(self) -> None:
        """R7.AC2"""
        statement = OfxSource().parse(OFX_FILE)

        assert len(statement.lines) == 2
        assert statement.rejected == []

    def test_signs_come_from_the_file(self) -> None:
        lines = OfxSource().parse(OFX_FILE).lines
        assert [line.amount for line in lines] == [d("1150.00"), d("-500.00")]

    def test_a_timestamped_date_is_still_a_date(self) -> None:
        assert OfxSource().parse(OFX_FILE).lines[0].date == date(2026, 3, 1)

    def test_the_banks_own_identifier_is_kept(self) -> None:
        """R7.AC3 — FITID is what makes a re-import recognisable."""
        line = OfxSource().parse(OFX_FILE).lines[0]

        assert line.bank_reference == "TRX-1"
        assert line.counterparty == "AL NOOR EST"
        assert line.description == "Invoice INV/2026/00001"

    def test_the_account_and_currency_are_read(self) -> None:
        statement = OfxSource().parse(OFX_FILE)

        assert statement.currency_code == "SAR"
        assert statement.account_reference == "608010167519"
        assert statement.closing_balance == d("13150.00")

    def test_the_xml_spelling_works_too(self) -> None:
        payload = b"""<?xml version="1.0"?><OFX><STMTTRN><DTPOSTED>20260301</DTPOSTED>
<TRNAMT>250.00</TRNAMT><FITID>X1</FITID><MEMO>Transfer</MEMO></STMTTRN></OFX>"""
        statement = OfxSource().parse(payload)

        assert statement.lines[0].amount == d("250.00")
        assert statement.lines[0].bank_reference == "X1"

    def test_a_transaction_without_an_amount_is_rejected(self) -> None:
        """R7.AC6"""
        payload = b"<OFX><STMTTRN><DTPOSTED>20260301<FITID>X1</STMTTRN></OFX>"
        statement = OfxSource().parse(payload)

        assert statement.lines == []
        assert len(statement.rejected) == 1

    def test_a_file_with_no_transactions_is_refused(self) -> None:
        """R7.AC5"""
        with pytest.raises(DomainError) as caught:
            OfxSource().parse(b"OFXHEADER:100\n<OFX></OFX>")
        assert caught.value.code == "payments.unreadable_file"


def test_bytes_that_are_not_text_are_refused() -> None:
    """R7.AC5 — someone will upload a PDF."""
    with pytest.raises(DomainError) as caught:
        CsvSource(MAPPING).parse(b"\xff\xfe\x00\x00\xff")
    assert caught.value.code == "payments.unreadable_file"


class TestTheImportFingerprint:
    line = ParsedLine(
        date=date(2026, 3, 1),
        amount=Decimal("1150.00"),
        description="Invoice INV/2026/00001",
        counterparty="Al Noor Est",
        bank_reference="TRX-1",
    )

    def test_the_same_row_hashes_the_same_way_twice(self) -> None:
        """R7.AC4 rests on this being stable."""
        account = uuid7()
        assert line_hash(account, self.line, Decimal("13150.00")) == line_hash(
            account, self.line, Decimal("13150.00")
        )

    def test_trailing_zeros_do_not_change_the_fingerprint(self) -> None:
        """The same amount written 1150.00 or 1150.000000 is the same amount."""
        account = uuid7()
        other = ParsedLine(
            date=self.line.date,
            amount=Decimal("1150.000000"),
            description=self.line.description,
            counterparty=self.line.counterparty,
            bank_reference=self.line.bank_reference,
        )
        assert line_hash(account, other, Decimal("13150")) == line_hash(
            account, self.line, Decimal("13150.00")
        )

    def test_a_different_amount_is_a_different_row(self) -> None:
        account = uuid7()
        other = ParsedLine(date=self.line.date, amount=Decimal("1150.01"))
        assert line_hash(account, other, None) != line_hash(account, self.line, None)

    def test_the_running_balance_separates_two_identical_transactions(self) -> None:
        """Two identical payments on one day differ by where they leave the balance."""
        account = uuid7()
        assert line_hash(account, self.line, Decimal("13150.00")) != line_hash(
            account, self.line, Decimal("14300.00")
        )

    def test_the_same_row_on_another_account_is_another_row(self) -> None:
        assert line_hash(uuid7(), self.line, None) != line_hash(uuid7(), self.line, None)
