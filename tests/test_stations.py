import pytest
from obspy.core.inventory import Inventory
from seed_vault.service.seismoloader import get_stations
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.enums.config import Levels

@pytest.fixture
def test_settings():
    """Fixture to load real settings from a test config file."""
    settings = SeismoLoaderSettings.from_cfg_file("tests/config_test.cfg")  # Load config
    return settings


def get_num_contents(inventory):
    num_networks = 0
    num_stations = 0
    num_channels = num_locations = 0
    for network in inventory.networks:
        num_networks += 1
        for station in network.stations:
            num_stations += 1
            for channel in station:
                num_channels += 1
                num_locations += 1

    return num_networks, num_stations, num_locations, num_channels

def test_get_stations(test_settings):
    """Integration test using a real FDSN client"""
    
    # Act: Call get_stations() with real settings
    inventory = get_stations(test_settings)

    num_networks, num_stations, num_locations, num_channels = get_num_contents(inventory)

    # Assert: Ensure we get a valid Inventory object
    assert isinstance(inventory, Inventory), "Expected an Inventory object, but got None or incorrect type."
    assert num_networks > 0, "Expected networks in the inventory, but got an empty inventory."
    assert num_stations > 0, "Expected stations in the inventory, but got an empty stations."
    assert num_locations > 0, "Expected locations in the inventory, but got an empty locations."
    assert num_channels > 0, "Expected channels in the inventory, but got an empty channels."


def test_bad_req_stations(test_settings):

    test_settings.station.network = "xdfsfss"
    try:
        inventory = get_stations(test_settings)
    except Exception as e:
        assert f"400 BAD_REQUEST" in str(e)


def test_no_stations(test_settings):

    test_settings.station.client = 'AUSPASS'
    inventory = get_stations(test_settings)

    assert inventory is None

def test_param_level(test_settings):
    test_settings.station.level = Levels.STATION
    inventory = get_stations(test_settings)
    num_networks, num_stations, num_locations, num_channels = get_num_contents(inventory)

    assert num_networks > 0, "Expected networks in the inventory, but got an empty inventory."
    assert num_stations > 0, "Expected stations in the inventory, but got an empty stations."
    assert num_locations == 0, "Expected empty locations in the inventory, but got some."
    assert num_channels == 0, "Expected empty channels in the inventory, but got an some."


def test_param_highest_sample_rate(test_settings):
    """
    @FIXME: This function needs a review from Rob.
    """
    test_settings.station.highest_samplerate_only = True
    inventory = get_stations(test_settings)
    for network in inventory.networks:
        for station in network.stations:
            for channel in station:
                # @FIXME: how to check if the channel is highest rate??
                assert channel.code.startswith("H")
