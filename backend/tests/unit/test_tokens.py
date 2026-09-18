"""Session and invitation secrets (R4.AC2, R11.AC4)."""

import re

from app.platform.identity import tokens


def test_tokens_are_url_safe_and_long_enough() -> None:
    token = tokens.new_token()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43,}", token), token


def test_tokens_are_unique() -> None:
    assert len({tokens.new_token() for _ in range(500)}) == 500


def test_hash_is_sha256_hex_and_hides_the_token() -> None:
    token = tokens.new_token()
    stored = tokens.token_hash(token)
    assert re.fullmatch(r"[0-9a-f]{64}", stored)
    assert token not in stored


def test_hashing_is_stable() -> None:
    token = tokens.new_token()
    assert tokens.token_hash(token) == tokens.token_hash(token)


def test_matching_compares_token_against_stored_hash() -> None:
    token = tokens.new_token()
    stored = tokens.token_hash(token)
    assert tokens.tokens_match(token, stored)
    assert not tokens.tokens_match(tokens.new_token(), stored)
    assert not tokens.tokens_match(token[:-1], stored)
    assert not tokens.tokens_match("", stored)
