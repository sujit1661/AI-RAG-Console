"""Tests for shared utility functions."""
import pytest
from backend.deps import get_safe_name


def test_get_safe_name_basic():
    assert get_safe_name("My Project") == "my-project"


def test_get_safe_name_special_chars():
    assert get_safe_name("Hello World!") == "hello-world"


def test_get_safe_name_multiple_spaces():
    assert get_safe_name("  lots   of   spaces  ") == "lots-of-spaces"


def test_get_safe_name_already_slug():
    assert get_safe_name("my-project") == "my-project"


def test_get_safe_name_numbers():
    assert get_safe_name("Project 2024") == "project-2024"


def test_get_safe_name_username_prefix():
    slug = get_safe_name(f"sujit-myworkspace")
    assert slug == "sujit-myworkspace"
