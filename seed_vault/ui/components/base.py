import io
import os
import re
from typing import List
from copy import deepcopy
import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from datetime import datetime, time, date, timedelta
from obspy.core.event import Catalog, read_events
from obspy.core.inventory import Inventory, read_inventory
from time import sleep
import tempfile


from seed_vault.ui.components.map import LON_RANGE_END, LON_RANGE_START, create_map, add_area_overlays, add_data_points, clear_map_layers, clear_map_draw,add_map_draw
from seed_vault.ui.app_pages.helpers.common import get_selected_areas, save_filter

from seed_vault.service.events import get_event_data, event_response_to_df
from seed_vault.service.stations import get_station_data, station_response_to_df

from seed_vault.models.config import SeismoLoaderSettings, GeometryConstraint
from seed_vault.models.common import CircleArea, RectangleArea

from seed_vault.enums.config import GeoConstraintType, Levels
from seed_vault.enums.ui import Steps

from seed_vault.service.utils import convert_to_datetime, check_client_services, get_time_interval

class BaseComponentTexts:
    """Defines text constants for UI components in different configuration steps."""
    CLEAR_ALL_MAP_DATA = "Clear All"
    DOWNLOAD_CONFIG = "Download Config"
    SAVE_CONFIG = "Save Config"
    CONFIG_TEMPLATE_FILE="config_template.cfg"
    CONFIG_EVENT_FILE="config_event"
    CONFIG_STATION_FILE="config_station"

    def __init__(self, config_type: Steps):
        if config_type == Steps.EVENT:
            self.STEP   = "event"
            self.PREV_STEP = "station"

            self.GET_DATA_TITLE = "Select Data Tools"
            self.BTN_GET_DATA = "Get Events"
            self.SELECT_DATA_TITLE = "Select Events from Map or Table"
            self.SELECT_MARKER_TITLE = "#### Select Events from map"
            self.SELECT_MARKER_MSG   = "Select an event from map and Add to Selection."
            self.SELECT_DATA_TABLE_TITLE = "Select Events from Table  ⤵️  or from Map  ↗️"
            self.SELECT_DATA_TABLE_MSG = "Tick events from the table to view your selected events on the map."

            self.PREV_SELECT_NO  = "Total Number of Selected Events"
            self.SELECT_AREA_AROUND_MSG = "Define an area around the selected events."

        if config_type == Steps.STATION:
            self.STEP   = "station"
            self.PREV_STEP = "event"

            self.GET_DATA_TITLE = "Select Data Tools"
            self.BTN_GET_DATA = "Get Stations"
            self.SELECT_DATA_TITLE = "Select Stations from Map or Table"
            self.SELECT_MARKER_TITLE = "#### Select Stations from map"
            self.SELECT_MARKER_MSG   = "Select a station from map and Add to Selection."
            self.SELECT_DATA_TABLE_TITLE = "Select Stations from table  ⤵️  or from Map  ↗️"
            self.SELECT_DATA_TABLE_MSG = "Tick stations from the table to view your selected stations on the map."

            self.PREV_SELECT_NO  = "Total Number of Selected Stations"
            self.SELECT_AREA_AROUND_MSG = "Define an area around the selected stations."


class BaseComponent:
    """Base class for handling the search and selection of seismic events and stations.

    This class supports searching, selecting, and visualizing seismic data in a Streamlit application.

    Attributes:
        settings (SeismoLoaderSettings): The current application settings.
        old_settings (SeismoLoaderSettings): A deep copy of the initial settings before modifications.
        step_type (Steps): The current processing step (event or station).
        prev_step_type (Steps): The previous processing step, if applicable.
        TXT (BaseComponentTexts): Stores UI-related text constants based on the step type.
        stage (int): The current processing stage.
        all_current_drawings (List[GeometryConstraint]): A list of current geometry constraints.
        all_feature_drawings (List[GeometryConstraint]): A list of feature-based geometry constraints.
        df_markers (pd.DataFrame): Dataframe containing marker information for events or stations.
        df_data_edit (pd.DataFrame): Dataframe for editable data related to events or stations.
        catalogs (Catalog): Holds seismic event catalog data.
        inventories (Inventory): Holds station inventory data.
        map_disp: The main map display object.
        map_fg_area: Map layer displaying geographic areas.
        map_fg_marker: Map layer displaying markers for events or stations.
        map_fg_prev_selected_marker: Map layer for previously selected markers.
        map_height (int): Height of the map display.
        map_output: Output container for map elements.
        selected_marker_map_idx: Index of the currently selected marker on the map.
        map_view_center (dict): Dictionary storing the center coordinates of the map.
        map_view_zoom (int): Zoom level of the map.
        marker_info: Information about the currently selected marker.
        clicked_marker_info: Information about the last clicked marker.
        warning: Warning message to be displayed in the UI.
        error (str): Error message to be displayed in the UI.
        df_rect: Dataframe for rectangular selection areas.
        df_circ: Dataframe for circular selection areas.
        col_color: Column used for color coding markers.
        col_size: Column used for size scaling of markers.
        fig_color_bar: Color bar figure for the map visualization.
        df_markers_prev (pd.DataFrame): Dataframe storing previously selected markers.
        delay_selection (int): Delay time before processing a new selection.
        cols_to_exclude (List[str]): List of columns to exclude from the display.
        has_error (bool): Indicates whether an error has occurred.
    """

    settings: SeismoLoaderSettings
    old_settings: SeismoLoaderSettings
    step_type: Steps
    prev_step_type: Steps

    TXT: BaseComponentTexts
    stage: int

    all_current_drawings: List[GeometryConstraint] = []
    all_feature_drawings: List[GeometryConstraint] = []
    df_markers          : pd  .DataFrame           = pd.DataFrame()
    df_data_edit        : pd  .DataFrame           = pd.DataFrame()
    catalogs            : Catalog = Catalog(events=None)
    inventories         : Inventory = Inventory()
    
    map_disp                    = None
    map_fg_area                 = None
    map_fg_marker               = None
    map_fg_prev_selected_marker = None
    map_height                  = 500
    map_output                  = None
    selected_marker_map_idx     = None
    map_view_center             = {}
    map_view_zoom               = 2
    marker_info                 = None
    clicked_marker_info         = None
    warning                     = None
    error                       = None
    df_rect                     = None
    df_circ                     = None
    col_color                   = None  
    col_size                    = None
    fig_color_bar               = None
    df_markers_prev             = pd.DataFrame()
    
    delay_selection            = 0

    cols_to_exclude             = ['detail', 'is_selected']

    has_error: bool = False
    has_fetch_new_data: bool = False
    auto_refresh_enabled: bool = True
    error: str = ""

    @property
    def page_type(self) -> str:
        """Determines the page type based on the previous or current step.

        Returns:
            str: The page type, which is the previous step type if available, otherwise the current step type.
        """
        if self.prev_step_type is not None and self.prev_step_type != Steps.NONE:
            return self.prev_step_type
        else:
            return self.step_type

    def __init__(
            self, 
            settings: SeismoLoaderSettings, 
            step_type: Steps, 
            prev_step_type: Steps, 
            stage: int, 
            init_map_center = {}, 
            init_map_zoom = 2
        ):
        """Initializes the BaseComponent with the given settings and parameters.

        Args:
            settings (SeismoLoaderSettings): Configuration settings for loading seismic data.
            step_type (Steps): The current processing step (event or station).
            prev_step_type (Steps): The previous processing step, if applicable.
            stage (int): The current processing stage.
            init_map_center (dict, optional): Initial map center coordinates. Defaults to an empty dictionary.
            init_map_zoom (int, optional): Initial map zoom level. Defaults to 2.
        """
        self.settings       = settings
        self.old_settings   = deepcopy(settings)
        self.step_type      = step_type
        self.prev_step_type = prev_step_type
        self.stage          = stage
        self.map_id         = f"map_{step_type.value}_{prev_step_type.value}_{stage}" if prev_step_type else f"map_{step_type.value}_no_prev_{stage}" 
        self.TXT            = BaseComponentTexts(step_type)

        self.all_feature_drawings = self.get_geo_constraint()
        self.map_fg_area= add_area_overlays(areas=self.get_geo_constraint()) 
        if self.catalogs:
            self.df_markers = event_response_to_df(self.catalogs)

        if self.step_type == Steps.EVENT:
            self.col_color = "depth (km)"
            self.col_size  = "magnitude"
            self.config = self.settings.event
        if self.step_type == Steps.STATION:
            self.col_color = "network"
            self.col_size  = None
            self.config =  self.settings.station

        self.has_error = False
        self.error = ""
        self.set_map_view(init_map_center, init_map_zoom)
        self.map_view_center = init_map_center
        self.map_view_zoom   = init_map_zoom
        self.export_as_alternate = False
        self.is_refreshing = False
        self.station_dates_applied = False
        self.event_dates_applied = False

    def get_key_element(self, name):
        """Generates a unique key identifier for a UI element based on the step type and stage.

        Args:
            name (str): The base name of the element.

        Returns:
            str: A formatted string representing the unique key for the element.
        """
        return f"{name}-{self.step_type.value}-{self.stage}"


    def get_geo_constraint(self):
        """Retrieves the geographic constraints for the current step.

        Geographic constraints define the search area on the map using bounding boxes or circles.

        Returns:
            List[GeometryConstraint]: A list of geographic constraints (boxes or circles) 
            that confine the search area. Returns an empty list if no constraints are set.
        """
        if self.step_type == Steps.EVENT:
            return self.settings.event.geo_constraint
        if self.step_type == Steps.STATION and self.settings.station is not None:
            return self.settings.station.geo_constraint
        return []

    def set_geo_constraint(self, geo_constraint: List[GeometryConstraint]):
        """Sets the geographic constraints for the current step.

        This method updates the geographic constraints, which define the search area on the map using 
        bounding boxes or circles.

        Args:
            geo_constraint (List[GeometryConstraint]): A list of geographic constraints 
            (boxes or circles) to be applied to the current step.
        """
        geo_constraint = self.get_unique_geo_constraints(geo_constraint) 

        if self.step_type == Steps.EVENT and self.settings.event is not None:
            self.settings.event.geo_constraint = geo_constraint
        if self.step_type == Steps.STATION and self.settings.station is not None:
            self.settings.station.geo_constraint = geo_constraint

    # ====================
    # FILTERS
    # ====================
    def refresh_filters(self):
        """Refreshes and updates the filter settings based on configuration changes."""
        #print(f"DEBUG refresh_filters called: step={self.step_type}, stage={self.stage}")
        changes = self.settings.has_changed(self.old_settings)
        #print(f"DEBUG changes detected: {changes}")
        if changes.get('has_changed', False):
            #print("DEBUG: Calling st.rerun() from refresh_filters")
            self.old_settings = deepcopy(self.settings)
            save_filter(self.settings)
            st.rerun()

    def event_filter(self):
        """Displays and manages event filtering options in the Streamlit sidebar.

        This method allows users to filter seismic events based on:
        - Client selection
        - Time range (last month, last week, last day, or custom start/end dates)
        - Magnitude range
        - Depth range

        Functionality:
        - Users select a client from a dropdown list.
        - A warning is displayed if the selected client does not support event services.
        - Users can set predefined time intervals (last month, last week, last day).
        - Users can manually set start and end dates/times.
        - Validation ensures that the end date is after the start date.
        - Users can adjust event magnitude and depth ranges using sliders.
        - Map interaction buttons are rendered.
        - Refreshes filters upon changes.
        """

        min_date = date(1800,1,1)
        max_date = date(2100,1,1)

        # Trim start and end times to whatever we just returned
        if (self.prev_step_type == Steps.STATION and 
            not self.station_dates_applied and 
            not st.session_state.get('skip_station_date_calc', False)):
            
            start_dates = [
                station.start_date 
                for network in self.settings.station.selected_invs 
                for station in network 
                if station.start_date is not None
            ]
            end_dates = [
                station.end_date if station.end_date is not None else datetime.now()
                for network in self.settings.station.selected_invs 
                for station in network
            ]
            calculated_start_datetime = datetime.combine(*convert_to_datetime(min(start_dates)))
            calculated_end_datetime = datetime.combine(*convert_to_datetime(max(end_dates))) + timedelta(days=1)
            
            self.settings.event.date_config.start_time = calculated_start_datetime
            self.settings.event.date_config.end_time = calculated_end_datetime
            self.station_dates_applied = True  # Mark as applied

        else:
            if st.session_state.get('skip_station_date_calc', False):
                st.session_state['skip_station_date_calc'] = False

        start_date, start_time = convert_to_datetime(self.settings.event.date_config.start_time)
        end_date, end_time     = convert_to_datetime(self.settings.event.date_config.end_time)


        with st.sidebar:
            with st.expander("Filters", expanded=True):
                client_options = list(self.settings.client_url_mapping.get_clients())
                self.settings.event.client = st.selectbox(
                    'Choose a client:',
                    client_options,
                    index=client_options.index(self.settings.event.client),
                    key=f"{self.TXT.STEP}-pg-client-event"
                )

                # Check services for selected client
                services = check_client_services(self.settings.event.client)
                is_service_available = bool(services.get('event'))

                # Display warning if service is not available
                if not is_service_available:
                    st.warning(f"⚠️ Warning: Selected client '{self.settings.event.client}' does not support EVENT service. Please choose another client.")
            
                c11, c12, c13 = st.columns([1,1,1])
                with c11:
                    if st.button('Last Month', key="event-set-last-month"):
                        st.session_state['skip_station_date_calc'] = True
                        self.settings.event.date_config.end_time, self.settings.event.date_config.start_time = get_time_interval('month')
                        st.rerun()
                with c12:
                    if st.button('Last Week', key="event-set-last-week"):
                        st.session_state['skip_station_date_calc'] = True
                        self.settings.event.date_config.end_time, self.settings.event.date_config.start_time = get_time_interval('week')
                        st.rerun()
                with c13:
                    if st.button('Last Day', key="event-set-last-day"):
                        st.session_state['skip_station_date_calc'] = True
                        self.settings.event.date_config.end_time, self.settings.event.date_config.start_time = get_time_interval('day')
                        st.rerun()

                c1, c2 = st.columns([1,1])

                with c1:
                    start_date  = st.date_input("Start Date", min_value=min_date, max_value=max_date, value=start_date, key="event-pg-start-date-event")
                    start_time  = st.time_input("Start Time (UTC)", start_time)
                with c2:
                    end_date  = st.date_input("End Date", min_value=min_date, max_value=max_date, value=end_date, key="event-pg-end-date-event")
                    end_time  = st.time_input("End Time (UTC)", end_time)

                if self.settings.event.date_config.start_time > self.settings.event.date_config.end_time:
                    st.error("Error: End Date must fall after Start Date.")

                self.settings.event.min_magnitude, self.settings.event.max_magnitude = st.slider(
                    "Min Magnitude", 
                    min_value=-2.0, max_value=10.0, 
                    value=(self.settings.event.min_magnitude, self.settings.event.max_magnitude), 
                    step=0.1, key="event-pg-mag"
                )

                self.settings.event.min_depth, self.settings.event.max_depth = st.slider(
                    "Min Depth (km)", 
                    min_value=-5.0, max_value=1000.0, 
                    value=(self.settings.event.min_depth, self.settings.event.max_depth), 
                    step=1.0, key="event-pg-depth"
                )

                self.render_map_buttons()

        self.refresh_filters()


    def station_filter(self):
        """Displays and manages station filtering options in the Streamlit sidebar.

        This method allows users to filter seismic stations based on:
        - Client selection
        - Time range (last month, last week, last day, or custom start/end dates)
        - Network, station, location, and channel filters
        - Highest sample rate option
        - Restricted data inclusion

        Functionality:
        - Users select a client from a dropdown list.
        - A warning is displayed if the selected client does not support station services.
        - Users can set predefined time intervals (last month, last week, last day).
        - Users can manually set start and end dates/times with a one-hour shift if needed.
        - Validation ensures that the end date is after the start date.
        - Users can input station metadata filters (network, station, location, channel).
        - Users can enable highest sample rate filtering and restricted data inclusion.
        - Map interaction buttons are rendered.
        - Refreshes filters upon changes.
        """

        min_date = date(1800,1,1)
        max_date = date(2100,1,1)

        # Trim start and end times to whatever we just returned
        if (self.prev_step_type == Steps.EVENT and 
            not getattr(self, 'event_dates_applied', False) and 
            not st.session_state.get('skip_event_date_calc', False)):
            
            origin_times = []

            for event in self.settings.event.selected_catalogs:
                if event.preferred_origin():
                    origin_times.append(event.preferred_origin().time)
                elif event.origins:
                    origin_times.append(event.origins[0].time)

                start_date, start_time = convert_to_datetime(min(origin_times))
                end_date, end_time     = convert_to_datetime(max(origin_times))
                end_date = end_date + timedelta(days=1) # add an extra day for that last event

            self.event_dates_applied = True

        else:
            if st.session_state.get('skip_event_date_calc', False):
                st.session_state['skip_event_date_calc'] = False

        start_date, start_time = convert_to_datetime(self.settings.station.date_config.start_time)
        end_date, end_time = convert_to_datetime(self.settings.station.date_config.end_time)

        # One hour shift
        if (start_date == end_date and start_time >= end_time):
            start_time = time(hour=0, minute=0, second=0)
            end_time   = time(hour=1, minute=0, second=0)

        with st.sidebar:
            with st.expander("Filters", expanded=True):
                client_options = list(self.settings.client_url_mapping.get_clients())
                self.settings.station.client = st.selectbox(
                    'Choose a client:', 
                    client_options,
                    index=client_options.index(self.settings.station.client),
                    key=f"{self.TXT.STEP}-pg-client-station"
                )
                
                # Check services for selected client
                services = check_client_services(self.settings.station.client)
                is_service_available = bool(services.get('station'))

                # Display warning if service is not available
                if not is_service_available:
                    st.warning(f"⚠️ Warning: Selected client '{self.settings.station.client}' does not support STATION service. Please choose another client.")


                c11, c12, c13 = st.columns([1,1,1])
                with c11:
                    if st.button('Last Year', key="station-set-last-year"):
                        st.session_state['skip_event_date_calc'] = True
                        self.settings.station.date_config.end_time, self.settings.station.date_config.start_time = get_time_interval('year')
                        st.rerun()
                with c12:
                    if st.button('Last Month', key="station-set-last-month"):
                        st.session_state['skip_event_date_calc'] = True
                        self.settings.station.date_config.end_time, self.settings.station.date_config.start_time = get_time_interval('month')
                        st.rerun()
                with c13:
                    if st.button('Last Week', key="station-set-last-week"):
                        st.session_state['skip_event_date_calc'] = True
                        self.settings.station.date_config.end_time, self.settings.station.date_config.start_time = get_time_interval('week')
                        st.rerun()

                c11, c12 = st.columns([1,1])
                with c11:
                    start_date = st.date_input("Start Date", min_value=min_date, max_value=max_date, value=start_date)
                    # start_time = st.time_input("Start Time (UTC)", value=start_time)
                    self.settings.station.date_config.start_time = datetime.combine(start_date, start_time)
                with c12:
                    end_date = st.date_input("End Date", min_value=min_date, max_value=max_date, value=end_date)
                    # end_time = st.time_input("End Time (UTC)", value=end_time)
                    self.settings.station.date_config.end_time = datetime.combine(end_date, end_time)

                if self.settings.station.date_config.start_time > self.settings.station.date_config.end_time:
                    st.error("Error: End Date must fall after Start Date.")

                c21, c22 = st.columns([1,1])
                c31, c32 = st.columns([1,1])

                with c21:
                    self.settings.station.network = st.text_input("Network",   self.settings.station.network, key="event-pg-net-txt-station")
                with c22:
                    self.settings.station.station = st.text_input("Station",   self.settings.station.station, key="event-pg-sta-txt-station")
                with c31:
                    self.settings.station.location = st.text_input("Location", self.settings.station.location, key="event-pg-loc-txt-station")
                with c32:
                    self.settings.station.channel = st.text_input("Channel",   self.settings.station.channel, key="event-pg-cha-txt-station")

                self.settings.station.highest_samplerate_only = st.checkbox(
                    "Highest Sample Rate Only", 
                    value=self.settings.station.highest_samplerate_only,  # Default to unchecked
                    help="If a station has multiple channels for the same component (e.g. HHZ & LHZ), only select the one with the highest samplerate (HHZ).",
                    key="station-pg-highest-sample-rate"
                )
                
                self.settings.station.include_restricted = st.checkbox(
                    "Include Restricted Data", 
                    value=self.settings.station.include_restricted,  # Default to unchecked
                    help="Includes restricted data in station search.",
                    key="event-pg-include-restricted-station"
                )

                # TODO WORK IN PROGRESS
                inventory_level_tick = st.checkbox(
                    "Include Instrument Response", 
                    value=False,
                    help="Download station metadata with full instrument response. Potentially makes metadata download MUCH larger. Use only if you need to export the fdsnXML or need to plot events with response removed.",
                    key="event-pg-station-level"
                )
                self.settings.station.level = Levels.RESPONSE if inventory_level_tick else Levels.CHANNEL

                self.render_map_buttons()

        self.refresh_filters()

    # ====================
    # MAP
    # ====================
    def set_map_view(self, map_center, map_zoom):
        """Sets the map view properties, including center coordinates and zoom level.

        Args:
            map_center (dict): A dictionary representing the center coordinates of the map.
            map_zoom (int): The zoom level for the map.
        """
        self.map_view_center = map_center
        self.map_view_zoom   = map_zoom


    def update_filter_geometry(self, df, geo_type: GeoConstraintType, geo_constraint: List[GeometryConstraint]):
        """This method adds a new drawing (box or circle) to the existing drawings on the map.

        Args:
            df (pd.DataFrame): A DataFrame containing the new geometric constraints.
            geo_type (GeoConstraintType): The type of geographic constraint (bounding box or circle).
            geo_constraint (List[GeometryConstraint]): The existing list of geographic constraints.
        """
        add_geo = []
        for _, row in df.iterrows():
            coords = row.to_dict()
            if geo_type == GeoConstraintType.BOUNDING:
                add_geo.append(GeometryConstraint(coords=RectangleArea(**coords)))
            if geo_type == GeoConstraintType.CIRCLE:
                add_geo.append(GeometryConstraint(coords=CircleArea(**coords)))

        new_geo = [
            area for area in geo_constraint
            if area.geo_type != geo_type
        ]
        new_geo.extend(add_geo)

        self.set_geo_constraint(new_geo)

    def is_valid_rectangle(self, min_lat, max_lat, min_lon, max_lon):
        """Checks if the given latitude and longitude values define a valid rectangle.

        A valid rectangle satisfies the following conditions:
        - Latitude values (`min_lat`, `max_lat`) must be within the range [-90, 90].
        - Longitude values (`min_lon`, `max_lon`) must be within the range [-180, 180].
        - `min_lat` must be less than or equal to `max_lat`.
        - `min_lon` must be less than or equal to `max_lon`.

        Args:
            min_lat (float): Minimum latitude value.
            max_lat (float): Maximum latitude value.
            min_lon (float): Minimum longitude value.
            max_lon (float): Maximum longitude value.

        Returns:
            bool: `True` if the rectangle is valid, `False` otherwise.
        """
        return (-90 <= min_lat <= 90 and -90 <= max_lat <= 90 and
                LON_RANGE_START <= min_lon <= LON_RANGE_END and LON_RANGE_START <= max_lon <= LON_RANGE_END and
                min_lat <= max_lat and min_lon <= max_lon)

    def is_valid_circle(self, lat, lon, max_radius, min_radius):
        """Checks if the given latitude, longitude, and radius values define a valid circle.

        A valid circle satisfies the following conditions:
        - Latitude (`lat`) must be within the range [-90, 90].
        - Longitude (`lon`) must be within the range [-180, 180].
        - `max_radius` must be greater than 0.
        - `min_radius` must be non-negative (>= 0).
        - `min_radius` must be less than or equal to `max_radius`.

        Args:
            lat (float): Latitude of the circle's center.
            lon (float): Longitude of the circle's center.
            max_radius (float): Maximum radius of the circle.
            min_radius (float): Minimum radius of the circle.

        Returns:
            bool: `True` if the circle data is valid, `False` otherwise.
        """
        return (
            -90 <= lat <= 90 and
            LON_RANGE_START <= lon <= LON_RANGE_END and
            max_radius > 0 and
            min_radius >= 0 and
            min_radius <= max_radius
        )


    def get_unique_geo_constraints(self, geo_constraint_list):
        seen = set()
        unique = []
        for gc in geo_constraint_list:
            try:
                key = tuple(sorted(gc.coords.model_dump().items()))
            except Exception as e:
                print(f"Failed to serialize geo constraint: {e}")
                continue
            if key not in seen:
                seen.add(key)
                unique.append(gc)
        return unique

    def update_circle_areas(self):
        geo_constraint = self.get_geo_constraint() 
        lst_circ = [area.coords.model_dump() for area in geo_constraint
                    if area.geo_type == GeoConstraintType.CIRCLE ]

        if lst_circ:
            st.write(f"Circle Areas (Degree)")
            original_df_circ = pd.DataFrame(lst_circ, columns=CircleArea.model_fields)
            self.df_circ = st.data_editor(original_df_circ, key=f"circ_area", hide_index=True)

            # Validate column names before applying validation
            if {"lat", "lon", "max_radius", "min_radius"}.issubset(self.df_circ.columns):
                invalid_entries = self.df_circ[
                    ~self.df_circ.apply(lambda row: self.is_valid_circle(
                        row["lat"], row["lon"], row["max_radius"], row["min_radius"]
                    ), axis=1)
                ]

                if not invalid_entries.empty:
                    st.warning(
                        f"Invalid circle data detected. Ensure lat is between -90 and 90, lon is between {LON_RANGE_START} and {LON_RANGE_END}, "
                        "max_radius is positive, and min_radius ≤ max_radius."
                    )
                    return  # Stop further processing if validation fails

            else:
                st.error("Error: Missing required columns. Check CircleArea.model_fields.")
                return  # Stop execution if column names are incorrect

            circ_changed = not original_df_circ.equals(self.df_circ)

            if circ_changed:
                self.update_filter_geometry(self.df_circ, GeoConstraintType.CIRCLE, geo_constraint)
                self.refresh_map(reset_areas=False, clear_draw=True)

    def update_rectangle_areas(self):
        geo_constraint = self.get_geo_constraint() 
        lst_rect = [area.coords.model_dump() for area in geo_constraint
                    if isinstance(area.coords, RectangleArea) ]

        if lst_rect:
            st.write(f"Rectangle Areas")
            original_df_rect = pd.DataFrame(lst_rect, columns=RectangleArea.model_fields)
            self.df_rect = st.data_editor(original_df_rect, key=f"rect_area", hide_index=True)

            # Validate column names before applying validation
            if {"min_lat", "max_lat", "min_lon", "max_lon"}.issubset(self.df_rect.columns):
                invalid_entries = self.df_rect[
                    ~self.df_rect.apply(lambda row: self.is_valid_rectangle(
                        row["min_lat"], row["max_lat"], row["min_lon"], row["max_lon"]
                    ), axis=1)
                ]

                if not invalid_entries.empty:
                    st.warning(f"Invalid rectangle coordinates detected. Ensure min_lat ≤ max_lat and min_lon ≤ max_lon, with values within valid ranges (-90 to 90 for lat, {LON_RANGE_START} to {LON_RANGE_END} for lon).")
                    return  

            else:
                st.error("Error: Missing required columns. Check RectangleArea.model_fields.")
                return 


            rect_changed = not original_df_rect.equals(self.df_rect)

            if rect_changed:
                self.update_filter_geometry(self.df_rect, GeoConstraintType.BOUNDING, geo_constraint)
                self.refresh_map(reset_areas=False, clear_draw=True)

    def update_selected_data(self):
        if self.df_data_edit is None or self.df_data_edit.empty:
            if 'is_selected' not in self.df_markers.columns:
                self.df_markers['is_selected'] = False
            return

        if self.step_type == Steps.EVENT:

            selected_indices = self.df_markers[self.df_markers['is_selected']].index.tolist()

            self.settings.event.selected_catalogs = Catalog(events=None)

            selected_events = []
            for i in selected_indices:
                event = self.catalogs[i]
                if 'place' in self.df_markers.columns:
                    event.extra = {
                        'region': {
                            'value': self.df_markers.loc[i, 'place'],
                            'namespace': 'SEEDVAULT'
                        }
                    }
                selected_events.append(event)

            self.settings.event.selected_catalogs.extend(selected_events)
            return

        if self.step_type == Steps.STATION:
            self.settings.station.selected_invs = None
            
            if not self.df_markers.empty and 'is_selected' in list(self.df_markers.columns):
                # Get all selected (network,station) pairs at once
                selected_stations = self.df_markers[self.df_markers['is_selected']][['network', 'station']].drop_duplicates().apply(tuple, axis=1).tolist()
                
                if selected_stations:
                    self.settings.station.selected_invs = None
                    for i, ns in enumerate(selected_stations):
                        if i == 0:
                            self.settings.station.selected_invs = self.inventories.select(network=ns[0],station=ns[1])
                        else:
                            self.settings.station.selected_invs += self.inventories.select(network=ns[0],station=ns[1])
            return


    def handle_update_data_points(self, selected_idx):
        if not self.df_markers.empty:
            cols = self.df_markers.columns
            cols_to_disp = {c:c.capitalize() for c in cols if c not in self.cols_to_exclude}
            self.map_fg_marker, self.marker_info, self.fig_color_bar = add_data_points( self.df_markers, cols_to_disp, step=self.step_type, selected_idx = selected_idx, col_color=self.col_color, col_size=self.col_size)
        else:
            self.warning = "No data found."


    def get_data_globally(self):
        self.clear_all_data()
        clear_map_draw(self.map_disp)
        self.handle_get_data()        
        st.rerun()


    def refresh_map(self, reset_areas = False, selected_idx = None, clear_draw = False, rerun = False, get_data = True, recreate_map = True):
        if self.is_refreshing:
            return
        self.is_refreshing = True

        try:
            geo_constraint = self.get_geo_constraint()

            if recreate_map:
                self.map_disp = create_map(
                    map_id=self.map_id, 
                    zoom_start=self.map_view_zoom,
                    map_center=[
                        self.map_view_center.get("lat", 0.0),
                        self.map_view_center.get("lng", 0.0)
                    ]
                )

            if clear_draw:
                clear_map_draw(self.map_disp)
                self.all_feature_drawings = geo_constraint
                self.map_fg_area= add_area_overlays(areas=geo_constraint)
            else:
                if reset_areas:
                    geo_constraint = []
                else:
                    geo_constraint = self.all_current_drawings + self.all_feature_drawings

            self.set_geo_constraint(geo_constraint)

            if selected_idx != None:
                self.handle_update_data_points(selected_idx)
            else:
                # @NOTE: Below is added to resolve triangle marker displays.
                #        But it results in map blinking and hence a chance to
                #        break the map.
                if not clear_draw:
                    clear_map_draw(self.map_disp)
                    self.all_feature_drawings = geo_constraint
                    self.map_fg_area= add_area_overlays(areas=geo_constraint)
                if get_data:
                    self.has_fetch_new_data = False
                    self.handle_get_data()

            if rerun:
                st.rerun()
        finally:
            self.is_refreshing = False

    def reset_markers(self):
        self.map_fg_marker = None
        self.df_markers    = pd.DataFrame()
    # ====================
    # GET DATA
    # ====================

    def fetch_data_with_loading(self, fetch_func, *args, spinner_message="🔄 Fetching data...", success_message="✅ Data loaded successfully.", **kwargs):
        st.session_state['loading'] = True
        self.add_loading_overlay()
        with st.spinner(spinner_message):
            try:
                fetch_func(*args, **kwargs)
                # st.success(success_message)
            except Exception as e:
                st.error(f"⚠️ An unexpected error occurred: {str(e)}")
            finally:
                st.session_state['loading'] = False

    def add_loading_overlay(self):
        st.markdown("""
            <style>
            .loading-overlay {
                position: fixed;
                top: 0; left: 0; width: 100%; height: 100%;
                background-color: rgba(255, 255, 255, 0.5);
                z-index: 9999;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 24px;
                color: black;
            }
            </style>
            <div class="loading-overlay">🔄 Loading... Please wait.</div>
        """, unsafe_allow_html=True)

    def handle_get_data(self, is_import: bool = False, uploaded_file = None):
        http_error = {
            204: "No data found",
            400: "Malformed input or unrecognized search parameter",
            401: "Unauthorized access",
            403: "Authentication failed for restricted data",
            413: "Data request is too large for server; try reducing size into several pieces",
            502: "Server response is invalid; please try again another time",
            503: "Server appears to be down; please try again another time",
            504: "Server appears to be down; please try again another time"
        }        
        self.warning = None
        self.error   = None
        self.has_error = False
        try:
            if self.step_type == Steps.EVENT:
                self.catalogs = Catalog()
                # self.catalogs = get_event_data(self.settings.model_dump_json())
                if is_import:
                    self.import_xml(uploaded_file)
                else:
                    self.catalogs = get_event_data(self.settings)

                if self.catalogs:
                    self.df_markers = event_response_to_df(self.catalogs)
                else:
                    self.reset_markers()

            if self.step_type == Steps.STATION:
                self.inventories = Inventory()
                # self.inventories = get_station_data(self.settings.model_dump_json())
                if is_import:
                    self.import_xml(uploaded_file)
                else:
                    self.inventories = get_station_data(self.settings)
                if self.inventories:
                    self.df_markers = station_response_to_df(self.inventories)
                else:
                    self.reset_markers()
                
            if not self.df_markers.empty:
                cols = self.df_markers.columns
                cols_to_disp = {c:c.capitalize() for c in cols if c not in self.cols_to_exclude}
                self.map_fg_marker, self.marker_info, self.fig_color_bar = add_data_points( self.df_markers, cols_to_disp, step=self.step_type, col_color=self.col_color, col_size=self.col_size)

            else:
                self.warning = "No data available for the selected settings."

        except Exception as e:
            error_message = str(e)
            http_status_code = None

            match = re.search(r"\b(\d{3})\b", error_message)
            if match:
                http_status_code = int(match.group(1))

            user_friendly_message = http_error.get(http_status_code, "An unexpected error occurred. Please try again.")

            self.has_error = True
            self.error = f"⚠️ {user_friendly_message}\n\n"

            if http_status_code:
                self.error += f"**Technical details:**\n\nError {http_status_code}: {error_message}"

            print(self.error)  # Logging for debugging

    def clear_all_data(self):
        self.map_fg_marker= None
        self.map_fg_area= None
        self.df_markers = pd.DataFrame()
        self.all_current_drawings = []

        if self.step_type == Steps.EVENT:
            self.catalogs=Catalog()
            self.settings.event.geo_constraint = []
            self.settings.event.selected_catalogs=Catalog(events=None)

        if self.step_type == Steps.STATION:
            self.inventories = Inventory()
            self.settings.station.geo_constraint = []
            self.settings.station.selected_invs = None

        # not sure if plotting these area tables is useful
        self.update_rectangle_areas()
        self.update_circle_areas()


    def get_selected_marker_info(self):
        info = self.clicked_marker_info
        if self.step_type == Steps.EVENT:
            return f"Event No {info['id']}: {info['Magnitude']} {info['Magnitude type']}, {info['Depth (km)']} km, {info['Place']}"
        if self.step_type == Steps.STATION:
            return f"Station No {info['id']}: {info['Network']}, {info['Station']}"
    # ===================
    # SELECT DATA
    # ===================
    def get_selected_idx(self):
        if self.df_markers.empty:
            return []
        
        mask = self.df_markers['is_selected']
        return self.df_markers[mask].index.tolist()

    def sync_df_markers_with_df_edit(self):
        if self.df_data_edit is None:
            # st.error("No data has been edited yet. Please make a selection first.")
            return

        if 'is_selected' not in self.df_data_edit.columns:
            # st.error("'is_selected' column is missing from the edited data.")
            return

        self.df_markers['is_selected'] = self.df_data_edit['is_selected']

    def refresh_map_selection(self, rerun=True, recreate=False):
        selected_idx = self.get_selected_idx()
        self.update_selected_data()
        self.refresh_map(reset_areas=False, selected_idx=selected_idx, rerun=rerun, recreate_map=recreate)

    # ===================
    # PREV SELECTION
    # ===================
    def get_prev_step_df(self):
        if self.prev_step_type == Steps.EVENT:
            self.df_markers_prev = event_response_to_df(self.settings.event.selected_catalogs)
            return

        if self.prev_step_type == Steps.STATION:
            self.df_markers_prev = station_response_to_df(self.settings.station.selected_invs)
            return

        self.df_markers_prev = pd.DataFrame()

    def display_prev_step_selection_marker(self):
        if self.stage > 1:
            col_color = None
            col_size  = None
            if self.prev_step_type == Steps.EVENT:
                col_color = "depth (km)"
                col_size  = "magnitude"
            
            if self.prev_step_type == Steps.STATION:
                col_color = "network"

            if not self.df_markers_prev.empty:
                cols = self.df_markers_prev.columns
                cols_to_disp = {c:c.capitalize() for c in cols if c not in self.cols_to_exclude}
                selected_idx = self.df_markers_prev.index.tolist()
                self.map_fg_prev_selected_marker, _, _ = add_data_points( self.df_markers_prev, cols_to_disp, step=self.prev_step_type,selected_idx=selected_idx, col_color=col_color, col_size=col_size)


    def display_prev_step_selection_table(self):
        if self.stage > 1:
            if self.df_markers_prev.empty:
                st.write(f"No selected {self.TXT.PREV_STEP}s")
            else:
                # with st.expander(f"Search around {self.TXT.PREV_STEP}", expanded = True):
                self.area_around_prev_step_selections()
                # st.write(f"Total Number of Selected {self.TXT.PREV_STEP.title()}s: {len(self.df_markers_prev)}")
                # st.dataframe(self.df_markers_prev, width='stretch')


    def area_around_prev_step_selections(self):

        st.markdown(
            """
            <style>
            div.stButton > button {
                margin-top: 25px;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.write(f"Define an area around the selected {self.TXT.STEP}s.")
        c1, c2 = st.columns([1, 1])

        with c1:
            self.settings.event.min_radius = st.number_input("Minimum radius (degree)", 
                value=self.settings.event.min_radius or 0.0,
                step=0.5,min_value=0.0,max_value=180.0)
        with c2:
            self.settings.event.max_radius = st.number_input("Maximum radius (degree)",
                value=self.settings.event.max_radius or 0.0,
                step=0.5,min_value=0.0,max_value=180.0)
        try:
            min_radius = float(self.settings.event.min_radius)
            max_radius = float(self.settings.event.max_radius)
        except ValueError:
            st.error("Please enter valid numeric values for the radius.")
            return

        if min_radius >= max_radius:
            st.error("Maximum radius should be greater than minimum radius.")
            return

        if not hasattr(self, 'prev_min_radius') or not hasattr(self, 'prev_max_radius'):
            self.prev_min_radius = None
            self.prev_max_radius = None

        if not hasattr(self, 'prev_marker'):
            self.prev_marker = pd.DataFrame() 

        df_has_changed = (
            self.df_markers_prev.shape[0] != self.prev_marker.shape[0] or 
            not self.df_markers_prev.equals(self.prev_marker) 
        )

        # with c3:
        if st.button("Draw Area", key=self.get_key_element("Draw Area")):
            if (
                self.prev_min_radius is None or 
                self.prev_max_radius is None or 
                min_radius != self.prev_min_radius or 
                max_radius != self.prev_max_radius or 
                df_has_changed
            ):      
                self.update_area_around_prev_step_selections(min_radius, max_radius)
                self.prev_min_radius = min_radius
                self.prev_max_radius = max_radius
                self.prev_marker = self.df_markers_prev.copy()


            self.refresh_map(reset_areas=False, clear_draw=True, rerun=True)
            # st.rerun()

    def update_area_around_prev_step_selections(self, min_radius, max_radius):
        min_radius_value = float(min_radius)
        max_radius_value = float(max_radius)

        updated_constraints = []

        # Normalize df_markers_prev to 0–360 longitudes for consistent comparison
        df_markers_normalized = self.df_markers_prev.copy()
        df_markers_normalized['longitude'] = df_markers_normalized['longitude'] % 360

        geo_constraints = self.get_geo_constraint()

        # Update existing circle constraints
        for geo in geo_constraints:
            if geo.geo_type == GeoConstraintType.CIRCLE:
                lat, lon = geo.coords.lat, geo.coords.lon % 360  # Normalize for comparison
                matching_event = df_markers_normalized[
                    (df_markers_normalized['latitude'] == lat) &
                    (df_markers_normalized['longitude'] == lon)
                ]

                if not matching_event.empty:
                    geo.coords.min_radius = min_radius_value
                    geo.coords.max_radius = max_radius_value
                    geo.coords.lon = lon  # Ensure normalized
            updated_constraints.append(geo)

        # Add missing circles for markers not already covered
        for _, row in df_markers_normalized.iterrows():
            lat, lon = row['latitude'], row['longitude']  # already normalized above
            if not any(
                geo.geo_type == GeoConstraintType.CIRCLE and
                geo.coords.lat == lat and geo.coords.lon == lon
                for geo in updated_constraints
            ):
                new_donut = CircleArea(lat=lat, lon=lon, min_radius=min_radius_value, max_radius=max_radius_value)
                geo = GeometryConstraint(geo_type=GeoConstraintType.CIRCLE, coords=new_donut)
                updated_constraints.append(geo)

        # Remove any constraints whose markers no longer exist
        updated_constraints = [
            geo for geo in updated_constraints
            if not (geo.geo_type == GeoConstraintType.CIRCLE and
                    df_markers_normalized[
                        (df_markers_normalized['latitude'] == geo.coords.lat) &
                        (df_markers_normalized['longitude'] == geo.coords.lon)
                    ].empty)
        ]

        self.set_geo_constraint(updated_constraints)

    # ===================
    # FILES
    # ===================
    def exp_imp_events_stations(self):
        st.write(f"#### Export/Import {self.TXT.STEP.title()}s (XML)")

        c11, c22 = st.columns([1,1])
        self.export_as_alternate = st.checkbox(
            "Export as " + ("TXT" if self.step_type == Steps.STATION else "KML"), 
            key=self.get_key_element("export_alternate_format")
        )
        with c11:

            if self.export_as_alternate:
                export_data = self.export_txt_tmpfile(export_selected=False)
                file_extension = ".txt" if self.step_type == Steps.STATION else ".kml"
                file_name = f"{self.TXT.STEP}s{file_extension}"
                mime_type = "text/plain" if self.step_type == Steps.STATION else "application/vnd.google-earth.kml+xml"
            else:
                export_data = self.export_xml_bytes(export_selected=False)
                file_name = f"{self.TXT.STEP}s.xml"
                mime_type = "application/xml"

            st.download_button(
                f"Download All", 
                key=self.get_key_element(f"Download All {self.TXT.STEP.title()}s"),
                data=export_data,
                file_name=file_name,
                mime=mime_type,
                disabled=(len(self.catalogs.events) == 0 and (self.inventories is None or len(self.inventories.get_contents().get('stations')) == 0))
            )


            ## @NOTE: Download Selected had to be with the table.
            ## if (len(self.catalogs.events) > 0 or len(self.inventories.get_contents().get('stations')) > 0):
            #st.download_button(
            #    f"Download All", 
            #    key=self.get_key_element(f"Download All {self.TXT.STEP.title()}s"),
            #    data=self.export_xml_bytes(export_selected=False),
            #    file_name = f"{self.TXT.STEP}s.xml",
            #    mime="application/xml",
            #    disabled=(len(self.catalogs.events) == 0 and (self.inventories is None or len(self.inventories.get_contents().get('stations')) == 0))
            #)

        def reset_uploaded_file_processed():
            st.session_state['uploaded_file_processed'] = False

        uploaded_file = st.file_uploader(f"Import {self.TXT.STEP.title()}s from a File", on_change=lambda:  reset_uploaded_file_processed())
        if uploaded_file and not st.session_state['uploaded_file_processed']:
            self.clear_all_data()
            self.refresh_map(reset_areas=True, clear_draw=True)
            self.handle_get_data(is_import=True, uploaded_file=uploaded_file)

            st.session_state['uploaded_file_processed'] = True

        if self.has_error and "Import Error" in self.error:
            st.error(self.error)

        return c22

    def export_xml_bytes(self, export_selected: bool = True):
        with io.BytesIO() as f:
            if not self.df_markers.empty and len(self.df_markers) > 0:
                if export_selected:
                # self.sync_df_markers_with_df_edit()
                    self.update_selected_data()
                
                if self.step_type == Steps.STATION:
                    inv = self.settings.station.selected_invs if export_selected else self.inventories
                    if inv:
                        inv.write(f, format='STATIONXML')

                if self.step_type == Steps.EVENT:
                    cat = self.settings.event.selected_catalogs if export_selected else self.catalogs
                    if cat:
                        cat.write(f, format='QUAKEML')

            # if f.getbuffer().nbytes == 0:
            #     f.write(b"No Data")

            return f.getvalue()

    def export_txt_tmpfile(self, export_selected: bool = True):
        extension = ".txt" if self.step_type == Steps.STATION else ".kml"

        # Create temporary file with the correct extension
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            if not self.df_markers.empty and len(self.df_markers) > 0:
                if export_selected:
                    self.update_selected_data()

                if self.step_type == Steps.STATION:
                    inv = self.settings.station.selected_invs if export_selected else self.inventories
                    if inv:
                        inv.write(temp_path, format='STATIONTXT')
                if self.step_type == Steps.EVENT:
                    cat = self.settings.event.selected_catalogs if export_selected else self.catalogs
                    if cat:
                        cat.write(temp_path, format='KML')

            with open(temp_path, 'rb') as f:
                return f.read()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


    def import_xml(self, uploaded_file):
        st.session_state["show_error_workflow_combined"] = False
        try:
            if uploaded_file is not None:
                if self.step_type == Steps.STATION:
                    inv = read_inventory(uploaded_file)
                    self.inventories = Inventory()
                    self.inventories += inv
                if self.step_type == Steps.EVENT:
                    cat = read_events(uploaded_file)
                    self.catalogs = Catalog()
                    self.catalogs.extend(cat)
        except Exception as e:
            if "unknown format" in str(e).lower():
                self.trigger_error(f"Import Error: Unknown format for file {uploaded_file.name}. Please ensure the file is in correct format and **do not forget to remove the {uploaded_file.name} file from upload.**")
            self.trigger_error(f"Import Error: An error occured when importing {uploaded_file.name}. Please ensure the file is in correct format and **do not forget to remove the {uploaded_file.name} file from upload.**")

    # ===================
    # WATCHER
    # ===================
    def watch_all_drawings(self, all_drawings):
        # if self.all_current_drawings != all_drawings:
        #     self.all_current_drawings = all_drawings
        #     self.refresh_map(rerun=True, get_data=True)
        #print(f"DEBUG watch_all_drawings called: step={self.step_type}, prev_step={self.prev_step_type}, stage={self.stage}")
        #print(f"DEBUG has_fetch_new_data: {self.has_fetch_new_data}")
        #print(f"DEBUG drawings changed: {self.all_current_drawings != all_drawings}")        
        if self.is_refreshing or self.all_current_drawings == all_drawings:
            #print("DEBUG: Early return - no changes or already refreshing")
            return

        self.all_current_drawings = all_drawings
        if not self.has_fetch_new_data:
            self.has_fetch_new_data = True
            self.refresh_map(rerun=False, get_data=True)
        else:
            if self.has_fetch_new_data:
                self.has_fetch_new_data = False

    # ===================
    #  ERROR HANDLES
    # ===================
    def trigger_error(self, message):
        """Set an error message in session state to be displayed."""
        self.has_error = True
        self.error = message

    # ===================
    # RENDER
    # ===================
    def render_map_buttons(self):

        cc1, cc2, cc3 = st.columns([1,1,1])

        with cc1:
            if st.button(
                f"Load {self.TXT.STEP.title()}s", 
                key=self.get_key_element(f"Load {self.TXT.STEP}s")
            ):
                self.refresh_map(reset_areas=False, clear_draw=False, rerun=False)

        with cc2:
            if st.button(self.TXT.CLEAR_ALL_MAP_DATA, key=self.get_key_element(self.TXT.CLEAR_ALL_MAP_DATA)):
                self.clear_all_data()
                self.refresh_map(reset_areas=True, clear_draw=True, rerun=True, get_data=False)

        with cc3:
            if st.button(
                "Reload Map", 
                key=self.get_key_element(f"ReLoad {self.TXT.STEP}s")
            ):
                self.refresh_map(get_data=False, clear_draw=True, rerun=True, recreate_map=True)


    def render_map_handles(self):
        # not sure if plotting these area tables is useful
        with st.expander("Shape tools - edit areas", expanded=True):
            self.update_rectangle_areas()
            self.update_circle_areas()


    def render_import_export(self):
        def reset_import_setting_processed():
            if uploaded_file is not None:
                uploaded_file_info = f"{uploaded_file.name}-{uploaded_file.size}"
                if "uploaded_file_info" not in st.session_state or st.session_state.uploaded_file_info != uploaded_file_info:
                    st.session_state['import_setting_processed'] = False
                    st.session_state['uploaded_file_info'] = uploaded_file_info  

        # st.sidebar.markdown("### Import/Export Settings")

        with st.expander("Import & Export", expanded=True):
            tab1, tab2 = st.tabs([f"{self.TXT.STEP.title()}s", "Settings"])
            with tab2:
                config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../service/config.cfg')
                config_file_path = os.path.abspath(config_file_path)

                st.markdown("#### ⬇️ Export Settings")

                if os.path.exists(config_file_path):
                    with open(config_file_path, "r") as file:
                        file_data = file.read()

                    st.download_button(
                        label="Download file",
                        data=file_data,  
                        file_name="config.cfg",
                        mime="application/octet-stream",
                        help="Download the current settings.",
                        width='stretch',
                    )
                else:
                    st.caption("No config file available for download.")

                # Import settings should only be displayed if stage == 1
                if self.stage == 1:
                    st.markdown("#### 📂 Import Settings")
                    uploaded_file = st.file_uploader(
                        "Import Settings",type=["cfg"], on_change=reset_import_setting_processed,
                        help="Upload a config file (.cfg) to update settings." , label_visibility="collapsed"
                    )

                    if uploaded_file:
                        if not st.session_state.get('import_setting_processed', False):
                            file_like_object = io.BytesIO(uploaded_file.getvalue())
                            text_file_object = io.TextIOWrapper(file_like_object, encoding='utf-8')

                            settings = SeismoLoaderSettings.from_cfg_file(text_file_object)
                            if(settings.status_handler.has_errors()):
                                errors = settings.status_handler.generate_status_report("errors")
                                st.error(f"{errors}\n\n**Please review the errors in the imported file. Resolve them before proceeding.**")

                                if(settings.status_handler.has_warnings()):
                                    warning = settings.status_handler.generate_status_report("warnings")
                                    st.warning(warning)                            
                                settings.status_handler.display()

                            else:    
                                settings.event.geo_constraint = []
                                settings.station.geo_constraint = []           
                                settings.event.selected_catalogs=Catalog(events=None)    
                                settings.station.selected_invs = None
                                
                                self.clear_all_data()
                                # self.settings = settings
                                for key, value in vars(settings).items():
                                    setattr(self.settings, key, value)
                                self.df_markers_prev= pd.DataFrame()
                                self.refresh_map(reset_areas=True, clear_draw=True)
                                st.session_state['import_setting_processed'] = True   

                                if(settings.status_handler.has_warnings()):
                                    warning = settings.status_handler.generate_status_report("warnings")
                                    st.warning(warning) 

                                st.success("Settings imported successfully!")   
            with tab1:
                c2_export = self.exp_imp_events_stations()

            return c2_export


    def render_map_right_menu(self):
        if self.prev_step_type and len(self.df_markers_prev) < 6:
            with st.expander(f"Search Around {self.prev_step_type.title()}s", expanded=True):
                self.display_prev_step_selection_table() 

    def render_map(self):

        if self.map_disp is None:
            self.map_disp = create_map(map_id=f"init_{self.map_id}")
        else:
            clear_map_layers(self.map_disp)
        
        self.display_prev_step_selection_marker()

        # feature_groups = [fg for fg in [self.map_fg_area, self.map_fg_marker] if fg is not None]
        feature_groups = [fg for fg in [self.map_fg_area, self.map_fg_marker , self.map_fg_prev_selected_marker] if fg is not None]
        

        info_display = f"ℹ️ Use **shape tools** to search **{self.TXT.STEP}s** in confined areas   "
        info_display += "\nℹ️ Use **Reload** button to refresh map if needed   "

        if self.step_type == Steps.EVENT:
           info_display += "\nℹ️ **Marker size** is associated with **earthquake magnitude**"

        st.caption(info_display)
        
        c1, c2 = st.columns([18,1])
        with c1:
            self.map_output = st_folium(
                self.map_disp, 
                key=f"map_{self.map_id}",
                feature_group_to_add=feature_groups, 
                width='stretch', 
                # height=self.map_height
            )


        with c2:
            if self.fig_color_bar:
                st.pyplot(self.fig_color_bar)

        self.watch_all_drawings(get_selected_areas(self.map_output))

        # @IMPORTANT NOTE: Streamlit-Folium does not provide a direct way to tag a Marker with
        #                  some metadata, including adding an id. The options are using PopUp
        #                  window or tooltips. Here, we have embedded a line at the bottom of the
        #                  popup to be able to get the Event/Station Ids as well as the type of 
        #                  the marker, ie, event or station.

        if self.map_output is not None and self.map_output.get("center"):
            self.map_view_center = self.map_output.get("center", {})
            self.map_view_zoom = self.map_output.get("zoom", 2)

        # st.write(self.map_output)
        if self.map_output and self.map_output.get('last_object_clicked') is not None:
            last_clicked = self.map_output['last_object_clicked_popup']

            if isinstance(last_clicked, str):
                idx_info = last_clicked.splitlines()[-1].split()
                step = idx_info[0].lower()
                idx  = int(idx_info[1])
                if step == self.step_type:
                    if self.selected_marker_map_idx is None or idx != self.selected_marker_map_idx:
                        self.selected_marker_map_idx = idx
                        self.clicked_marker_info = self.marker_info[self.selected_marker_map_idx]

            else:
                self.clicked_marker_info = None

        if self.warning:
            st.warning(self.warning)


    def render_marker_select(self):
        def handle_marker_select():
            # selected_data = self.get_selected_marker_info()

            if 'is_selected' not in self.df_markers.columns:
                self.df_markers['is_selected'] = False

            try:
                if self.clicked_marker_info['step'] == self.step_type:
                    if not self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected']:
                        self.sync_df_markers_with_df_edit()
                        self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected'] = True
                        self.clicked_marker_info = None
                        if self.auto_refresh_enabled:
                            self.refresh_map_selection()
                    # else:
                    #     self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected'] = False
                    #     self.refresh_map_selection()

            except KeyError:
                print("Selected map marker not found")
  

        if self.clicked_marker_info:
            handle_marker_select()


    def render_data_table(self, c5_map):
        if self.df_markers.empty:
            st.warning("No data available for the selected settings.")
            return

        # Ensure `is_selected` column exists
        if 'is_selected' not in self.df_markers.columns:
            self.df_markers['is_selected'] = False

        # Define ordered columns
        cols = self.df_markers.columns
        orig_cols = [col for col in cols if col != 'is_selected']
        if self.step_type == Steps.STATION:
            ordered_col = ['is_selected'] + orig_cols
        else: # Steps.EVENT
            ordered_col = ['is_selected','place','time','magnitude_combined','latitude','longitude','depth (km)']

        # Define config
        config = {col: {'disabled': True} for col in orig_cols}
        config['is_selected'] = st.column_config.CheckboxColumn('Select')

        state_key = f'initial_df_markers_{self.stage}'

        # Store the initial state in the session if not already stored
        if state_key not in st.session_state:
            st.session_state[state_key] = self.df_markers.copy()

        self.data_table_view(ordered_col, config, state_key)


        # Download button logic
        is_disabled = 'is_selected' not in self.df_markers or self.df_markers['is_selected'].sum() == 0

        with c5_map:

            if self.export_as_alternate:
                export_data = self.export_txt_tmpfile(export_selected=True)
                file_extension = ".txt" if self.step_type == Steps.STATION else ".kml"
                file_name = f"{self.TXT.STEP}s_selected{file_extension}"
                mime_type = "text/plain" if self.step_type == Steps.STATION else "application/vnd.google-earth.kml+xml"
            else:
                export_data = self.export_xml_bytes(export_selected=True)
                file_name = f"{self.TXT.STEP}s_selected.xml"
                mime_type = "application/xml"

            st.download_button(
                f"Download Selected",
                key=self.get_key_element(f"Download Selected {self.TXT.STEP.title()}s"),
                data=export_data,
                file_name=file_name,
                mime=mime_type,
                disabled=is_disabled
            )

    def on_change_df_table(self):
        if self.auto_refresh_enabled:
            self.delay_selection = 0.2
        else:
            self.update_selected_data()
            self.delay_selection = 0

    def render_auto_refresh_toggle(self):
        """Renders the auto-refresh toggle between the map and data table."""

        # Initialize the toggle state if not already in session state
        if 'auto_refresh_toggle' not in st.session_state:
            st.session_state['auto_refresh_toggle'] = self.auto_refresh_enabled

        # Create columns for the toggle and refresh button
        col1, col2 = st.columns([3, 1])

        with col1:
            # Add the toggle switch
            st.toggle(
                "Auto-Refresh Enabled",
                key='auto_refresh_toggle',
                help="Toggle automatic refresh when making selections or drawing areas (helpful when table is large)",
                on_change=lambda: self.update_auto_refresh_state()
            )

        self.update_auto_refresh_state()            

    def update_auto_refresh_state(self):
        self.auto_refresh_enabled = st.session_state['auto_refresh_toggle']
    
    def data_table_view(self, ordered_col, config, state_key):
        """Displays the full data table, allowing selection."""

        def _get_column_width(column):
            max_length = max(self.df_markers[column].astype(str).apply(len))  # Get max string length            
            if max_length <= 10:
                return None 
            elif max_length <= 10:
                return "small"
            elif max_length <= 50 or column=="description" or column=="loc. codes":
                return "medium"
            elif max_length <= 100:
                return None
            return "large"


        def _format_columns():
            column_map = {}

            if self.step_type == Steps.EVENT:

                # combine magnitude scalar and type into one column
                self.df_markers['magnitude_combined'] = self.df_markers['magnitude'].astype(str) + ' ' + self.df_markers['magnitude type']

                column_map = {
                    "is_selected": st.column_config.Column("", width=4, disabled=False),
                    "place": st.column_config.TextColumn("place", width=None, disabled=True),
                    "magnitude_combined": st.column_config.TextColumn("mag", width=12, disabled=True),
                    #"magnitude": st.column_config.NumberColumn("mag", format="%.1f",width=6, disabled=True),
                    #"magnitude type": st.column_config.Column("type", width=6, disabled=True),
                    "time": st.column_config.DatetimeColumn("origin time", width=18, disabled=True),
                    "longitude": st.column_config.NumberColumn("lon", format="%.4f", width=8, disabled=True),
                    "latitude": st.column_config.NumberColumn("lat", format="%.4f", width=8, disabled=True),
                    "depth (km)": st.column_config.NumberColumn("dep (km)", format="%.1f", width=6, disabled=True),
                }

            if self.step_type == Steps.STATION:
                column_map = {
                        "is_selected": st.column_config.Column("", width=4, disabled=False),
                        "network": st.column_config.TextColumn("net", width=2, disabled=True),
                        "station": st.column_config.TextColumn("sta", width=5, disabled=True),
                        "description": st.column_config.TextColumn("description", width=38, disabled=True),
                        "latitude": st.column_config.NumberColumn("lat", format="%.4f", width=8, disabled=True),
                        "longitude": st.column_config.NumberColumn("lon", format="%.4f", width=8, disabled=True),
                        "elevation": st.column_config.NumberColumn("elev", format="%d", width=6, disabled=True),
                        "loc. codes": st.column_config.TextColumn("loc", width=None),
                        "channels": st.column_config.TextColumn("cha", width=None),
                        "start date (UTC)": st.column_config.Column("start", width=13, disabled=True),
                        "end date (UTC)": st.column_config.Column("end", width=11, disabled=True),
                    }

            for col in ordered_col:
                if col in column_map:
                    config[col] = column_map.get(col)
                else:
                    config[col] = st.column_config.Column(col)

            return config


        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            st.write(f"Total Number of {self.TXT.STEP.title()}s: {len(self.df_markers)}")

        with c2:
            if st.button("Select All", key=self.get_key_element("Select All")):
                self.df_markers['is_selected'] = True
                self.update_selected_data()
                self.refresh_map_selection(rerun=True)

        with c3:
            if st.button("Unselect All", key=self.get_key_element("Unselect All")):
                self.df_markers['is_selected'] = False
                self.clicked_marker_info = None
                self.update_selected_data()
                self.refresh_map_selection(rerun=True)

        # Add a manual refresh button if auto-refresh is disabled
        # BUG: if Un/Select All only operates with auto_refresh, 
        #      first click doesn't register / have to click twice for Select All and Unselect All
        #      for now we just have Un/Select All just work regardless of auto_refresh_state
        #      ...which sort of makes sense anyway
        if not self.auto_refresh_enabled:
            if st.button("Apply Selections", key=self.get_key_element("Apply Selections")):
                self.sync_df_markers_with_df_edit()
                self.refresh_map_selection(rerun=True)

        #OFF for now / self.selected_items_view(state_key) #this adds the red icons above the table.. possibly not worth the lag

        height = (len(self.df_markers) + 1) * 35 + 2
        height = min(100*35, height)

        # These create "bubble icons" for the individual channel codes in the table.. but take up extra space
        #df_markers_view = None
        #if self.step_type == Steps.STATION:
        #    df_markers_view = deepcopy(self.df_markers)
        #    df_markers_view["loc. codes"] = df_markers_view["loc. codes"].apply(lambda x: x.split(",")) 
        #    df_markers_view["channels"] = df_markers_view["channels"].apply(lambda x: x.split(","))            
        #    # df_markers_view.drop("elevation", axis=1, inplace=True)

        self.df_data_edit = st.data_editor(
            #df_markers_view if self.step_type == Steps.STATION else self.df_markers, # for bubble icons
            self.df_markers,
            hide_index = True, 
            column_config=_format_columns(), 
            column_order = ordered_col, 
            key=self.get_key_element("Data Table"),
            width='stretch',
            height=height,
            on_change=self.on_change_df_table
        )

        if len(self.df_data_edit) != len(st.session_state[state_key]):
            has_changed = True
        else:
            has_changed = not self.df_data_edit.equals(st.session_state[state_key])

        if has_changed:
            if self.delay_selection > 0:
                sleep(self.delay_selection)
            st.session_state[state_key] = self.df_data_edit.copy()  # Save the unsorted version to preserve user sorting

            if self.auto_refresh_enabled:
                self.sync_df_markers_with_df_edit()
                self.refresh_map_selection()
                self.delay_selection = 0.2
            #else: (seems to work better with this commented...?)
            #    self.sync_df_markers_with_df_edit()

    # This function pertains to the red icons above the table.. currently disabled
    def selected_items_view(self, state_key):
        """Displays selected items using an actual `st.multiselect`, controlled by table selection."""

        df_selected = self.df_markers[self.df_markers['is_selected']].copy()

        if df_selected.empty:
            return

        if self.step_type == Steps.EVENT:
            unique_columns = ["place", "time"]

        elif self.step_type == Steps.STATION:
            unique_columns = ["network", "station"]

        # Ensure all unique_columns exist in the dataframe
        missing_columns = [col for col in unique_columns if col not in df_selected.columns]
        if missing_columns:
            st.warning(f"Missing columns in data: {', '.join(missing_columns)}")
            return


        df_selected["display_label"] = df_selected[unique_columns].astype(str).agg(".".join, axis=1)

        selected_items = df_selected["display_label"].tolist()

        updated_selection = st.multiselect(
            "Selected Items",
            options=selected_items,
            default=selected_items,
            key="selected_items_list",
            placeholder="Selected Items",
            disabled=False
        )

        # Determine which items were removed
        removed_items = set(selected_items) - set(updated_selection)

        if removed_items:
            for item in removed_items:
                values = item.split(" | ")  # Extract the separated values

                # Construct a mask for filtering rows based on extracted values
                mask = (self.df_markers[unique_columns[0]].astype(str) == values[0])
                for col, val in zip(unique_columns[1:], values[1:]):  # Loop over remaining columns
                    mask &= (self.df_markers[col].astype(str) == val)

                # Update `is_selected` to False for matching rows
                self.df_markers.loc[mask, 'is_selected'] = False


            st.session_state[state_key] = self.df_markers.copy()
            self.refresh_map_selection(recreate=False)


    def render(self):
        with st.sidebar:
            self.render_map_handles()
            self.render_map_right_menu()

        if self.has_error and "Import Error" not in self.error:
            c1_err, c2_err = st.columns([4,1])
            with c1_err:
                if self.error == "Error: 'TimeoutError' object has no attribute 'splitlines'":
                    st.error("server timeout, try again in a minute")                
                st.error(self.error)
            with c2_err:
                if st.button(":material/close:"): # ❌
                    self.has_error = False
                    self.error = ""
                    st.rerun()

        if self.step_type == Steps.EVENT:
            self.event_filter()

        if self.step_type == Steps.STATION:
            self.station_filter()

        with st.sidebar:
            c2_export = self.render_import_export()

        self.get_prev_step_df()

        self.render_map()

        # Add the auto-refresh toggle between map and table
        self.render_auto_refresh_toggle()

        if not self.df_markers.empty:
            self.render_marker_select()
            with st.expander(self.TXT.SELECT_DATA_TABLE_TITLE, expanded = not self.df_markers.empty):
                self.render_data_table(c2_export)
