"""Argon2id wrapper: hashing, verification, parameter upgrades (R1.AC5, R2.AC1, R2.AC4, R2.AC5)."""

import pytest
from argon2 import PasswordHasher

from app.platform.identity import passwords
from app.shared.errors import DomainError

GOOD_PASSWORD = "correct horse battery staple"


def test_hash_is_argon2id_and_hides_the_password() -> None:
    stored = passwords.hash_password(GOOD_PASSWORD)
    assert stored.startswith("$argon2id$")
    assert GOOD_PASSWORD not in stored


def test_hashes_are_salted_so_two_users_with_one_password_differ() -> None:
    assert passwords.hash_password(GOOD_PASSWORD) != passwords.hash_password(GOOD_PASSWORD)


def test_verify_accepts_the_right_password() -> None:
    assert passwords.verify_password(passwords.hash_password(GOOD_PASSWORD), GOOD_PASSWORD)


@pytest.mark.parametrize(
    "wrong", ["correct horse battery stapl", "", "CORRECT HORSE BATTERY STAPLE"]
)
def test_verify_rejects_a_wrong_password(wrong: str) -> None:
    assert not passwords.verify_password(passwords.hash_password(GOOD_PASSWORD), wrong)


@pytest.mark.parametrize("broken", ["", "not-a-hash", "$argon2id$v=19$m=1", "plaintext"])
def test_unreadable_hash_verifies_as_false(broken: str) -> None:
    """R2.AC5 — a corrupt hash must refuse the login, never crash or accept."""
    assert not passwords.verify_password(broken, GOOD_PASSWORD)


@pytest.mark.parametrize("short", ["", "short", "elevenchars"])
def test_short_passwords_are_refused(short: str) -> None:
    with pytest.raises(DomainError) as error:
        passwords.hash_password(short)
    assert error.value.code == "identity.weak_password"
    assert "12" in error.value.message


def test_twelve_characters_is_enough() -> None:
    assert passwords.hash_password("twelvechars!")


def test_current_parameters_need_no_rehash() -> None:
    assert not passwords.needs_rehash(passwords.hash_password(GOOD_PASSWORD))


def test_weaker_parameters_need_a_rehash() -> None:
    """R2.AC4 — a hash made under older settings is upgraded at the next login."""
    weaker = PasswordHasher(memory_cost=8192, time_cost=1, parallelism=1)
    assert passwords.needs_rehash(weaker.hash(GOOD_PASSWORD))


def test_unreadable_hash_does_not_ask_for_a_rehash() -> None:
    assert not passwords.needs_rehash("not-a-hash")


def test_dummy_verification_is_silent() -> None:
    """R3.AC8 — used when the email address is unknown, so it must never raise."""
    passwords.verify_dummy()
