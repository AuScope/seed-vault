import pytest
from unittest.mock import patch, MagicMock
from obspy.core.inventory import Inventory
from obspy import UTCDateTime
from obspy.clients.fdsn.header import FDSNNoDataException
from seed_vault.service.seismoloader import get_stations
from seed_vault.models.config import SeismoLoaderSettings


@pytest.fixture
def mock_settings():
    """Fixture for mock settings"""
    settings = SeismoLoaderSettings.from_cfg_file("tests/config_test.cfg")
    return settings


@pytest.fixture
def mock_client():
    """Fixture for mock Client instance"""
    with patch("seed_vault.service.seismoloader.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.services = {
            "station": {
                "network": True,
                "station": True,
                "location": True,
                "channel": True,
                "starttime": True,
                "endtime": True,
                "includerestricted": True,
                "level": True,
            }
        }
        mock_instance.get_stations.return_value = Inventory()  # Mock empty inventory
        yield mock_instance


def test_get_stations(mock_settings, mock_client):
    """Test get_stations with valid settings and mock client"""
    result = get_stations(mock_settings)

    assert isinstance(result, Inventory)
    # Capture the actual arguments passed to get_stations()
    _, actual_kwargs = mock_client.get_stations.call_args  # `call_args` returns (args, kwargs)

    # Expected kwargs (dynamically constructed from mock_settings)
    expected_kwargs = {
        "network": mock_settings.station.network,
        "station": mock_settings.station.station,
        "location": mock_settings.station.location,
        "channel": mock_settings.station.channel,
        "starttime": UTCDateTime(mock_settings.station.date_config.start_time),
        "endtime": UTCDateTime(mock_settings.station.date_config.end_time),
        "minlatitude":  mock_settings.station.geo_constraint[0].coords.min_lat,
        "maxlatitude":  mock_settings.station.geo_constraint[0].coords.max_lat,
        "minlongitude": mock_settings.station.geo_constraint[0].coords.min_lng,
        "maxlongitude": mock_settings.station.geo_constraint[0].coords.max_lng,
        "includerestricted": mock_settings.station.include_restricted,
        "level": mock_settings.station.level.value,
    }

    # Assert: Compare the expected and actual kwargs
    assert actual_kwargs == expected_kwargs, f"Expected {expected_kwargs}, but got {actual_kwargs}"


def test_get_stations_no_service(mock_settings):
    """Test get_stations when the station service is unavailable"""
    with patch("seed_vault.service.seismoloader.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.services = {}  # No station service

        result = get_stations(mock_settings)

        assert result is None


def test_get_stations_no_data(mock_settings):
    """Test get_stations when no stations are found (FDSNNoDataException)"""
    with patch("seed_vault.service.seismoloader.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.services = {
            "station": {
                "network": True,
                "station": True,
                "location": True,
                "channel": True,
                "starttime": True,
                "endtime": True,
            }
        }
        mock_instance.get_stations.side_effect = FDSNNoDataException("No data found")

        result = get_stations(mock_settings)

        assert result is None
