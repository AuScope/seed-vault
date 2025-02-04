import pytest
from obspy.core.inventory import Inventory
from seed_vault.service.seismoloader import get_stations
from seed_vault.models.config import SeismoLoaderSettings

@pytest.fixture
def test_settings():
    """Fixture to load real settings from a test config file."""
    settings = SeismoLoaderSettings.from_cfg_file("tests/config_test.cfg")  # Load config
    return settings

def test_get_stations(test_settings):
    """Integration test using a real FDSN client"""
    
    # Act: Call get_stations() with real settings
    result = get_stations(test_settings)

    # Assert: Ensure we get a valid Inventory object
    assert isinstance(result, Inventory), "Expected an Inventory object, but got None or incorrect type."
    assert len(result) > 0, "Expected stations in the inventory, but got an empty result."