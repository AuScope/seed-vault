from typing import List, Dict, Union
from obspy import Stream
from obspy import UTCDateTime
import threading
from seed_vault.enums.config import WorkflowType
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_event
from obspy.clients.fdsn import Client
from obspy.taup import TauPyModel
from seed_vault.ui.components.display_log import ConsoleDisplay
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from html import escape
from seed_vault.ui.components.continuous_waveform import ContinuousComponents
from seed_vault.service.utils import check_client_services
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from seed_vault.ui.pages.helpers.common import save_filter
import time



query_thread = None
stop_event = threading.Event()


if "query_done" not in st.session_state:
    st.session_state["query_done"] = False
if "trigger_rerun" not in st.session_state:
    st.session_state["trigger_rerun"] = False

def get_tele_filter(tr):
    # get a generic teleseismic filter band
    distance_km = tr.stats.distance_km
    nyq = tr.stats.sampling_rate/2 - 0.1
    senstype = tr.stats.channel[1]

    if senstype not in ['H','N']:
        return 0,0 # flagged elsewhere

    if distance_km < 100:
        f0,f1 = 2.0,15
    elif distance_km < 500:
        f0,f1 = 1.8,8
    elif distance_km < 3000:
        f0,f1 = 1.4,5
    elif distance_km < 10000:
        f0,f1 = 1.0,3
    else:
        f0,f1 = 0.7,2
    
    return min(f0,nyq),min(f1,nyq)

class WaveformFilterMenu:
    settings: SeismoLoaderSettings
    network_filter: str
    station_filter: str
    channel_filter: str
    available_channels: List[str]
    display_limit: int

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.old_settings = deepcopy(settings)  # Track previous state
        self.network_filter = "All networks"
        self.station_filter = "All stations"
        self.channel_filter = "All channels"
        self.available_channels = ["All channels"]
        self.display_limit = 50
        # Track previous filter state
        self.old_filter_state = {
            'network_filter': self.network_filter,
            'station_filter': self.station_filter,
            'channel_filter': self.channel_filter,
            'display_limit': self.display_limit
        }

    def refresh_filters(self):
        """Check for changes and trigger updates"""
        current_state = {
            'network_filter': self.network_filter,
            'station_filter': self.station_filter,
            'channel_filter': self.channel_filter,
            'display_limit': self.display_limit
        }
        
        # Check if filter state changed
        if current_state != self.old_filter_state:
            self.old_filter_state = current_state.copy()
            st.rerun()

        # Check if settings changed
        changes = self.settings.has_changed(self.old_settings)
        if changes.get('has_changed', False):
            self.old_settings = deepcopy(self.settings)
            save_filter(self.settings)
            st.rerun()

    def update_available_channels(self, stream: Stream):
        if not stream:
            self.available_channels = ["All channels"]
            return
            
        channels = set()
        for tr in stream:
            channels.add(tr.stats.channel)
        self.available_channels = ["All channels"] + sorted(list(channels))
        
        # Reset channel filter if current selection is invalid
        if self.channel_filter not in self.available_channels:
            self.channel_filter = "All channels"
    
    def render(self, stream=None):
        st.sidebar.title("Waveform Controls")
        

        # Step 1: Data Retrieval Settings
        with st.sidebar.expander("Step 1: Data Source", expanded=True):
            st.subheader("🔍 Time Window")
            
            # Update time window settings with immediate refresh
            before_p = st.number_input(
                "Start (secs before P arrival):", 
                value=self.settings.event.before_p_sec or 20,
                help="Time window before P arrival",
                key="before_p_input"
            )
            if before_p != self.settings.event.before_p_sec:
                self.settings.event.before_p_sec = before_p
                self.refresh_filters()

            after_p = st.number_input(
                "End (secs after P arrival):", 
                value=self.settings.event.after_p_sec or 100,
                help="Time window after P arrival",
                key="after_p_input"
            )
            if after_p != self.settings.event.after_p_sec:
                self.settings.event.after_p_sec = after_p
                self.refresh_filters()

            # Client selection with immediate refresh
            client_options = list(self.settings.client_url_mapping.get_clients())
            selected_client = st.selectbox(
                'Choose a client:', 
                client_options,
                index=client_options.index(self.settings.waveform.client),
                key="waveform_client_select"
            )
            if selected_client != self.settings.waveform.client:
                self.settings.waveform.client = selected_client
                self.refresh_filters()

            # Check services for selected client
            services = check_client_services(self.settings.waveform.client)
            if not services['dataselect']:
                st.warning(f"⚠️ Warning: Selected client '{self.settings.waveform.client}' does not support WAVEFORM service. Please choose another client.")

            # Add Download Preferences section
            st.subheader("📊 Download Preferences")
            
            # Channel Priority Input
            channel_pref = st.text_input(
                "Channel Priority",
                value=self.settings.waveform.channel_pref,
                help="Order of preferred channels (e.g., HH,BH,EH). Only the first existing channel in this list will be downloaded.",
                key="channel_pref"
            )
            
            # Validate and update channel preferences
            if channel_pref:
                # Remove spaces and convert to uppercase
                channel_pref = channel_pref.replace(" ", "").upper()
                # Basic validation
                channel_codes = channel_pref.split(",")
                is_valid = all(len(code) == 2 for code in channel_codes)
                if is_valid:
                    self.settings.waveform.channel_pref = channel_pref
                else:
                    st.error("Invalid channel format. Each channel code should be 2 characters (e.g., HH,BH,EH)")

            # Location Priority Input
            location_pref = st.text_input(
                "Location Priority",
                value=self.settings.waveform.location_pref,
                help="Order of preferred location codes (e.g., 00,--,10,20). Only the first existing location code in this list will be downloaded.. Use -- or '' for blank location.",
                key="location_pref"
            )
            
            # Validate and update location preferences
            if location_pref:
                # Remove spaces
                location_pref = location_pref.replace(" ", "")
                # Basic validation
                location_codes = location_pref.split(",")
                is_valid = all(len(code) <= 2 for code in location_codes)
                if is_valid:
                    self.settings.waveform.location_pref = location_pref
                else:
                    st.error("Invalid location format. Each location code should be 0-2 characters (e.g., 00,--,10,20)")

            if stream is not None:
                networks = ["All networks"] + list(set([inv.code for inv in self.settings.station.selected_invs]))
                selected_network = st.selectbox(
                    "Network:",
                    networks,
                    index=networks.index(self.network_filter),
                    help="Filter by network",
                    key="network_filter_select"
                )
                if selected_network != self.network_filter:
                    self.network_filter = selected_network
                    self.refresh_filters()

                # Station filter with immediate refresh
                stations = ["All stations"]
                for inv in self.settings.station.selected_invs:
                    stations.extend([sta.code for sta in inv])
                stations = list(dict.fromkeys(stations))  # Remove duplicates
                stations.sort()
                
                selected_station = st.selectbox(
                    "Station:",
                    stations,
                    index=stations.index(self.station_filter),
                    help="Filter by station",
                    key="station_filter_select"
                )
                if selected_station != self.station_filter:
                    self.station_filter = selected_station
                    self.refresh_filters()

                # Channel filter with immediate refresh
                self.channel_filter = st.selectbox(
                    "Channel:",
                    options=self.available_channels,
                    index=self.available_channels.index(self.channel_filter),
                    help="Filter by channel",
                    key="channel_filter_select"
                )
                if self.channel_filter != self.old_filter_state['channel_filter']:
                    self.old_filter_state['channel_filter'] = self.channel_filter
                    self.refresh_filters()

                st.subheader("📊 Display Options")
                display_limit = st.selectbox(
                    "Waveforms per page:",
                    options=[10, 25, 50],
                    index=[10, 25, 50].index(self.display_limit),
                    key="waveform_display_limit",
                    help="Number of waveforms to show per page"
                )
                if display_limit != self.display_limit:
                    self.display_limit = display_limit
                    self.refresh_filters()
                
                # Add status information
                if stream:
                    st.sidebar.info(f"Total waveforms: {len(stream)}")
                    
                # Add reset filters button
                if st.sidebar.button("Reset Filters"):
                    self.network_filter = "All networks"
                    self.station_filter = "All stations"
                    self.channel_filter = "All channels"
                    self.display_limit = 50
                    self.refresh_filters()

class WaveformDisplay:
    def __init__(self, settings: SeismoLoaderSettings, filter_menu: WaveformFilterMenu):
        self.settings = settings
        self.filter_menu = filter_menu
        
        try:
            self.client = Client(self.settings.waveform.client)
        except ValueError as e:
            st.error(f"Error: {str(e)} Waveform client is set to {self.settings.waveform.client}, which seems does not exists. Please navigate to the settings page and use the Clients tab to add the client or fix the stored config.cfg file.")
        self.ttmodel = TauPyModel("iasp91")
        self.streams = []
        self.missing_data = {}
        self.console = ConsoleDisplay()  # Add console display
        self.missing_data = {}

    def apply_filters(self, stream) -> Stream:
        """Filter stream based on user selection"""
        filtered_stream = Stream()
        
        # Handle case where stream is a list of traces
        if isinstance(stream, list):
            stream = Stream(traces=stream)
        
        if not stream:
            return filtered_stream
        
        for tr in stream:
            try:
                if (self.filter_menu.network_filter == "All networks" or 
                    tr.stats.network == self.filter_menu.network_filter) and \
                   (self.filter_menu.station_filter == "All stations" or 
                    tr.stats.station == self.filter_menu.station_filter) and \
                   (self.filter_menu.channel_filter == "All channels" or 
                    tr.stats.channel == self.filter_menu.channel_filter):
                    filtered_stream += tr
            except AttributeError as e:
                continue
        return filtered_stream
    

    def fetch_data(self):
        """
        Fetches waveform data in a background thread with logging.
        """        
        # Capture stdout/stderr for logging
        with redirect_stdout(StringIO()) as stdout, redirect_stderr(StringIO()) as stderr:
            try:
                # Update to unpack the tuple returned by run_event
                streams_and_missing = run_event(self.settings, stop_event)
                if streams_and_missing:
                    self.streams, self.missing_data = streams_and_missing
                    success = True
                else:
                    success = False
            except Exception as e:
                success = False
                print(f"Error: {str(e)}")  # This will be captured in the output
            
            # Capture output for logs
            output = stdout.getvalue() + stderr.getvalue()
            if output:
                self.console.accumulated_output = output.splitlines()

        st.session_state.update({
            "query_done": True,
            "is_downloading": False,
            "trigger_rerun": True
        })

    def retrieve_waveforms(self):
        """
        Initiates waveform retrieval in a background thread with cancellation support
        """
        if not self.settings.event.selected_catalogs or not self.settings.station.selected_invs:
            st.warning("Please select events and stations before downloading waveforms.")
            return

        stop_event.clear()  # Reset cancellation flag
        st.session_state["query_thread"] = threading.Thread(target=self.fetch_data, daemon=True)
        st.session_state["query_thread"].start()

        st.session_state.update({
            "is_downloading": True,
            "query_done": False,
            "polling_active": True
        })

        st.rerun()

    def _get_trace_color(self, tr) -> str:
        """Get color based on channel component"""
        # Extract last character of channel code
        component = tr.stats.channel[-1].upper()
        sensortype = tr.stats.channel[1].upper()

        if sensortype not in ['H','N']:
            return 'tomato'
        
        # Standard color scheme for components
        if component == 'Z':
            return 'black'
        elif component in ['N', '1']:
            return 'blue'
        elif component in ['E', '2']:
            return 'green'
        else:
            return 'gray'

    def _plot_stream_with_colors(self, stream: Stream, size=(800, 600), view_type=None):
        """Plot stream with proper time windows and P markers"""
        if not stream:
            return None

        try:
            # Create figure with subplots
            num_traces = len(stream)
            fig, axes = plt.subplots(num_traces, 1, figsize=(size[0]/100, size[1]/100), sharex=True)
            if num_traces == 1:
                axes = [axes]

            # Sort stream by distance
            stream.traces.sort(key=lambda x: x.stats.starttime)
            
            # Process each trace
            for i, tr in enumerate(stream):
                ax = axes[i]

                # Calculate and add an appropriate filter for plotting              
                filter_min,filter_max = get_tele_filter(tr)
                if filter_min < filter_max:
                    tr.stats.filterband = (filter_min,filter_max)

                if view_type == "station":
                    if hasattr(tr.stats, 'p_arrival') and hasattr(tr.stats, 'event_time'):
                        p_time = UTCDateTime(tr.stats.p_arrival)
                        before_p = self.settings.event.before_p_sec
                        after_p = self.settings.event.after_p_sec
                        
                        # Trim trace to desired window around P
                        window_start = p_time - before_p
                        window_end = p_time + after_p
                        tr_windowed = tr.slice(window_start, window_end)

                        # Pre-process and apply a bandpass filter
                        if tr_windowed.stats.sampling_rate/2 > filter_min and filter_min<filter_max:
                            tr_windowed.detrend()
                            tr_windowed.taper(.005)
                            tr_windowed.filter('bandpass',freqmin=filter_min,freqmax=filter_max,
                                zerophase=True)
                        
                        # Calculate times relative to P arrival
                        times = np.arange(tr_windowed.stats.npts) * tr_windowed.stats.delta
                        relative_times = times - before_p  # This makes P arrival at t=0
                        
                        # Plot the trace
                        ax.plot(relative_times, tr_windowed.data, '-', 
                               color=self._get_trace_color(tr), linewidth=0.8)
                        
                        # Add P arrival line (now at x=0)
                        ax.axvline(x=0, color='red', linewidth=1, linestyle='-')
                        
                        # Format trace label
                        station_label = f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location or ''}.{tr.stats.channel}"
                        event_info = ""
                        if hasattr(tr.stats, 'distance_km'):
                            event_info += f"{tr.stats.distance_km:.1f} km"
                        if hasattr(tr.stats, 'event_magnitude'):
                            event_info += f", M{tr.stats.event_magnitude:.1f}"
                        if hasattr(tr.stats, 'event_region'):
                            event_info += f", {tr.stats.event_region}"
                        if hasattr(tr.stats, 'filterband'):
                            event_info += f", {tr.stats.filterband[0]}-{tr.stats.filterband[1]}Hz"
                        
                        # Position label inside plot in upper left
                        label = f"{station_label} - {event_info}"
                        ax.text(0.02, 0.95, label, 
                               transform=ax.transAxes,
                               verticalalignment='top',
                               fontsize=8)
                        
                        # Set consistent x-axis limits
                        ax.set_xlim(-before_p, after_p)
                        
                else:
                    # Original plotting logic for other views
                    # Get P arrival time
                    p_time = UTCDateTime(tr.stats.p_arrival) if hasattr(tr.stats, 'p_arrival') else None
                    
                    if p_time:
                        # Calculate window boundaries
                        start_time = p_time - self.settings.event.before_p_sec
                        end_time = p_time + self.settings.event.after_p_sec
                        
                        # Ensure trace is trimmed to window
                        tr.trim(start_time, end_time, pad=True, fill_value=0)

                        # Pre-process and apply a bandpass filter
                        if tr_windowed.stats.sampling_rate/2 > filter_min and filter_min<filter_max:
                            tr.detrend()
                            tr.taper(.005)
                            tr.filter('bandpass',freqmin=filter_min,freqmax=filter_max,
                                zerophase=True)
                        
                        # Create time vector matching data length
                        times = np.linspace(-self.settings.event.before_p_sec, 
                                          self.settings.event.after_p_sec,
                                          len(tr.data))
                        
                        # Plot waveform
                        ax.plot(times, tr.data, '-', color=self._get_trace_color(tr), linewidth=0.8)
                        
                        # Add P marker at t=0
                        ax.axvline(x=0, color='red', linewidth=1, linestyle='-')
                        ax.text(0, ax.get_ylim()[1], 'P', color='red', fontsize=8,
                               verticalalignment='bottom')
                        
                        # Format axis
                        ax.set_xlim(-self.settings.event.before_p_sec, 
                                   self.settings.event.after_p_sec)
                        
                        # Add trace label
                        label = f'{tr.stats.network}.{tr.stats.station}.{tr.stats.location or ""}.{tr.stats.channel}'
                        if hasattr(tr.stats, 'distance_km'):
                            label += f' {tr.stats.distance_km:.1f} km'
                        if hasattr(tr.stats, 'filterband'):
                            event_info += f", {tr.stats.filterband[0]}-{tr.stats.filterband[1]}Hz"
                        ax.text(-self.settings.event.before_p_sec * 0.95, 
                               ax.get_ylim()[1],
                               label,
                               fontsize=8)
                        
                        # Format time axis
                        if i == num_traces - 1:  # Only for bottom subplot
                            ax.set_xlabel('Time relative to P (seconds)')
                            # Add actual time labels
                            def format_time(x, p):
                                t = p_time + x
                                return t.strftime('%H:%M:%S')
                            ax.xaxis.set_major_formatter(plt.FuncFormatter(format_time))
                            plt.setp(ax.xaxis.get_majorticklabels(), rotation=20)
                    else:
                        # If no P arrival, plot raw data
                        times = np.arange(len(tr.data)) * tr.stats.delta

                        # Pre-process and apply a bandpass filter
                        if tr_windowed.stats.sampling_rate/2 > filter_min and filter_min<filter_max:
                            tr.detrend()
                            tr.taper(.005)
                            tr.filter('bandpass',freqmin=filter_min,freqmax=filter_max,
                                zerophase=True)

                        ax.plot(times, tr.data, '-', color=self._get_trace_color(tr), linewidth=0.8)
                        ax.text(0, ax.get_ylim()[1], 
                               f'{tr.stats.network}.{tr.stats.station}.{tr.stats.location or ""}.{tr.stats.channel} {tr.stats.filterband[0]}-{tr.stats.filterband[1]}Hz',
                               fontsize=8)
                
                # Remove unnecessary ticks
                ax.set_yticks([])
                if i < num_traces - 1:
                    ax.set_xticklabels([])
            
            # Format time axis for station view
            if view_type == "station":
                ax.set_xlabel('Time relative to origin (seconds)')
                ax.xaxis.set_major_formatter(plt.ScalarFormatter())
                ax.xaxis.set_major_locator(plt.MultipleLocator(20))
                ax.xaxis.set_major_formatter(lambda x, pos: f'{x:.0f}')
            
            plt.tight_layout()
            return fig
            
        except Exception as e:
            st.error(f"Error in plotting: {str(e)}")
            return None

    def _calculate_figure_dimensions(self, num_traces: int) -> tuple:
        """Calculate figure dimensions based on number of traces"""
        width = 12  # Slightly wider for better readability
        height_per_trace = 1.0  # Reduced slightly to fit more traces
        
        # Remove maximum height limit, keep minimum
        total_height = num_traces * height_per_trace + 0.5
        total_height = max(4, total_height)  # Only keep minimum height limit
        
        return (width, total_height)

    def plot_event_view(self, event, stream: Stream, page: int, num_pages: int):
        """Plot event view with proper time alignment and improved layout"""
        if not stream:
            return

        # Sort traces by distance (via starttime)
        stream.traces.sort(key=lambda x: x.stats.starttime)

        # Get current page's traces
        start_idx = page * self.filter_menu.display_limit
        end_idx = start_idx + self.filter_menu.display_limit
        current_stream = Stream(traces=stream.traces[start_idx:end_idx])
        
        # Create figure with standardized dimensions
        num_traces = len(current_stream)
        width, height = self._calculate_figure_dimensions(num_traces)
        fig = plt.figure(figsize=(width, height))
        
        # Use GridSpec with standardized spacing
        gs = plt.GridSpec(num_traces, 1, 
                         height_ratios=[1] * num_traces, 
                         hspace=0.05,
                         top=0.99,    # Adjusted from 0.97 to remove title space
                         bottom=0.08, 
                         left=0.1,
                         right=0.9)
        axes = [plt.subplot(gs[i]) for i in range(num_traces)]
        
        # Process each trace
        for i, tr in enumerate(current_stream):
            print("DEBUG plotted trace:",tr)
            ax = axes[i]

            # Calculate and add an appropriate filter for plotting
            filter_min,filter_max = get_tele_filter(tr)
            if filter_min < filter_max:
                tr.stats.filterband = (filter_min,filter_max)                 
            
            if hasattr(tr.stats, 'p_arrival'):
                p_time = UTCDateTime(tr.stats.p_arrival)
                before_p = self.settings.event.before_p_sec
                after_p = self.settings.event.after_p_sec
                
                # Trim trace to window around P
                window_start = p_time - before_p
                window_end = p_time + after_p
                tr_windowed = tr.slice(window_start, window_end)

                # Pre-process and apply a bandpass filter
                if tr_windowed.stats.sampling_rate/2 > filter_min and filter_min<filter_max:
                    tr_windowed.detrend()
                    tr_windowed.taper(.005)
                    tr_windowed.filter('bandpass',freqmin=filter_min,freqmax=filter_max,
                    zerophase=True)
                
                # Calculate times relative to P arrival
                times = np.arange(tr_windowed.stats.npts) * tr_windowed.stats.delta
                relative_times = times - before_p  # This makes P arrival at t=0
                
                # Plot the trace
                ax.plot(relative_times, tr_windowed.data, '-', 
                       color=self._get_trace_color(tr), linewidth=0.8)
                
                # Add P arrival line (now at x=0)
                ax.axvline(x=0, color='red', linewidth=1, linestyle='-', alpha=0.8)
                
                # Format station label with distance
                station_info = f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location or ''}.{tr.stats.channel}"
                if hasattr(tr.stats, 'distance_km'):
                    station_info += f" {tr.stats.distance_km:.1f} km"
                if hasattr(tr.stats, 'filterband'):
                    station_info += f", {tr.stats.filterband[0]}-{tr.stats.filterband[1]}Hz"
                
                # Position label inside plot
                ax.text(0.02, 0.95, station_info,
                       transform=ax.transAxes,
                       verticalalignment='top',
                       horizontalalignment='left',
                       fontsize=7,
                       bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=1))
                
                # Set consistent x-axis limits
                ax.set_xlim(-before_p, after_p)
                
                # Remove y-axis ticks and labels
                ax.set_yticks([])
                
                # Only show x-axis labels for bottom subplot
                if i < num_traces - 1:
                    ax.set_xticklabels([])
                else:
                    ax.set_xlabel('Time relative to P (seconds)')
                
                # Add subtle grid
                ax.grid(True, alpha=0.2)
                
                # Update box styling to show all borders
                for spine in ax.spines.values():
                    spine.set_visible(True)
                    spine.set_linewidth(0.5)

                # Add padding to the plot
                ax.margins(x=0.05)  # Increased padding to 5% on left and right
        
        # Adjust layout
        plt.subplots_adjust(left=0.1, right=0.9, top=0.97, bottom=0.1)
        
        return fig

    def plot_station_view(self, station_code: str, stream: Stream, page: int, num_pages: int):
        """Plot station view with event information"""
        if not stream:
            return
        
        # Sort traces by distance
        for tr in stream:
            if not hasattr(tr.stats, 'distance_km') or not tr.stats.distance_km:
                tr.stats.distance_km = 99999
        stream = Stream(sorted(stream, key=lambda tr: tr.stats.distance_km))
        
        # Get current page's traces
        start_idx = page * self.filter_menu.display_limit
        end_idx = start_idx + self.filter_menu.display_limit
        current_stream = Stream(traces=stream.traces[start_idx:end_idx])
        
        # Add event metadata to traces if not already present
        for tr in current_stream:
            if hasattr(tr.stats, 'event_id'):
                # Find corresponding event in selected catalogs
                for event in self.settings.event.selected_catalogs:
                    if str(event.resource_id) == tr.stats.event_id:
                        tr.stats.event_magnitude = event.magnitudes[0].mag
                        tr.stats.event_time = event.origins[0].time
                        # Add location from event extra parameters
                        if hasattr(event, 'extra') and 'region' in event.extra:
                            tr.stats.event_region = event.extra['region']['value']
                        break
        
        # Calculate standardized dimensions
        width, height = self._calculate_figure_dimensions(len(current_stream))
        
        # Create figure with standardized dimensions
        fig = plt.figure(figsize=(width, height))
        
        # Use GridSpec with standardized spacing
        gs = plt.GridSpec(len(current_stream), 1,
                         height_ratios=[1] * len(current_stream),
                         hspace=0.05,
                         top=0.97,
                         bottom=0.08,
                         left=0.1,
                         right=0.9)
        axes = [plt.subplot(gs[i]) for i in range(len(current_stream))]
        
        # Process each trace
        for i, tr in enumerate(current_stream):
            ax = axes[i]

            # Calculate and add an appropriate filter for plotting
            filter_min,filter_max = get_tele_filter(tr)
            if filter_min < filter_max:
                tr.stats.filterband = (filter_min,filter_max)

            if hasattr(tr.stats, 'p_arrival'):
                p_time = UTCDateTime(tr.stats.p_arrival)
                before_p = self.settings.event.before_p_sec
                after_p = self.settings.event.after_p_sec

                # Trim trace to window around P
                window_start = p_time - before_p
                window_end = p_time + after_p
                tr_windowed = tr.slice(window_start, window_end)

                # Pre-process and apply a bandpass filter
                if tr_windowed.stats.sampling_rate/2 > filter_min and filter_min<filter_max:
                    tr_windowed.detrend()
                    tr_windowed.taper(.005)
                    tr_windowed.filter('bandpass',freqmin=filter_min,freqmax=filter_max,
                        zerophase=True)                

                # Calculate times relative to P arrival
                times = np.arange(tr_windowed.stats.npts) * tr_windowed.stats.delta
                relative_times = times - before_p  # This makes P arrival at t=0

                # Plot the trace
                ax.plot(relative_times, tr_windowed.data, '-', 
                       color=self._get_trace_color(tr), linewidth=0.8)

                # Add P arrival line (now at x=0)
                ax.axvline(x=0, color='red', linewidth=1, linestyle='-', alpha=0.8)

                # Format station label with distance, magnitude, and region
                station_info = f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location or ''}.{tr.stats.channel}"
                event_info = []
                # TODO: Add distance, magnitude, and region to station_info
                if hasattr(tr.stats, 'distance_km'):
                    event_info.append(f"{tr.stats.distance_km:.1f} km")
                if hasattr(tr.stats, 'event_time'):
                    event_info.append(f"OT:{str(tr.stats.event_time)[0:19]}")                    
                if hasattr(tr.stats, 'event_magnitude'):
                    event_info.append(f"M{tr.stats.event_magnitude:.1f}")
                if hasattr(tr.stats, 'event_region'):
                    event_info.append(tr.stats.event_region)
                if hasattr(tr.stats, 'filterband'):
                    event_info.append(f"{tr.stats.filterband[0]}-{tr.stats.filterband[1]}Hz")

                # Combine all information with proper formatting
                label = f"{station_info} - {', '.join(event_info)}"
                
                # Position label inside plot
                ax.text(0.02, 0.95, label,
                       transform=ax.transAxes,
                       verticalalignment='top',
                       horizontalalignment='left',
                       fontsize=7,
                       bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=1))

                # Set consistent x-axis limits
                ax.set_xlim(-before_p, after_p)

                # Remove y-axis ticks and labels
                ax.set_yticks([])

                # Only show x-axis labels for bottom subplot
                if i < len(current_stream) - 1:
                    ax.set_xticklabels([])
                else:
                    ax.set_xlabel('Time relative to P (seconds)')

                # Add subtle grid
                ax.grid(True, alpha=0.2)

                # Update box styling to show all borders
                for spine in ax.spines.values():
                    spine.set_visible(True)
                    spine.set_linewidth(0.5)

                # Add padding to the plot
                ax.margins(x=0.05)  # Increased padding to 5% on left and right

        # Update title
        net, sta = station_code.split(".")
        #fig.suptitle(f"Station {station_code} - Multiple Events View",
        #            fontsize=10, y=0.98)
        
        return fig

    def render(self):
        view_type = st.radio(
            "Select View Type",
            ["Single Event - Multiple Stations", "Single Station - Multiple Events"],
            key="view_selector_waveform"
        )
        
        if not self.streams:
            st.info("No waveforms to display. Use the 'Get Waveforms' button to retrieve waveforms.")
            return

        if view_type == "Single Event - Multiple Stations":
            events = self.settings.event.selected_catalogs
            if not events:
                st.warning("No events available.")
                return
            
            # it's possible an event doesn't have a magnitude TODO
            event_options = [
                f"Event {i+1}: {event.origins[0].time} M{event.magnitudes[0].mag:.1f} {event.extra.get('region', {}).get('value', 'Unknown Region')}"
                for i, event in enumerate(events)
            ]
            selected_event_idx = st.selectbox(
                "Select Event",
                range(len(event_options)),
                format_func=lambda x: event_options[x]
            )
            
            if self.streams and len(self.streams) > selected_event_idx:
                stream = self.streams[selected_event_idx]
                filtered_stream = self.apply_filters(stream)
                
                if len(filtered_stream) > 0:
                    # Calculate pagination
                    num_pages = (len(filtered_stream) - 1) // self.filter_menu.display_limit + 1
                    page = st.sidebar.selectbox(
                        "Page Navigation", 
                        range(1, num_pages + 1),
                        key="event_view_pagination"
                    ) - 1
                    
                    fig = self.plot_event_view(
                        events[selected_event_idx],
                        filtered_stream,
                        page,
                        num_pages
                    )
                    if fig:
                        st.session_state.current_figure = fig
                        st.pyplot(fig)
                else:
                    st.warning("No waveforms match the current filter criteria.")
        
        else:  # Single Station - Multiple Events view
            if not self.streams:
                st.warning("No streams available.")
                return
            
            # Get unique stations from all streams
            stations = set()
            for stream in self.streams:
                filtered_stream = self.apply_filters(stream)
                for tr in filtered_stream:
                    stations.add(f"{tr.stats.network}.{tr.stats.station}")
            
            if not stations:
                st.warning("No stations match the current filter criteria.")
                return
            
            station_options = sorted(list(stations))
            selected_station = st.selectbox(
                "Select Station",
                station_options
            )
            
            if selected_station:
                net, sta = selected_station.split(".")
                # Collect all traces for selected station
                station_stream = Stream()
                for stream in self.streams:
                    filtered_stream = self.apply_filters(stream)
                    for tr in filtered_stream:
                        if tr.stats.network == net and tr.stats.station == sta:
                            station_stream += tr
                
                if station_stream:
                    # Calculate pagination
                    num_pages = (len(station_stream) - 1) // self.filter_menu.display_limit + 1
                    page = st.sidebar.selectbox(
                        "Page Navigation", 
                        range(1, num_pages + 1),
                        key="station_view_pagination"
                    ) - 1
                    
                    # Use plot_station_view
                    fig = self.plot_station_view(selected_station, station_stream, page, num_pages)
                    if fig:
                        st.session_state.current_figure = fig
                        st.pyplot(fig)
                else:
                    st.warning("No waveforms available for the selected station.")
        # Create missing data display before checking streams
        missing_data_display = MissingDataDisplay(
            self.streams,
            self.missing_data,
            self.settings
        )
        missing_data_display.render()
class WaveformComponents:
    settings: SeismoLoaderSettings
    filter_menu: WaveformFilterMenu
    waveform_display: WaveformDisplay
    continuous_components: ContinuousComponents
    console: ConsoleDisplay
    
    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.filter_menu = WaveformFilterMenu(settings)
        self.waveform_display = WaveformDisplay(settings, self.filter_menu)
        self.continuous_components = ContinuousComponents(settings)
        self.console = ConsoleDisplay()
        
        # Pass console to WaveformDisplay
        self.waveform_display.console = self.console
        
        # Initialize session state
        required_states = {
            "is_downloading": False,
            "query_done": False,
            "polling_active": False,
            "query_thread": None,
            "trigger_rerun": False
        }
        for key, val in required_states.items():
            if key not in st.session_state:
                st.session_state[key] = val

    def render_polling_ui(self):
        """
        Handles UI updates while monitoring background thread status
        """
        if st.session_state.get("is_downloading", False):
            with st.spinner("Downloading waveforms... (this may take several minutes)"):
                query_thread = st.session_state.get("query_thread")
                if query_thread and not query_thread.is_alive():
                    try:
                        query_thread.join()
                    except Exception as e:
                        st.error(f"Error in background thread: {e}")
                        # Add error to console output
                        if not self.console.accumulated_output:
                            self.console.accumulated_output = []
                        self.console.accumulated_output.append(f"Error: {str(e)}")

                    st.session_state.update({
                        "is_downloading": False,
                        "query_done": True,
                        "query_thread": None,
                        "polling_active": False
                    })
                    st.rerun()

                if st.session_state.get("polling_active"):
                    time.sleep(0.5)  # Brief pause between checks
                    st.rerun()

    def render(self):
        if self.settings.selected_workflow == WorkflowType.CONTINUOUS:
            self.continuous_components.render()
            return

        # Create tabs for Waveform and Log views
        waveform_tab, log_tab = st.tabs(["📊 Waveform View", "📝 Log View"])

        
        # Always render filter menu (sidebar) first
        current_stream = self.waveform_display.streams[0] if self.waveform_display.streams else None
        self.filter_menu.render(current_stream)

        # Handle content based on active tab
        with waveform_tab:
            self._render_waveform_view()
        
        with log_tab:
            self._render_log_view()


    def _render_waveform_view(self):
        st.title("Waveform Analysis")

        # Create three columns for the controls
        col1, col2, col3 = st.columns(3)
        
        # Force Re-download toggle in first column
        with col1:
            self.settings.waveform.force_redownload = st.toggle(
                "Force Re-download", 
                value=self.settings.waveform.force_redownload, 
                help="If turned off, the app will try to avoid "
                "downloading data that are already available locally."
                " If flagged, it will redownload the data again."
            )

        # Get Waveforms button in second column
        with col2:
            get_waveforms_button = st.button(
                "Get Waveforms",
                key="get_waveforms",
                disabled=st.session_state.get("is_downloading", False),
                use_container_width=True
            )

        # Cancel Download button in third column
        with col3:
            if st.button("Cancel Download", 
                        key="cancel_download",
                        disabled=not st.session_state.get("is_downloading", False),
                        use_container_width=True):
                stop_event.set()  # Signal cancellation
                st.warning("Cancelling query...")
                st.session_state.update({
                    "is_downloading": False,
                    "polling_active": False
                })
                st.rerun()

        # Download status indicator
        status_container = st.empty()
        
        # Show appropriate status message
        if get_waveforms_button:
            status_container.info("Starting waveform download...")
            self.waveform_display.retrieve_waveforms()
        elif st.session_state.get("is_downloading"):
            # status_container.info("Downloading waveforms... (this may take several minutes)")
            st.spinner("Downloading waveforms... (this may take several minutes)")
            self.render_polling_ui()
        elif st.session_state.get("query_done") and self.waveform_display.streams:
            status_container.success(f"Successfully retrieved waveforms for {len(self.waveform_display.streams)} events.")
        elif st.session_state.get("query_done"):
            status_container.warning("No waveforms retrieved. Please check your selection criteria.")

        # Display waveforms if they exist
        if self.waveform_display.streams:
            self.waveform_display.render()

        # Add download button at the bottom of the sidebar
        with st.sidebar:
            st.markdown("---")
            if st.session_state.get("current_figure") is not None:

                import io
                buf = io.BytesIO()
                st.session_state.current_figure.savefig(buf, format='png', dpi=300, bbox_inches='tight')
                buf.seek(0)
                
                st.download_button(
                    label="Download PNG",
                    data=buf,
                    file_name="waveform_plot.png",
                    mime="image/png",
                    use_container_width=True
                )
            else:
                st.button("Download PNG", disabled=True, use_container_width=True)


    def _render_log_view(self):
        st.title("Waveform Retrieval Logs")
        self.console._init_terminal_style()  # Initialize terminal styling
        
        if self.console.accumulated_output:
            log_text = (
                '<div class="terminal" id="log-terminal">'
                '<pre>{}</pre>'
                '</div>'
            ).format('\n'.join(self.console.accumulated_output))
            st.markdown(log_text, unsafe_allow_html=True)
        else:
            st.info("No logs available yet. Perform a waveform download first.")
class MissingDataDisplay:
    def __init__(self, streams: List[Stream], missing_data: Dict[str, Union[List[str], str]], settings: SeismoLoaderSettings):
        self.streams = streams
        self.missing_data = missing_data
        self.settings = settings
    
    def _format_event_time(self, event) -> str:
        """Format event time in a readable way"""
        return event.origins[0].time.strftime('%Y-%m-%d %H:%M:%S')
    
    def _get_missing_events(self):
        """Identify events with no data and their missing channels"""
        missing_events = []
        
        # sort events by time? does this cause problems elsewhere? can we just sort selected_catalogs? do this elsewhere? REVIEW
        try:
            catalog = self.settings.event.selected_catalogs.copy() #need copy?
            catalog.events.sort(key=lambda x: getattr(x.origins[0], 'time', UTCDateTime(0)) if x.origins else UTCDateTime(0))
        except Exception as e:
            print("catalog sort problem",e)

        for event in catalog:
            event_id = str(event.resource_id)

            # Create a string for NSLCs which should have been downloaded (e.g. within search radius) but weren't for some reason
            try:
                if event_id not in self.missing_data.keys():
                    continue

                results = []
                for station_key, value in self.missing_data[event_id].items():
                    if value == "ALL":
                        results.append(f"{station_key}.*")  # Indicate all channels missing
                    elif value == '':
                        continue
                    elif isinstance(value, list):
                        if value:  # If list not empty
                            results.extend(value)  # Add all missing channels
                if results:
                    missing_data_str = ' '.join(results)
                else:
                    missing_data_str = None

            except Exception as e:
                missing_data_str = None
                print("DEBUG: missing data dict issue",e)


            if missing_data_str:
                # Combine event ot, mag, region into one column
                event_str = f"{self._format_event_time(event)},  M{event.magnitudes[0].mag:.1f},  {event.extra.get('region', {}).get('value', 'Unknown Region')}"

                # Event completely missing
                missing_events.append({
                    'Event ID': event_id,
                    'Event': event_str,
                    'Missing Data': missing_data_str
                })
        
        return missing_events
    
    def render(self):
        """Display missing event information in a table format"""
        missing_events = self._get_missing_events()
        
        if missing_events:
            st.warning("⚠️ Events with Missing Data:")
            
            # Create DataFrame from missing events
            df = pd.DataFrame(missing_events)
            
            # Calculate dynamic height based on number of rows
            height = len(df) * 35 + 40  # Same formula as distance display
            
            # Display the DataFrame
            st.dataframe(
                df,
                use_container_width=True,
                height=height,
                hide_index=True
            )


if st.session_state.get("trigger_rerun", False):
    st.session_state["trigger_rerun"] = False  # Reset flag to prevent infinite loops
    st.rerun()  # 🔹 Force UI update
