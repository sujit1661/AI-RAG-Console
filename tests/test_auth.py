"""Tests for auth logic."""
import pytest
from backend.auth import hash_password, verify_password


def test_bcrypt_hash_and_verify():
    password = "mysecretpassword"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)


def test_wrong_password_fails():
    hashed = hash_password("correct")
    assert not verify_password("wrong", hashed)


def test_legacy_sha256_verify():
    """Legacy SHA256 hashes should still verify correctly."""
    import hashlib
    password = "oldpassword"
    sha256_hash = hashlib.sha256(password.encode()).hexdigest()
    assert verify_password(password, sha256_hash)


def test_legacy_sha256_wrong_password():
    import hashlib
    sha256_hash = hashlib.sha256("correct".encode()).hexdigest()
    assert not verify_password("wrong", sha256_hash)


def test_bcrypt_hash_is_unique():
    """Same password should produce different hashes (bcrypt uses random salt)."""
    h1 = hash_password("password")
    h2 = hash_password("password")
    assert h1 != h2
    assert verify_password("password", h1)
    assert verify_password("password", h2)
