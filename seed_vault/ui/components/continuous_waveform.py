# seed_vault/ui/components/continuous_waveform.py

from typing import List
import streamlit as st
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_continuous
from seed_vault.ui.components.display_log import ConsoleDisplay

class ContinuousFilterMenu:
    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        
    def render(self):
        st.sidebar.title("Continuous Waveform Information")
        
        with st.sidebar.expander("Time Selection", expanded=True):
            self.settings.station.date_config.start_time = st.date_input(
                "Start Time",
                value=self.settings.station.date_config.start_time
            )
            self.settings.station.date_config.end_time = st.date_input(
                "End Time",
                value=self.settings.station.date_config.end_time
            )
            
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
            # No need to set values as they're already in settings
            return run_continuous(self.settings)
            
        return self.console.run_with_logs(
            process_func=process_func,
            status_message="Downloading continuous waveform data..."
        )
        
    def render(self):
        st.title("Continuous Waveform Processing")
        
        if st.button("Download Waveforms", key="download_continuous"):
            success = self.process_continuous_data()
            if success:
                st.success("Continuous data processing completed successfully!")
            else:
                st.error("Error processing continuous data. Check the logs for details.")

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