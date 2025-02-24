import io
import os
import re
from typing import List
from copy import deepcopy
import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from datetime import datetime, time
from obspy.core.event import Catalog, read_events
from obspy.core.inventory import Inventory, read_inventory


from seed_vault.ui.components.map import create_map, add_area_overlays, add_data_points, clear_map_layers, clear_map_draw,add_map_draw
from seed_vault.ui.pages.helpers.common import get_selected_areas, save_filter

from seed_vault.service.events import get_event_data, event_response_to_df
from seed_vault.service.stations import get_station_data, station_response_to_df

from seed_vault.models.config import SeismoLoaderSettings, GeometryConstraint
from seed_vault.models.common import CircleArea, RectangleArea

from seed_vault.enums.config import GeoConstraintType, Levels
from seed_vault.enums.ui import Steps

from seed_vault.service.utils import convert_to_datetime, check_client_services, get_time_interval


class BaseComponentTexts:
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

    cols_to_exclude             = ['detail', 'is_selected']

    has_error: bool = False
    error: str = ""

    @property
    def page_type(self) -> str:
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
        self.settings       = settings
        self.old_settings   = deepcopy(settings)
        self.step_type      = step_type
        self.prev_step_type = prev_step_type
        self.stage          = stage
        self.map_id         = f"map_{step_type.value}_{prev_step_type.value}_{stage}" if prev_step_type else f"map_{step_type.value}_no_prev_{stage}"   # str(uuid.uuid4())
        self.map_disp       = create_map(map_id=self.map_id)
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


    def get_key_element(self, name):        
        return f"{name}-{self.step_type.value}-{self.stage}"


    def get_geo_constraint(self):
        if self.step_type == Steps.EVENT:
            return self.settings.event.geo_constraint
        if self.step_type == Steps.STATION:
            return self.settings.station.geo_constraint
        return []
    
    def set_geo_constraint(self, geo_constraint: List[GeometryConstraint]):
        if self.step_type == Steps.EVENT:
            self.settings.event.geo_constraint = geo_constraint
        if self.step_type == Steps.STATION:
            self.settings.station.geo_constraint = geo_constraint


    # ====================
    # FILTERS
    # ====================
    def refresh_filters(self):
        """
        Renders Export settings for all stages and Import settings only for stage 1.

        - Allows users to download the current configuration (`config.cfg`) at all stages.
        - Shows the import settings section only when `stage == 1`.
        """        
        changes = self.settings.has_changed(self.old_settings)
        if changes.get('has_changed', False):
            self.old_settings      = deepcopy(self.settings)
            save_filter(self.settings)
            st.rerun()

    def event_filter(self):

        start_date, start_time = convert_to_datetime(self.settings.event.date_config.start_time)
        end_date, end_time     = convert_to_datetime(self.settings.event.date_config.end_time)

        with st.sidebar:
            with st.expander("### Filters", expanded=True):
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
                        self.settings.event.date_config.end_time, self.settings.event.date_config.start_time = get_time_interval('month')
                        st.rerun()
                with c12:
                    if st.button('Last Week', key="event-set-last-week"):
                        self.settings.event.date_config.end_time, self.settings.event.date_config.start_time = get_time_interval('week')
                        st.rerun()
                with c13:
                    if st.button('Last Day', key="event-set-last-day"):
                        self.settings.event.date_config.end_time, self.settings.event.date_config.start_time = get_time_interval('day')
                        st.rerun()


                c1, c2 = st.columns([1,1])

                with c1:
                    start_date  = st.date_input("Start Date", start_date, key="event-pg-start-date-event")
                    start_time  = st.time_input("Start Time (UTC)", start_time)
                    self.settings.event.date_config.start_time = datetime.combine(start_date, start_time)
                with c2:
                    end_date  = st.date_input("End Date", end_date, key="event-pg-end-date-event")
                    end_time  = st.time_input("End Time (UTC)", end_time)
                    self.settings.event.date_config.end_time = datetime.combine(end_date, end_time)

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
                    min_value=-5.0, max_value=800.0, 
                    value=(self.settings.event.min_depth, self.settings.event.max_depth), 
                    step=1.0, key="event-pg-depth"
                )

                self.render_map_buttons()

        self.refresh_filters()



    def station_filter(self):

        start_date, start_time = convert_to_datetime(self.settings.station.date_config.start_time)
        end_date, end_time = convert_to_datetime(self.settings.station.date_config.end_time)

        # One hour shift
        if (start_date == end_date and start_time >= end_time):
            start_time = time(hour=0, minute=0, second=0)
            end_time   = time(hour=1, minute=0, second=0)

        with st.sidebar:                
            with st.expander("### Filters", expanded=True):
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
                    if st.button('Last Month', key="station-set-last-month"):
                        self.settings.station.date_config.end_time, self.settings.station.date_config.start_time = get_time_interval('month')
                        st.rerun()
                with c12:
                    if st.button('Last Week', key="station-set-last-week"):
                        self.settings.station.date_config.end_time, self.settings.station.date_config.start_time = get_time_interval('week')
                        st.rerun()
                with c13:
                    if st.button('Last Day', key="station-set-last-day"):
                        self.settings.station.date_config.end_time, self.settings.station.date_config.start_time = get_time_interval('day')
                        st.rerun()

                c11, c12 = st.columns([1,1])
                with c11:
                    start_date = st.date_input("Start Date", value=start_date)
                    # start_time = st.time_input("Start Time (UTC)", value=start_time)
                    self.settings.station.date_config.start_time = datetime.combine(start_date, start_time)
                with c12:
                    end_date = st.date_input("End Date", value=end_date)
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
                    key="station-pg-highest-sample-rate"
                )
                
                self.settings.station.include_restricted = st.checkbox(
                    "Include Restricted Data", 
                    value=self.settings.station.include_restricted,  # Default to unchecked
                    key="event-pg-include-restricted-station"
                )

                

                self.settings.station.level = Levels.CHANNEL

                self.render_map_buttons()

        self.refresh_filters()

    # ====================
    # MAP
    # ====================   
    def set_map_view(self, map_center, map_zoom):
        self.map_view_center = map_center
        self.map_view_zoom   = map_zoom


    def update_filter_geometry(self, df, geo_type: GeoConstraintType, geo_constraint: List[GeometryConstraint]):
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
        """Check if min/max latitude and longitude values are valid."""
        return (-90 <= min_lat <= 90 and -90 <= max_lat <= 90 and
                -180 <= min_lon <= 180 and -180 <= max_lon <= 180 and
                min_lat <= max_lat and min_lon <= max_lon)

    def is_valid_circle(self, lat, lon, max_radius, min_radius):
        """Check if circle data is valid."""
        return (
            -90 <= lat <= 90 and
            -180 <= lon <= 180 and
            max_radius > 0 and
            min_radius >= 0 and
            min_radius <= max_radius
        )


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
                        "Invalid circle data detected. Ensure lat is between -90 and 90, lon is between -180 and 180, "
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
                    st.warning("Invalid rectangle coordinates detected. Ensure min_lat ≤ max_lat and min_lon ≤ max_lon, with values within valid ranges (-90 to 90 for lat, -180 to 180 for lon).")
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
            self.settings.event.selected_catalogs = Catalog(events=None)
            for i, event in enumerate(self.catalogs):
                if self.df_markers.loc[i, 'is_selected']:
                    if 'place' in self.df_markers.columns:
                        event.extra = {
                            'region': {
                                'value': self.df_markers.loc[i, 'place'],
                                'namespace': 'SEEDVAULT'
                            }
                        }
                    self.settings.event.selected_catalogs.append(event)

            return
        if self.step_type == Steps.STATION:
            self.settings.station.selected_invs = None
            is_init = False
            if not self.df_markers.empty and 'is_selected' in list(self.df_markers.columns):
                for idx, row in self.df_markers[self.df_markers['is_selected']].iterrows():
                    if not is_init:
                        self.settings.station.selected_invs = self.inventories.select(station=row["station"])
                        is_init = True
                    else:
                        self.settings.station.selected_invs += self.inventories.select(station=row["station"])
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
        geo_constraint = self.get_geo_constraint()

        if recreate_map:
            if self.map_output is not None and self.map_output.get("center"):
                self.map_view_center = self.map_output.get("center", {})
                self.map_view_zoom = self.map_output.get("zoom", 2)

            self.map_disp = create_map(
                map_id=self.map_id, 
                zoom_start=self.map_view_zoom,
                map_center=[
                    self.map_view_center.get("lat", 0.0),
                    self.map_view_center.get("lng", 175), # pacific ocean
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
                self.handle_get_data()


        if rerun:
            st.rerun()
    
    def reset_markers(self):
        self.map_fg_marker = None
        self.df_markers    = pd.DataFrame()
    # ====================
    # GET DATA
    # ====================


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

            # Extract HTTP error code if present
            match = re.search(r"Error (\d{3})", error_message)
            if match:
                http_status_code = int(match.group(1))

            # Lookup user-friendly error message
            user_friendly_message = http_error.get(http_status_code, "An error has occurred, please check parameters.")

            # Construct detailed error message
            self.has_error = True
            self.error = (
                f"{user_friendly_message}\n\n"
                f"**Technical details:**\n\n"
                f"Error: {error_message}"
            )

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
    
    def refresh_map_selection(self):
        selected_idx = self.get_selected_idx()
        self.update_selected_data()
        self.refresh_map(reset_areas=False, selected_idx=selected_idx, rerun=True, recreate_map=True)


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
                # st.dataframe(self.df_markers_prev, use_container_width=True)

    
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
            min_radius_str = st.text_input("Minimum radius (degree)", value="0")
        with c2:
            max_radius_str = st.text_input("Maximum radius (degree)", value="90")

        try:
            min_radius = float(min_radius_str)
            max_radius = float(max_radius_str)
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


            self.refresh_map(reset_areas=False, clear_draw=True)
            st.rerun()

    def update_area_around_prev_step_selections(self, min_radius, max_radius):
        min_radius_value = float(min_radius) # * 1000
        max_radius_value = float(max_radius) # * 1000

        updated_constraints = []

        geo_constraints = self.get_geo_constraint()

        for geo in geo_constraints:
            if geo.geo_type == GeoConstraintType.CIRCLE:
                lat, lon = geo.coords.lat, geo.coords.lon
                matching_event = self.df_markers_prev[(self.df_markers_prev['latitude'] == lat) & (self.df_markers_prev['longitude'] == lon)]

                if not matching_event.empty:
                    geo.coords.min_radius = min_radius_value
                    geo.coords.max_radius = max_radius_value
            updated_constraints.append(geo)

        for _, row in self.df_markers_prev.iterrows():
            lat, lon = row['latitude'], row['longitude']
            if not any(
                geo.geo_type == GeoConstraintType.CIRCLE and geo.coords.lat == lat and geo.coords.lon == lon
                for geo in updated_constraints
            ):
                new_donut = CircleArea(lat=lat, lon=lon, min_radius=min_radius_value, max_radius=max_radius_value)
                geo = GeometryConstraint(geo_type=GeoConstraintType.CIRCLE, coords=new_donut)
                updated_constraints.append(geo)

        updated_constraints = [
            geo for geo in updated_constraints
            if not (geo.geo_type == GeoConstraintType.CIRCLE and
                    self.df_markers_prev[
                        (self.df_markers_prev['latitude'] == geo.coords.lat) &
                        (self.df_markers_prev['longitude'] == geo.coords.lon)
                    ].empty)
        ]
        self.set_geo_constraint(updated_constraints)

    # ===================
    # FILES
    # ===================
    def exp_imp_events_stations(self):
        st.write(f"#### Export/Import {self.TXT.STEP.title()}s")

        c11, c22 = st.columns([1,1])
        with c11:
            # @NOTE: Download Selected had to be with the table.
            # if (len(self.catalogs.events) > 0 or len(self.inventories.get_contents().get('stations')) > 0):
            st.download_button(
                f"Download All", 
                key=self.get_key_element(f"Download All {self.TXT.STEP.title()}s"),
                data=self.export_xml_bytes(export_selected=False),
                file_name = f"{self.TXT.STEP}s.xml",
                mime="application/xml",
                disabled=(len(self.catalogs.events) == 0 and (self.inventories is None or len(self.inventories.get_contents().get('stations')) == 0))
            )

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
                        cat.write(f, format="QUAKEML")

            # if f.getbuffer().nbytes == 0:
            #     f.write(b"No Data")     

            return f.getvalue()
        

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
        if self.all_current_drawings != all_drawings:
            self.all_current_drawings = all_drawings
            self.refresh_map(rerun=True, get_data=True)



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
                # self.clear_all_data()
                # self.refresh_map(reset_areas=True, clear_draw=True, rerun=True, get_data=True)


        with cc2:
            if st.button(self.TXT.CLEAR_ALL_MAP_DATA, key=self.get_key_element(self.TXT.CLEAR_ALL_MAP_DATA)):
                self.clear_all_data()
                self.refresh_map(reset_areas=True, clear_draw=True, rerun=True, get_data=False)

        
        with cc3:
            if st.button(
                "Reload", 
                # help="Use Reload button if the map is collapsed or some layers are missing.",
                key=self.get_key_element(f"ReLoad {self.TXT.STEP}s")
            ):
                self.refresh_map(get_data=False, rerun=True, recreate_map=True)

        

    
    def render_map_handles(self):
        # not sure if plotting these area tables is useful
        with st.expander("Shape tools - edit areas", expanded=True):
            self.update_rectangle_areas()
            self.update_circle_areas()
        # self.render_map_buttons()
        

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
                        use_container_width=True,
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
        if self.prev_step_type:
            with st.expander(f"Search Around {self.prev_step_type.title()}s", expanded=True):
                self.display_prev_step_selection_table() 

    def render_map(self):
        if self.map_disp is not None:
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
                use_container_width=True, 
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

        # st.write(self.map_output)
        if self.map_output and self.map_output.get('last_object_clicked') is not None:
            last_clicked = self.map_output['last_object_clicked_popup']

            if isinstance(last_clicked, str):
                idx_info = last_clicked.splitlines()[-1].split()
                step = idx_info[0].lower()
                idx  = int(idx_info[1])
                if step == self.step_type:
                    self.clicked_marker_info = self.marker_info[idx]
                
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
        ordered_col = ['is_selected'] + orig_cols

        # Define config
        config = {col: {'disabled': True} for col in orig_cols}
        config['is_selected'] = st.column_config.CheckboxColumn('Select')

        state_key = f'initial_df_markers_{self.stage}'

        # Store the initial state in the session if not already stored
        if  state_key not in st.session_state:
            st.session_state[state_key] = self.df_markers.copy()

        self.data_table_view(ordered_col, config, state_key)


        # Download button logic
        is_disabled = 'is_selected' not in self.df_markers or self.df_markers['is_selected'].sum() == 0

        with c5_map:
            st.download_button(
                f"Download Selected",
                key=self.get_key_element(f"Download Selected {self.TXT.STEP.title()}s"),
                data=self.export_xml_bytes(export_selected=True),
                file_name=f"{self.TXT.STEP}s_selected.xml",
                mime="application/xml",
                disabled=is_disabled
            )

    def data_table_view(self, ordered_col, config, state_key):
        """Displays the full data table, allowing selection."""

        # Add custom CSS to ensure full width and remove scrollbars
        st.markdown("""
            <style>
                .element-container {
                    width: 100% !important;
                }
                .stDataFrame {
                    width: 100% !important;
                    text-align: center !important;                    
                }
                .data-editor-container {
                    width: 100% !important;
                }
                [data-testid="stDataFrame"] {
                    width: 100% !important;                 
                }
                div[data-testid="stDataFrame"] > div {
                    width: 100% !important;                  
                }
                div[data-testid="stDataFrame"] > div > iframe {
                    width: 100% !important;
                    text-align: center !important;                    
                    min-height: calc(100vh - 300px);  # Adjust this value as needed
                }                   
            </style>
        """, unsafe_allow_html=True)  

        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            st.write(f"Total Number of {self.TXT.STEP.title()}s: {len(self.df_markers)}")
                
        with c2:
            if st.button("Select All", key=self.get_key_element("Select All")):
                self.df_markers['is_selected'] = True

        with c3:
            if st.button("Unselect All", key=self.get_key_element("Unselect All")):
                self.df_markers['is_selected'] = False
        
        # it would be prettier to merge "magnitude_type" with magnitude here.. TODO

        self.selected_items_view(state_key) 

        # Set the height based on the number of rows (with a minimum and maximum)
        num_rows = len(self.df_markers)
        height = max(min(num_rows * 35 + 100, 800), 400)  # Adjust as needed

        # Define desired column widths in pts
        column_widths = {
            "Select": 60,
            "network": 60,
            "station": 80,
            "elevation": 80,
            "longitude": 130,
            "latitude": 130,
            "start_date": 140,
            "end_date": 140
            }

        for col in ordered_col:
            
            # Add width if this column should have a specific width
            if col in column_widths:
                config[col] = st.column_config.Column(
                    col,
                    width=column_widths[col]
                )
            else:
                config[col] = st.column_config.Column(
                    col,
                )

        self.df_data_edit = st.data_editor(
            self.df_markers, 
            hide_index = True, 
            column_config=config, 
            column_order = ordered_col, 
            key=self.get_key_element("Data Table"),
            height=height,
            use_container_width=True
        )
        

        if len(self.df_data_edit) != len(st.session_state[state_key]):
            has_changed = True
        else:
            has_changed = not self.df_data_edit.equals(st.session_state[state_key])
            
            if has_changed:
                df_sorted_new = self.df_data_edit.sort_values(by=self.df_data_edit.columns.tolist()).reset_index(drop=True)
                df_sorted_old = st.session_state[state_key].sort_values(by=st.session_state[state_key].columns.tolist()).reset_index(drop=True)
                has_changed = not df_sorted_new.equals(df_sorted_old)

        if has_changed:
            st.session_state[state_key] = self.df_data_edit.copy()  # Save the unsorted version to preserve user sorting
            self.sync_df_markers_with_df_edit()
            self.refresh_map_selection()

    def selected_items_view(self, state_key):
        """Displays selected items using an actual `st.multiselect`, controlled by table selection."""

        df_selected = self.df_markers[self.df_markers['is_selected']].copy()

        if df_selected.empty:
            return

        if self.step_type == Steps.EVENT:
            preferred_column = "place"
            unique_column = "magnitude"  # Extra column to make each entry unique

        if self.step_type == Steps.STATION:
            preferred_column = "network"
            unique_column = "station"  # Extra column to make each entry unique

        ## causing issue in STATION table which doesn't have "magnitude" (NEEDS REVIEW)
        if preferred_column not in df_selected.columns or unique_column not in df_selected.columns:
            st.warning(f"Column '{preferred_column}' or '{unique_column}' not found in the data!")
            return

        df_selected["display_label"] = df_selected[preferred_column] + " (" + df_selected[unique_column].astype(str) + ")"
        
        selected_items = df_selected["display_label"].tolist()

        updated_selection = st.multiselect(
            "Selected Items",
            options=self.df_markers[self.df_markers['is_selected']].apply(lambda x: f"{x[preferred_column]} ({x[unique_column]})", axis=1).tolist(),
            default=selected_items,
            key="selected_items_list",
            placeholder="Selected Items",
            disabled=False
        )

        removed_items = set(selected_items) - set(updated_selection)

        if removed_items:
            for item in removed_items:
                place_name, magnitude = item.rsplit(" (", 1)
                magnitude = magnitude.rstrip(")")  # Remove closing bracket

                item_index = self.df_markers[
                    (self.df_markers[preferred_column] == place_name) & 
                    (self.df_markers[unique_column].astype(str) == magnitude)
                ].index.tolist()

                if item_index:
                    self.df_markers.at[item_index[0], 'is_selected'] = False  
                    # self.sync_df_markers_with_df_edit()

            st.session_state[state_key] = self.df_markers.copy()
            self.refresh_map_selection()

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

        if not self.df_markers.empty:
            self.render_marker_select()
            with st.expander(self.TXT.SELECT_DATA_TABLE_TITLE, expanded = not self.df_markers.empty):
                self.render_data_table(c2_export)

    



