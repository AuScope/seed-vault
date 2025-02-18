# seed_vault/ui/components/continuous_waveform.py

from typing import List
import streamlit as st
from datetime import datetime
from copy import deepcopy
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_continuous
from seed_vault.ui.components.display_log import ConsoleDisplay
from seed_vault.service.utils import convert_to_datetime, get_time_interval
from seed_vault.ui.pages.helpers.common import save_filter

class ContinuousFilterMenu:
    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.old_settings = deepcopy(settings)
        # Track previous time state
        self.old_time_state = {
            'start_time': self.settings.station.date_config.start_time,
            'end_time': self.settings.station.date_config.end_time
        }

    def refresh_filters(self):
        """Check for changes and trigger updates"""
        current_time_state = {
            'start_time': self.settings.station.date_config.start_time,
            'end_time': self.settings.station.date_config.end_time
        }
        
        # Check if time state changed
        if current_time_state != self.old_time_state:
            self.old_time_state = current_time_state.copy()
            save_filter(self.settings)
            st.rerun()

        # Check if settings changed
        changes = self.settings.has_changed(self.old_settings)
        if changes.get('has_changed', False):
            self.old_settings = deepcopy(self.settings)
            save_filter(self.settings)
            st.rerun()
        
    def render(self):
        st.sidebar.title("Continuous Waveform Information")
        
        with st.sidebar.expander("Time Selection", expanded=True):
            start_date, start_time = convert_to_datetime(self.settings.station.date_config.start_time)
            end_date, end_time = convert_to_datetime(self.settings.station.date_config.end_time)

            c11, c12 = st.columns([1,1])
            c21, c22 = st.columns([1,1])
            with c11:
                if st.button('Last Month', key="station-set-last-month"):
                    end_time, start_time = get_time_interval('month')
                    self.settings.station.date_config.end_time = end_time
                    self.settings.station.date_config.start_time = start_time
                    self.refresh_filters()

            with c12:
                if st.button('Last Week', key="station-set-last-week"):
                    end_time, start_time = get_time_interval('week')
                    self.settings.station.date_config.end_time = end_time
                    self.settings.station.date_config.start_time = start_time
                    self.refresh_filters()

            with c21:
                if st.button('Last Day', key="station-set-last-day"):
                    end_time, start_time = get_time_interval('day')
                    self.settings.station.date_config.end_time = end_time
                    self.settings.station.date_config.start_time = start_time
                    self.refresh_filters()

            with c22:
                if st.button('Last Hour', key="station-set-last-hour"):
                    end_time, start_time = get_time_interval('hour')
                    self.settings.station.date_config.end_time = end_time
                    self.settings.station.date_config.start_time = start_time
                    self.refresh_filters()

            c1, c2 = st.columns([1,1])
            with c1:
                new_start_date = st.date_input("Start Date", value=start_date)
                new_start_time = st.time_input("Start Time (UTC)", value=start_time)
                new_start = datetime.combine(new_start_date, new_start_time)
                if new_start != self.settings.station.date_config.start_time:
                    self.settings.station.date_config.start_time = new_start
                    self.refresh_filters()

            with c2:
                new_end_date = st.date_input("End Date", value=end_date)                
                new_end_time = st.time_input("End Time (UTC)", value=end_time)
                new_end = datetime.combine(new_end_date, new_end_time)
                if new_end != self.settings.station.date_config.end_time:
                    self.settings.station.date_config.end_time = new_end
                    self.refresh_filters()

            
        with st.sidebar.expander("Waveform Details", expanded=True):
            # Display the current values instead of input fields
            st.text("Network:")
            st.code(self.settings.station.network)
            
            st.text("Station:")
            st.code(self.settings.station.station)
            
            st.text("Location:")
            st.code(self.settings.station.location)
            
            st.text("Channel:")
            st.code(self.settings.station.channel)

class ContinuousDisplay:
    def __init__(self, settings: SeismoLoaderSettings, filter_menu: ContinuousFilterMenu):
        self.settings = settings
        self.filter_menu = filter_menu
        self.console = ConsoleDisplay()
        
    def process_continuous_data(self):
        """Process continuous data with console output"""
        def process_func():
            return run_continuous(self.settings)
            
        success, error_message = self.console.run_with_logs(
            process_func=process_func,
            status_message="Downloading continuous waveform data..."
        )
        return success, error_message
        
    def render(self):
        st.title("Continuous Waveform Processing")
        
        if st.button("Download Waveforms", key="download_continuous"):
            success, error_message = self.process_continuous_data()
            if success:
                st.success("Continuous data processing completed successfully!")
            else:
                st.error(f"Error processing continuous data: {error_message}")

class ContinuousComponents:
    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.filter_menu = ContinuousFilterMenu(settings)
        self.display = ContinuousDisplay(settings, self.filter_menu)
        
    def render(self):
        # Render filter menu in sidebar
        self.filter_menu.render()
        # Render main display
        self.display.render()