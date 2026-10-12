"""Fixtures for end-to-end tests. They need the estate running: ``python -m estate up``.

The portal URL comes from ``base_url`` in pytest.ini (pytest-playwright), so ``page.goto("/")``
opens http://localhost:8085. Add ``--headed`` (and optionally ``--slowmo 300``) to watch the browser.
"""

from __future__ import annotations

import pytest

from estate.paths import EstateConfig, EstatePaths
from tests.support.estate_probe import EstateProbe, estate_is_running


@pytest.fixture(scope="session")
def estate_api_url() -> str:
    """Loopback URL for API calls from tests (avoids slow IPv6 fallbacks on some machines)."""
    return EstateConfig.load(EstatePaths.from_env()).api_url


@pytest.fixture(scope="session", autouse=True)
def require_running_estate(estate_api_url: str) -> None:
    """Fail fast, with the fix, when the estate is not running."""
    if not estate_is_running(estate_api_url):
        pytest.fail(
            f"The estate is not running at {estate_api_url}. Start it in another terminal with: "
            "python -m estate up",
            pytrace=False,
        )


@pytest.fixture
def probe() -> EstateProbe:
    """Read-only probe of the estate - the same library the estate MCP server uses."""
    return EstateProbe()


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:  # noqa: D103 - pytest-playwright hook fixture
    return {**browser_context_args, "locale": "en-GB", "viewport": {"width": 1280, "height": 900}}
