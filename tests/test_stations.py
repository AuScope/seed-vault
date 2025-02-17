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
@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_get_stations(test_settings, pytestconfig):
    """Integration test using a real FDSN client"""
    if not pytestconfig.getoption("--run-real-fdsn"):
        pytest.skip("Skipping real FDSN test: get_stations")
    
    inventory = get_stations(test_settings)

    num_networks, num_stations, num_locations, num_channels = get_num_contents(inventory)

    
    assert isinstance(inventory, Inventory), "Expected an Inventory object, but got None or incorrect type."
    assert num_networks > 0, "Expected networks in the inventory, but got an empty inventory."
    assert num_stations > 0, "Expected stations in the inventory, but got an empty stations."
    assert num_locations > 0, "Expected locations in the inventory, but got an empty locations."
    assert num_channels > 0, "Expected channels in the inventory, but got an empty channels."


@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_bad_req_stations(test_settings, pytestconfig):
    if not pytestconfig.getoption("--run-real-fdsn"):
        pytest.skip("Skipping real FDSN test: Bad Request - get_stations")

    test_settings.station.network = "xdfsfss"
    try:
        inventory = get_stations(test_settings)
    except Exception as e:
        assert f"http status code: 400" in str(e).lower()


@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_no_stations(test_settings, pytestconfig):
    if not pytestconfig.getoption("--run-real-fdsn"):
        pytest.skip("Skipping real FDSN test: Bad Request - get_stations")

    test_settings.station.client = 'AUSPASS'
    inventory = get_stations(test_settings)

    assert inventory is None


@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
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


@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_param_highest_sample_rate(test_settings, pytestconfig):
    """
    @FIXME: This function needs a review from Rob.
    """
    if not pytestconfig.getoption("--run-real-fdsn"):
        pytest.skip("Skipping real FDSN test: get_stations - highest_samplerate_only")

    inventory = get_stations(test_settings)

    n_net, n_sta, _, n_cha = get_num_contents(inventory)
    test_settings.station.highest_samplerate_only = True
    inventory = get_stations(test_settings)

    n_net_flt, n_sta_flt, _, n_cha_flt = get_num_contents(inventory)

    assert n_net == n_net_flt, f"Expected to get same number of networks but n_net={n_net}, n_net_flt={n_net_flt}"
    assert n_sta == n_sta_flt, f"Expected to get same number of stations but n_sta={n_sta}, n_sta_flt={n_sta_flt}"
    assert n_cha > n_cha_flt, f"Expected to get lower number of channels but n_cha={n_cha}, n_cha_flt={n_cha_flt}"
