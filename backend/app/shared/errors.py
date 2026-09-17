import re

from sqlalchemy.exc import DBAPIError

# Triggers raise messages shaped like "ledger.unbalanced: entry ... debit 10 credit 9".
_DB_ERROR = re.compile(r"^(?P<code>[a-z_]+\.[a-z_]+): (?P<message>.*)$", re.DOTALL)


class DomainError(Exception):
    """A business rule violation with a stable, machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def domain_error_from_db(exc: DBAPIError) -> DomainError | None:
    diag = getattr(exc.orig, "diag", None)
    primary = getattr(diag, "message_primary", None) or str(exc.orig)
    match = _DB_ERROR.match(primary.strip())
    if match is None:
        return None
    return DomainError(match["code"], match["message"])
