from seed_vault.ui.components.waveform import WaveformComponents
import streamlit as st
import plotly.express as px
import pandas as pd

from seed_vault.enums.ui import Steps
from seed_vault.models.config import SeismoLoaderSettings, DownloadType

from seed_vault.ui.components.base import BaseComponent

from seed_vault.service.seismoloader import run_event

download_options = [f.name.title() for f in DownloadType]


class EventBasedWorkflow:

    settings: SeismoLoaderSettings
    stage: int = 1
    event_components: BaseComponent
    station_components: BaseComponent
    waveform_components: WaveformComponents

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.event_components = BaseComponent(self.settings, step_type=Steps.EVENT, prev_step_type=None, stage=1)    
        self.station_components = BaseComponent(self.settings, step_type=Steps.STATION, prev_step_type=Steps.EVENT, stage=2)    
        self.waveform_components = WaveformComponents(self.settings)
    def next_stage(self):
        self.stage += 1
        st.rerun()

    def previous_stage(self):
        self.stage -= 1
        st.rerun()

    def render(self):
        if self.stage == 1:
            c1, c2, c3 = st.columns([1, 1, 1])        
            with c2:
                st.subheader("Step 1: Select Events")
            with c1:
                if st.button("Next"):
                    self.event_components.sync_df_markers_with_df_edit()
                    self.event_components.update_selected_data()
                    if len(self.event_components.settings.event.selected_catalogs)>0 :                    
                        self.next_stage()   
                    else :
                        st.error("Please select an event to proceed to the next step.")
            self.event_components.render()

        if self.stage == 2:            
            c1, c2, c3 = st.columns([1, 1, 1])
            with c3:
                if st.button("Next"):
                    self.station_components.sync_df_markers_with_df_edit()
                    self.station_components.update_selected_data()
                    if len(self.station_components.settings.station.selected_invs)>0 :                    
                        self.next_stage()   
                    else :
                        st.error("Please select a station to proceed to the next step.")
            with c2:
                st.write("### Step 2: Select Stations")
            with c1:
                if st.button("Previous"):
                    selected_idx = self.event_components.get_selected_idx()
                    self.event_components.refresh_map(selected_idx=selected_idx,clear_draw=True)
                    self.previous_stage() 
            self.station_components.render()

        if self.stage == 3:
            c1, c2, c3 = st.columns([1, 1, 1])
            with c2:
                st.write("### Step 3: Waveforms")
            with c1:
                if st.button("Previous"):
                    selected_idx = self.station_components.get_selected_idx()
                    self.station_components.refresh_map(selected_idx=selected_idx,clear_draw=True)
                    self.previous_stage()
            self.waveform_components.render()



class StationBasedWorkflow:

    settings: SeismoLoaderSettings
    stage: int = 1
    event_components: BaseComponent
    station_components: BaseComponent
    waveform_components: WaveformComponents


    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings   
        self.station_components = BaseComponent(self.settings, step_type=Steps.STATION, prev_step_type=None, stage=1)   
        self.event_components = BaseComponent(self.settings, step_type=Steps.EVENT, prev_step_type=Steps.STATION, stage=2)  
        self.waveform_components = WaveformComponents(self.settings)

    def next_stage(self):
        if self.settings.download_type == DownloadType.EVENT:
            self.stage += 1        
            st.rerun()
        if self.settings.download_type == DownloadType.CONTINUOUS:
            self.stage += 2       
            st.rerun()

    def previous_stage(self):
        if self.settings.download_type == DownloadType.EVENT:
            self.stage -= 1        
            st.rerun()
        if self.settings.download_type == DownloadType.CONTINUOUS:
            self.stage -= 2       
            st.rerun()

    def render(self):
        if self.stage == 1:
            c1, c2, c3 = st.columns([1, 1, 1])        
            with c2:
                st.subheader("Step 1: Select Stations")
            with c1:
                if st.button("Next"):
                    self.station_components.sync_df_markers_with_df_edit()
                    self.station_components.update_selected_data()
                    if len(self.station_components.settings.station.selected_invs)>0 :               
                        self.next_stage()   
                    else :
                        st.error("Please select a station to proceed to the next step.")

            with c3:
                selected_download_type = st.selectbox('Download Type:', download_options, index=download_options.index(self.settings.download_type.name.title()), key="station-pg-download-type")
                self.settings.download_type = DownloadType[selected_download_type.upper()]
                    
            self.station_components.render()

        if self.stage == 2:            
            c1, c2, c3 = st.columns([1, 1, 1])
            with c3:
                if st.button("Next"):
                    self.event_components.sync_df_markers_with_df_edit()
                    self.event_components.update_selected_data()
                    if len(self.event_components.settings.event.selected_catalogs)>0 :                    
                        self.next_stage()   
                    else :
                        st.error("Please select an event to proceed to the next step.")
            with c2:
                st.write("### Step 2: Select Events")
            with c1:
                if st.button("Previous"):
                    selected_idx = self.station_components.get_selected_idx()
                    self.station_components.refresh_map(selected_idx=selected_idx,clear_draw=True)
                    self.previous_stage() 
            self.event_components.render()

        if self.stage == 3:
            c1, c2, c3 = st.columns([1, 1, 1])
            with c2:
                st.write("### Step 3: Waveforms")
            with c1:
                if st.button("Previous"):
                    selected_idx = self.station_components.get_selected_idx()
                    self.station_components.refresh_map(selected_idx=selected_idx,clear_draw=True)
                    self.previous_stage()
            if self.settings.download_type == DownloadType.CONTINUOUS:
                st.write("# Waveform for Continuous not implemented!")

            if self.settings.download_type == DownloadType.EVENT:
                
                self.waveform_components.render()


