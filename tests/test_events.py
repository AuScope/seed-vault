import pytest
from obspy.core.event import Catalog
from seed_vault.service.seismoloader import  get_events
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.events import event_response_to_df


@pytest.fixture
def test_settings():
    """Fixture to load real settings from a test config file."""
    settings = SeismoLoaderSettings.from_cfg_file("tests/config_test.cfg")  # Load config
    return settings

# ==================================
# TEST WITH MOCKING
# ==================================
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
def test_mock_get_events_fdsn_errors(test_settings, exception, expected_message, status_code):
    """Test get_events with specific FDSN exceptions."""

    try:
        with patch("seed_vault.service.seismoloader.Client.get_events", side_effect=exception(expected_message)):
            inventory = get_events(test_settings)
    except Exception as e:
        assert f"HTTP Status code: {status_code}" in str(e), f"Expected to see 'HTTP Status code: {status_code}' in error message but got {str(e)}"



def test_mock_get_events_204(test_settings):
    """
    Simulate an FDSN 204 error using a mock.
    """

    with patch("seed_vault.service.seismoloader.Client.get_events") as mock_get_stations:
        mock_get_stations.side_effect = FDSNNoDataException("HTTP Status code: 204")

        catalog = get_events(test_settings)
        assert len(catalog) == 0


def test_mock_get_events_414(test_settings):
    """
    Simulate an FDSN 414 URI Too Long. 
    
    Note: Did not find an exception of long uri, hence, using a generic exception.
    """

    with patch("seed_vault.service.seismoloader.Client.get_events") as mock_get_stations:
        mock_get_stations.side_effect = FDSNException("HTTP Status code: 414")

        with pytest.raises(FDSNException) as excinfo:
            get_events(test_settings)

        assert "414" in str(excinfo.value), "Expected a 414 URI Too Long error, but got a different response."


# ==================================
# TEST WITH REAL FDSN API
# ==================================
@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_get_events(test_settings):
    """Integration test using a real FDSN client"""
    
    # Act: Call get_events() with real settings
    catalogs = get_events(test_settings)

    geo = test_settings.event.geo_constraint[0]

    # Assert: Ensure we get a valid Inventory object
    assert isinstance(catalogs, Catalog), "Expected an Catalog object, but got None or incorrect type."
    assert len(catalogs) > 0, "Expected events in the catalog, but got an empty result."

    df_res = event_response_to_df(catalogs)
    print(f'No events found: {len(df_res)}')
    print('Checking if the events follow the applied filters.')

    for i, row in df_res.iterrows():
        assert(((row["magnitude"] <= test_settings.event.max_magnitude) & (row["magnitude"] >= test_settings.event.min_magnitude)))
        assert(((row["depth (km)"] <= test_settings.event.max_depth) & (row["depth (km)"] >= test_settings.event.min_depth)))
        assert(((row["longitude"] <= geo.coords.max_lon) & (row["longitude"] >= geo.coords.min_lon)))
        assert(((row["latitude"] <= geo.coords.max_lat) & (row["latitude"] >= geo.coords.min_lat)))


@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_bad_request_events(test_settings):
    test_settings.event.min_magnitude = 7.0
    test_settings.event.max_magnitude = 5.0

    try:
        catalogs = get_events(test_settings)
    except Exception as e:
        assert f"http status code: 400" in str(e).lower()


@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_no_events(test_settings):
    test_settings.event.date_config.start_time = test_settings.event.date_config.end_time

    catalogs = get_events(test_settings)

    assert len(catalogs) == 0