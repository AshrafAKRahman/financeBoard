import os
import time
from uuid import UUID


def uuid7() -> UUID:
    """RFC 9562 UUID version 7: 48-bit Unix milliseconds + random bits, sortable by time.

    Python 3.13's ``uuid`` module has no uuid7. PostgreSQL 18 does provide ``uuidv7()``,
    but IDs are generated client-side so callers know them before flushing (and so POS
    registers can mint them offline later).
    """
    millis = time.time_ns() // 1_000_000
    value = (millis & ((1 << 48) - 1)) << 80
    value |= int.from_bytes(os.urandom(10)) & ((1 << 80) - 1)
    value &= ~(0xF << 76)
    value |= 0x7 << 76  # version
    value &= ~(0x3 << 62)
    value |= 0x2 << 62  # variant
    return UUID(int=value)
