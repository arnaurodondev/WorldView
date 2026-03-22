"""Shared pytest fixtures for ml-clients tests."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
def semaphore() -> asyncio.Semaphore:
    return asyncio.Semaphore(10)
