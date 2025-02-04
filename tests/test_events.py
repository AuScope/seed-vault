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


def test_get_events(test_settings):
    """Integration test using a real FDSN client"""
    
    # Act: Call get_stations() with real settings
    result = get_events(test_settings)

    geo = test_settings.event.geo_constraint[0]

    # Assert: Ensure we get a valid Inventory object
    assert isinstance(result, Catalog), "Expected an Catalog object, but got None or incorrect type."
    assert len(result) > 0, "Expected events in the catalog, but got an empty result."

    df_res = event_response_to_df(result)
    print(f'No events found: {len(df_res)}')
    print('Checking if the events follow the applied filters.')

    for i, row in df_res.iterrows():
        assert(((row["magnitude"] <= test_settings.event.max_magnitude) & (row["magnitude"] >= test_settings.event.min_magnitude)))
        assert(((row["depth (km)"] <= test_settings.event.max_depth) & (row["depth (km)"] >= test_settings.event.min_depth)))
        assert(((row["longitude"] <= geo.coords.max_lng) & (row["longitude"] >= geo.coords.min_lng)))
        assert(((row["latitude"] <= geo.coords.max_lat) & (row["latitude"] >= geo.coords.min_lat)))

    