# seed_vault/ui/components/continuous_waveform.py

from typing import List
import streamlit as st
from datetime import datetime
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_continuous
from seed_vault.ui.components.display_log import ConsoleDisplay
from seed_vault.service.utils import convert_to_datetime, get_time_interval

class ContinuousFilterMenu:
    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        
    def render(self):
        st.sidebar.title("Continuous Waveform Information")
        
        with st.sidebar.expander("Time Selection", expanded=True):
            start_date, start_time = convert_to_datetime(self.settings.station.date_config.start_time)
            end_date, end_time = convert_to_datetime(self.settings.station.date_config.end_time)

            c11, c12 = st.columns([1,1])
            c21, c22 = st.columns([1,1])
            with c11:
                if st.button('Last Month', key="station-set-last-month"):
                    self.settings.station.date_config.end_time, self.settings.station.date_config.start_time = get_time_interval('month')
                    st.rerun()
            with c12:
                if st.button('Last Week', key="station-set-last-week"):
                    self.settings.station.date_config.end_time, self.settings.station.date_config.start_time = get_time_interval('week')
                    st.rerun()
            with c21:
                if st.button('Last Day', key="station-set-last-day"):
                    self.settings.station.date_config.end_time, self.settings.station.date_config.start_time = get_time_interval('day')
                    st.rerun()
            with c22:
                if st.button('Last Hour', key="station-set-last-hour"):
                    self.settings.station.date_config.end_time, self.settings.station.date_config.start_time = get_time_interval('hour')
                    st.rerun()

            c1,c2 = st.columns([1,1])
            with c1:
                start_date = st.date_input("Start Date", value=start_date)
                start_time = st.time_input("Start Time (UTC)", value=start_time)
                self.settings.station.date_config.start_time = datetime.combine(start_date, start_time)
            with c2:
                end_date = st.date_input("End Date", value=end_date)                
                end_time = st.time_input("End Time (UTC)", value=end_time)
                self.settings.station.date_config.end_time = datetime.combine(end_date, end_time)

            
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