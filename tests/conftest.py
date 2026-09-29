"""Shared pytest fixtures for the whole suite."""

import pytest

from converter import ffmpegtool


@pytest.fixture(autouse=True)
def _reset_ffmpegtool_termination_state():
    """Clear `ffmpegtool`'s one-way shutdown flag and process registry.

    The flag is one-way by design in production -- once `terminate_all` sets
    it, nothing clears it again. But pytest runs every test in one
    interpreter, so without this a `terminate_all` test would leave every
    later test unable to spawn anything. Runs before *and* after each test:
    before, in case a previous run crashed mid-test and never reached its own
    teardown; after, so the next test starts clean.
    """
    ffmpegtool._reset_termination_state_for_tests()
    yield
    ffmpegtool._reset_termination_state_for_tests()
