"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest

from helpers_observation import series


@pytest.fixture
def observations_factory():
    """Build a contiguous run of stored observations over a range."""

    def factory(since, until, *, step_minutes=5, value=1.0):
        return series(since, until, step_minutes=step_minutes, value=value)

    return factory
