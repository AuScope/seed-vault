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

# ====================================
# MOCK API CALLS
# ====================================
from unittest.mock import patch
from obspy.clients.fdsn.header import (
    FDSNNoDataException,
    FDSNBadRequestException,
    FDSNForbiddenException,
    FDSNRequestTooLargeException,
    FDSNException, 
    FDSNInternalServerException,
    FDSNServiceUnavailableException,
    FDSNUnauthorizedException
)


@pytest.mark.parametrize("exception, expected_message, status_code", [
    (FDSNBadRequestException, "HTTP Status code: 400 - Invalid request parameters", 400),  # 400 Bad Request
    (FDSNForbiddenException, "HTTP Status code: 403 - Access to requested data is denied", 403),  # 403 Forbidden
    (FDSNRequestTooLargeException, "HTTP Status code: 413 - Request size too large", 413),  # 413 Payload Too Large
    (FDSNInternalServerException, "HTTP Status code: 500 - FDSN server error", 500),  # 500 Internal Server Error
    (FDSNServiceUnavailableException, "HTTP Status code: 503 - FDSN service is temporarily unavailable", 503),  # 503 Service Unavailable
    (FDSNUnauthorizedException, "HTTP Status code: 401 - Unauthorized request", 401),
])
def test_mock_get_stations_fdsn_errors(test_settings, exception, expected_message, status_code):
    """Test get_stations with specific FDSN exceptions."""

    try:
        with patch("seed_vault.service.seismoloader.Client.get_stations", side_effect=exception(expected_message)):
            inventory = get_stations(test_settings)
    except Exception as e:
        assert f"HTTP Status code: {status_code}" in str(e), f"Expected to see 'HTTP Status code: {status_code}' in error message but got {str(e)}"



def test_mock_get_stations_204(test_settings):
    """
    Simulate an FDSN 204 error using a mock.
    """

    with patch("seed_vault.service.seismoloader.Client.get_stations") as mock_get_stations:
        mock_get_stations.side_effect = FDSNNoDataException("HTTP Status code: 204")

        inventory = get_stations(test_settings)
        assert inventory is None


def test_mock_get_stations_414(test_settings):
    """
    Simulate an FDSN 414 URI Too Long. 
    
    Note: Did not find an exception of long uri, hence, using a generic exception.
    """

    with patch("seed_vault.service.seismoloader.Client.get_stations") as mock_get_stations:
        mock_get_stations.side_effect = FDSNException("HTTP Status code: 414")

        with pytest.raises(FDSNException) as excinfo:
            get_stations(test_settings)

        assert "414" in str(excinfo.value), "Expected a 414 URI Too Long error, but got a different response."

# ====================================
# REAL FDSN API CALLS
# ====================================
def test_get_stations(test_settings, pytestconfig):
    """Integration test using a real FDSN client"""
    if not pytestconfig.getoption("--run-real-fdsn"):
        pytest.skip("Skipping real FDSN test: get_stations")
    # Act: Call get_stations() with real settings
    inventory = get_stations(test_settings)

    num_networks, num_stations, num_locations, num_channels = get_num_contents(inventory)

    # Assert: Ensure we get a valid Inventory object
    assert isinstance(inventory, Inventory), "Expected an Inventory object, but got None or incorrect type."
    assert num_networks > 0, "Expected networks in the inventory, but got an empty inventory."
    assert num_stations > 0, "Expected stations in the inventory, but got an empty stations."
    assert num_locations > 0, "Expected locations in the inventory, but got an empty locations."
    assert num_channels > 0, "Expected channels in the inventory, but got an empty channels."


def test_bad_req_stations(test_settings, pytestconfig):
    if not pytestconfig.getoption("--run-real-fdsn"):
        pytest.skip("Skipping real FDSN test: Bad Request - get_stations")

    test_settings.station.network = "xdfsfss"
    try:
        inventory = get_stations(test_settings)
    except Exception as e:
        assert f"http status code: 400" in str(e).lower()


def test_no_stations(test_settings, pytestconfig):
    if not pytestconfig.getoption("--run-real-fdsn"):
        pytest.skip("Skipping real FDSN test: Bad Request - get_stations")

    test_settings.station.client = 'AUSPASS'
    inventory = get_stations(test_settings)

    assert inventory is None


def test_param_level(test_settings, pytestconfig):
    if not pytestconfig.getoption("--run-real-fdsn"):
        pytest.skip("Skipping real FDSN test: get_stations - param: level")
    test_settings.station.level = Levels.STATION
    inventory = get_stations(test_settings)
    num_networks, num_stations, num_locations, num_channels = get_num_contents(inventory)

    assert num_networks > 0, "Expected networks in the inventory, but got an empty inventory."
    assert num_stations > 0, "Expected stations in the inventory, but got an empty stations."
    assert num_locations == 0, "Expected empty locations in the inventory, but got some."
    assert num_channels == 0, "Expected empty channels in the inventory, but got an some."


def test_param_highest_sample_rate(test_settings, pytestconfig):
    """
    @FIXME: This function needs a review from Rob.
    """
    if not pytestconfig.getoption("--run-real-fdsn"):
        pytest.skip("Skipping real FDSN test: get_stations - highest_samplerate_only")

    test_settings.station.highest_samplerate_only = True
    inventory = get_stations(test_settings)
    for network in inventory.networks:
        for station in network.stations:
            for channel in station:
                # @FIXME: how to check if the channel is highest rate??
                assert channel.code.startswith("H")


# def test_get_stations_414(test_settings, pytestconfig):
#     """Test triggering a 414 URI Too Long error with an excessively long query."""

#     if not pytestconfig.getoption("--run-real-fdsn"):
#         pytest.skip("Skipping real FDSN test: get_stations - Too long uri error")
    
#     # mocking extremely long query string
#     test_settings.station.network = ",".join(["XX"] * 5000)
#     test_settings.station.station = ",".join(["TEST"] * 5000) 

#     # Act & Assert
#     try:
#         get_stations(test_settings)
#     except Exception as e:
#         # @FIXME: A long uri is raising Connection Reset and not a 414 error.
#         assert "HTTP Status code: 414" in str(e), f"But got: {str(e)}"


# def test_get_stations_413(test_settings, pytestconfig):
#     """Test triggering a 413 Payload Too Large error with a massive request."""
    
#     if not pytestconfig.getoption("--run-heavy-fdsn"):
#         pytest.skip("Skipping real FDSN test: get_stations - Too many data uri error")
    
#     # Modify settings to request an excessive amount of data
#     test_settings.station.network = "*"  # All networks
#     test_settings.station.station = "*"  # All stations
#     test_settings.station.channel = "*"  # All channels
#     test_settings.station.date_config.start_time = "1900-01-01"  # Very old start time
#     test_settings.station.date_config.end_time = "2100-01-01"  # Very far end time
       
#     try:
#         get_stations(test_settings)
#     except Exception as e:
#         assert "HTTP Status code: 413" in str(e), "Expected a 413 Payload Too Large error, but got a different response."