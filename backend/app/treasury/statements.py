"""Reading a bank's statement (R7).

Three formats, one shape. A source turns bytes into `ParsedStatement`: the rows it could
read, the rows it could not, and the balances the bank stated. Parsing is separate from
importing so a malformed file is a value, not an exception halfway through a transaction —
and so the formats can be tested without a database.

Nothing here touches the ledger. An imported line is the bank's claim; it becomes an entry
only when someone reconciles it (R7.AC7).
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID

from app.shared.errors import DomainError

# What a CSV mapping may name. Either "amount", or "debit" and "credit" as two columns.
CSV_FIELDS = ("date", "amount", "debit", "credit", "description", "counterparty", "reference")


@dataclass(frozen=True, slots=True)
class ParsedLine:
    """One row the bank says happened. Positive is money in (R7.AC3)."""

    date: date
    amount: Decimal
    description: str | None = None
    counterparty: str | None = None
    bank_reference: str | None = None


@dataclass(slots=True)
class ParsedStatement:
    lines: list[ParsedLine] = field(default_factory=list)
    rejected: list[tuple[int, str]] = field(default_factory=list)
    """(row number, why) for every row that could not be read (R7.AC6)."""

    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    currency_code: str | None = None
    account_reference: str | None = None


class StatementSource(Protocol):
    """Turns a file into a statement. One implementation per format."""

    format: str

    def parse(self, payload: bytes) -> ParsedStatement: ...


def decode(payload: bytes) -> str:
    """Bank files arrive in whatever the bank felt like (R7.AC5)."""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DomainError("payments.unreadable_file", "the file is not text in any expected encoding")


def parse_amount(raw: str, *, decimal_separator: str = ".") -> Decimal:
    text = raw.strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        raise ValueError("no amount")

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]

    if decimal_separator == ",":
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")

    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{raw.strip()!r} is not an amount") from exc
    return -amount if negative else amount


def parse_date(raw: str, *, formats: tuple[str, ...]) -> date:
    text = raw.strip()
    for pattern in formats:
        try:
            return datetime.strptime(text, pattern).date()  # noqa: DTZ007 (a date, not a moment)
        except ValueError:
            continue
    raise ValueError(f"{text!r} is not a date")


DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d.%m.%Y")


@dataclass(frozen=True, slots=True)
class CsvSource:
    """A CSV, with the caller saying which column means what (R7.AC1).

    Banks name their columns whatever they like, so the mapping is the caller's problem and
    the parsing is ours.
    """

    mapping: dict[str, str]
    date_formats: tuple[str, ...] = DATE_FORMATS
    decimal_separator: str = "."
    delimiter: str | None = None
    format: str = "csv"

    def parse(self, payload: bytes) -> ParsedStatement:
        text = decode(payload)
        if not text.strip():
            raise DomainError("payments.unreadable_file", "the file is empty")

        delimiter = self.delimiter or self._sniff(text)
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if reader.fieldnames is None:
            raise DomainError("payments.unreadable_file", "the file has no header row")

        headers = {name.strip(): name for name in reader.fieldnames if name}
        for our_field, column in self.mapping.items():
            if our_field not in CSV_FIELDS:
                raise DomainError(
                    "payments.unreadable_file", f"{our_field!r} is not a statement field"
                )
            if column not in headers:
                raise DomainError(
                    "payments.unreadable_file", f"the file has no column named {column!r}"
                )
        if "date" not in self.mapping:
            raise DomainError("payments.unreadable_file", "the mapping needs a date column")
        if "amount" not in self.mapping and not {"debit", "credit"} <= set(self.mapping):
            raise DomainError(
                "payments.unreadable_file",
                "the mapping needs an amount column, or a debit and a credit column",
            )

        statement = ParsedStatement()
        for row_no, row in enumerate(reader, start=2):
            try:
                statement.lines.append(self._line(row, headers))
            except ValueError as exc:
                statement.rejected.append((row_no, str(exc)))
        return statement

    def _line(self, row: dict[str, str | None], headers: dict[str, str]) -> ParsedLine:
        def value(our_field: str) -> str:
            column = self.mapping.get(our_field)
            if column is None:
                return ""
            return (row.get(headers[column]) or "").strip()

        amount = (
            parse_amount(value("amount"), decimal_separator=self.decimal_separator)
            if "amount" in self.mapping
            else self._from_two_columns(value("debit"), value("credit"))
        )
        if amount == 0:
            raise ValueError("the row has no amount")

        return ParsedLine(
            date=parse_date(value("date"), formats=self.date_formats),
            amount=amount,
            description=value("description") or None,
            counterparty=value("counterparty") or None,
            bank_reference=value("reference") or None,
        )

    def _from_two_columns(self, debit: str, credit: str) -> Decimal:
        """A statement with money-in and money-out columns: one of them is filled."""
        into = parse_amount(credit, decimal_separator=self.decimal_separator) if credit else None
        out = parse_amount(debit, decimal_separator=self.decimal_separator) if debit else None
        if into and out:
            raise ValueError("the row is both a debit and a credit")
        if into:
            return into
        if out:
            return -abs(out)
        raise ValueError("the row has no amount")

    @staticmethod
    def _sniff(text: str) -> str:
        header = text.splitlines()[0]
        return max((";", ",", "\t"), key=header.count)


# :61:YYMMDD[MMDD]{C|D|RC|RD}[funds]amount[type]//reference
MT940_LINE = re.compile(
    r"^(?P<value_date>\d{6})(?P<entry_date>\d{4})?(?P<mark>R?[CD])(?P<funds>[A-Z])?"
    r"(?P<amount>[\d,\.]+)(?P<type>[A-Z][A-Z0-9]{3})?(?P<reference>.*)$"
)
MT940_BALANCE = re.compile(r"^(?P<mark>[CD])(?P<date>\d{6})(?P<currency>[A-Z]{3})(?P<amount>.+)$")


@dataclass(frozen=True, slots=True)
class Mt940Source:
    """SWIFT MT940, which needs no mapping because the tags say what things are (R7.AC2)."""

    format: str = "mt940"

    def parse(self, payload: bytes) -> ParsedStatement:
        text = decode(payload)
        tags = list(self._tags(text))
        if not any(tag == "61" for tag, _ in tags):
            raise DomainError("payments.unreadable_file", "the file has no MT940 statement lines")

        statement = ParsedStatement()
        pending: ParsedLine | None = None
        row_no = 0

        for tag, body in tags:
            if tag == "25":
                statement.account_reference = body.strip() or None
            elif tag in ("60F", "60M", "62F", "62M"):
                self._balance(statement, tag, body)
            elif tag == "61":
                row_no += 1
                if pending is not None:
                    statement.lines.append(pending)
                    pending = None
                try:
                    pending = self._line(body)
                except ValueError as exc:
                    statement.rejected.append((row_no, str(exc)))
            elif tag == "86" and pending is not None:
                pending = self._describe(pending, body)

        if pending is not None:
            statement.lines.append(pending)
        return statement

    @staticmethod
    def _tags(text: str):
        tag = None
        body: list[str] = []
        for raw in text.replace("\r\n", "\n").split("\n"):
            line = raw.rstrip()
            if line == "-":
                continue
            match = re.match(r"^:(?P<tag>\d{2}[A-Z]?):(?P<rest>.*)$", line)
            if match:
                if tag is not None:
                    yield tag, "\n".join(body)
                tag, body = match["tag"], [match["rest"]]
            elif tag is not None:
                body.append(line)
        if tag is not None:
            yield tag, "\n".join(body)

    @staticmethod
    def _balance(statement: ParsedStatement, tag: str, body: str) -> None:
        match = MT940_BALANCE.match(body.strip())
        if match is None:
            return
        try:
            amount = parse_amount(match["amount"], decimal_separator=",")
        except ValueError:
            return
        if match["mark"] == "D":
            amount = -amount
        statement.currency_code = match["currency"]
        if tag.startswith("60") and statement.opening_balance is None:
            statement.opening_balance = amount
        elif tag.startswith("62"):
            statement.closing_balance = amount

    @staticmethod
    def _line(body: str) -> ParsedLine:
        first = body.split("\n")[0].strip()
        match = MT940_LINE.match(first)
        if match is None:
            raise ValueError(f"{first!r} is not an MT940 line")

        amount = parse_amount(match["amount"], decimal_separator=",")
        # A reversal (RC/RD) points the other way to its mark.
        outgoing = match["mark"].endswith("D") != match["mark"].startswith("R")
        reference = match["reference"].strip()
        bank_reference = reference.split("//", 1)[-1].strip() if "//" in reference else None

        return ParsedLine(
            date=parse_date(match["value_date"], formats=("%y%m%d",)),
            amount=-amount if outgoing else amount,
            description=reference.split("//", 1)[0].strip() or None,
            bank_reference=bank_reference or None,
        )

    @staticmethod
    def _describe(line: ParsedLine, body: str) -> ParsedLine:
        """Tag 86 is free text, sometimes with ?-numbered subfields."""
        text = " ".join(part.strip() for part in body.split("\n") if part.strip())
        subfields = dict(re.findall(r"\?(\d{2})([^?]*)", text))
        counterparty = " ".join(
            subfields[code].strip() for code in ("32", "33") if subfields.get(code)
        )
        description = (
            " ".join(
                subfields[code].strip() for code in ("20", "21", "22", "23") if subfields.get(code)
            )
            if subfields
            else text
        )
        return ParsedLine(
            date=line.date,
            amount=line.amount,
            description=description.strip() or line.description,
            counterparty=counterparty.strip() or line.counterparty,
            bank_reference=line.bank_reference,
        )


OFX_TRANSACTION = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.DOTALL | re.IGNORECASE)
OFX_TAG = re.compile(r"<([A-Z0-9.]+)>([^<\r\n]*)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class OfxSource:
    """OFX/QFX, in its SGML and its XML spelling (R7.AC2)."""

    format: str = "ofx"

    def parse(self, payload: bytes) -> ParsedStatement:
        text = decode(payload)
        blocks = OFX_TRANSACTION.findall(text)
        if not blocks:
            raise DomainError("payments.unreadable_file", "the file has no OFX transactions")

        statement = ParsedStatement()
        header = self._fields(text.split("<STMTTRN>", 1)[0])
        statement.currency_code = header.get("CURDEF")
        statement.account_reference = header.get("ACCTID")

        for row_no, block in enumerate(blocks, start=1):
            fields = self._fields(block)
            try:
                statement.lines.append(self._line(fields))
            except ValueError as exc:
                statement.rejected.append((row_no, str(exc)))

        closing = self._fields(text.split("</BANKTRANLIST>")[-1])
        if "BALAMT" in closing:
            with contextlib.suppress(ValueError):
                statement.closing_balance = parse_amount(closing["BALAMT"])
        return statement

    @staticmethod
    def _fields(block: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for tag, value in OFX_TAG.findall(block):
            cleaned = value.strip()
            if cleaned and tag.upper() not in found:
                found[tag.upper()] = cleaned
        return found

    @staticmethod
    def _line(fields: dict[str, str]) -> ParsedLine:
        posted = fields.get("DTPOSTED") or fields.get("DTUSER")
        if not posted:
            raise ValueError("the transaction has no date")
        amount = parse_amount(fields.get("TRNAMT", ""))
        if amount == 0:
            raise ValueError("the transaction has no amount")

        return ParsedLine(
            # OFX dates may carry a time and a timezone: 20260301120000[3:AST]
            date=parse_date(posted[:8], formats=("%Y%m%d",)),
            amount=amount,
            description=fields.get("MEMO") or fields.get("NAME"),
            counterparty=fields.get("NAME"),
            bank_reference=fields.get("FITID"),
        )


def line_hash(bank_account_id: UUID, line: ParsedLine, running_balance: Decimal | None) -> str:
    """What makes an imported row the same row (R7.AC4).

    The running balance is in the fingerprint because it is what separates two genuinely
    identical transactions on the same day from the same row imported twice.
    """
    parts = [
        str(bank_account_id),
        line.date.isoformat(),
        f"{line.amount.normalize():f}",
        (line.bank_reference or "").strip().casefold(),
        (line.description or "").strip().casefold(),
        f"{running_balance.normalize():f}" if running_balance is not None else "",
    ]
    return hashlib.sha256("".join(parts).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What an import did, so the accountant can see it at a glance (R7.AC6)."""

    statement_id: UUID
    created: int
    duplicates: int
    rejected: list[tuple[int, str]]
