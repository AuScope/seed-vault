import pytest

def pytest_addoption(parser):
    """Add custom CLI option for running real FDSN tests."""

    # Includes actual FDSN API calls during test
    parser.addoption(
        "--run-real-fdsn", action="store_true", default=False, help="Run real FDSN API tests"
    )

    # Includes heavy FDSN API calls during test, e.g. too many data
    parser.addoption(
        "--run-heavy-fdsn", action="store_true", default=False, help="Run real FDSN API tests"
    )

@pytest.fixture
def run_real_fdsn(pytestconfig):
    """Fixture to check if real FDSN tests should be run."""
    return pytestconfig.getoption("--run-real-fdsn")


@pytest.fixture
def run_heavy_fdsn(pytestconfig):
    """Fixture to check if heavy FDSN tests should be run."""
    return pytestconfig.getoption("--run-heavy-fdsn")
