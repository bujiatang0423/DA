"""Explicit guard for the local browser-test composition.

This module intentionally has no production import path.  The E2E entrypoint
must opt in before it can use frozen test data or reset its local database.
"""

from __future__ import annotations

from collections.abc import Mapping


class E2EConfigurationError(ValueError):
    """Raised when the local browser-test process is not explicitly isolated."""


def require_local_e2e_mode(environment: Mapping[str, str]) -> None:
    """Reject accidental use of the E2E process outside an explicit test mode."""
    if environment.get("DA_E2E_LOCAL") != "1":
        raise E2EConfigurationError("DA_E2E_LOCAL=1 is required for the local E2E harness")
    if environment.get("DA_ENVIRONMENT") != "test":
        raise E2EConfigurationError("the local E2E harness requires a test environment")
