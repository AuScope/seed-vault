import os
import shutil
import pytest
import warnings
from obspy.core.event import read_events
from obspy.core.inventory import read_inventory
from seed_vault.service.seismoloader import  run_event, run_continuous
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.utils import get_time_interval


@pytest.fixture
def test_settings():
    """Fixture to load real settings from a test config file."""
    settings = SeismoLoaderSettings.from_cfg_file("tests/config_test.cfg")  # Load config

    catalogs = read_events("tests/event_selected_test.xml")
    invs     = read_inventory("tests/station_selected_test.xml")

    settings.event.selected_catalogs = catalogs
    settings.station.selected_invs   = invs

    return settings


@pytest.fixture
def test_cont_settings():
    """Fixture to load real settings from a test config file."""
    settings = SeismoLoaderSettings.from_cfg_file("tests/config_test.cfg")  # Load config
    settings.download_type = 'continuous'

    catalogs = read_events("tests/event_selected_test.xml")
    invs     = read_inventory("tests/station_selected_test.xml")

    settings.event.selected_catalogs = catalogs
    settings.station.selected_invs   = invs

    settings.station.date_config.end_time, settings.station.date_config.start_time = get_time_interval('hour')

    return settings



@pytest.fixture
def clean_up_data(test_settings):
    if os.path.exists(test_settings.sds_path):
        shutil.rmtree(test_settings.sds_path)
    if os.path.exists(test_settings.db_path):
        os.remove(test_settings.db_path)
    yield


@pytest.fixture
def check_real_data(pytestconfig):
    if not pytestconfig.getoption("--run-real-fdsn"):
        pytest.skip("Skipping real FDSN test")


@pytest.fixture
def not_implement_test():
    warnings.warn("⚠️ Test not implemented yet!", UserWarning)

# ========================================
# TEST WITH REAL FDSN API
# ========================================
@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_get_fresh_data(test_settings: SeismoLoaderSettings, clean_up_data, check_real_data):
    
    test_settings.download_type = 'event'
    event_stream = run_event(test_settings)

    assert event_stream, "Expected waveform data but got None or an empty list."
    for stream in event_stream:
        assert len(stream) > 0, "Expected non-empty waveform data."

    assert os.path.exists(test_settings.sds_path)
    assert os.path.exists(test_settings.db_path)

    # @FIXME: It would be nice to check if data in db is consistent with downloaded data


@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_redownload_data(test_settings: SeismoLoaderSettings, check_real_data, not_implement_test):
    """
    Not quite sure how to assert it does not redownload (requests are not send to server).

    Not yet implmented. 
    """


@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_force_redownload_data(test_settings: SeismoLoaderSettings, check_real_data, not_implement_test):
    """
    Not quite sure how to assert it does redownload (all requests are send to server).

    Not yet implmented. 
    """


# ========================
# REAL CONTINUOUS
# ========================
@pytest.mark.xfail(reason="Testing live servers is not reliable as they are sometimes unavailable")
def test_get_continuous_data(test_cont_settings: SeismoLoaderSettings, clean_up_data, check_real_data, not_implement_test):
    
    success = run_continuous(test_cont_settings) #note that this doesn't return any data, just True

    assert success
    #assert event_streams, "Expected waveform data but got None or an empty list."
    #for stream in event_streams:
    #    assert len(stream) > 0, "Expected non-empty waveform data."

    assert os.path.exists(test_cont_settings.sds_path)
    assert os.path.exists(test_cont_settings.db_path)







