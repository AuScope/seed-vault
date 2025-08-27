from typing import List, Dict, Union
from obspy import Stream, Trace, UTCDateTime
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
from copy import deepcopy
from seed_vault.ui.app_pages.helpers.common import save_filter
from time import sleep
import sys
import queue

# Create a global stop event for cancellation
query_thread = None
stop_event = threading.Event()
# Create a global queue for logs
log_queue = queue.Queue()
# Track threading task status
task_completed = threading.Event()
task_result = {"success": False}

if "query_done" not in st.session_state:
    st.session_state["query_done"] = False
if "trigger_rerun" not in st.session_state:
    st.session_state["trigger_rerun"] = False
if "log_entries" not in st.session_state:
    st.session_state["log_entries"] = []

def get_tele_filter(tr):
    """Calculate appropriate filter band for teleseismic data based on distance.

    This function determines the optimal frequency band for filtering teleseismic
    data based on the distance from the source and the sensor type.

    Args:
        tr (Trace): ObsPy Trace object containing waveform data.

    Returns:
        tuple: A tuple of (f0, f1) where:
            - f0 (float): Lower frequency bound in Hz
            - f1 (float): Upper frequency bound in Hz
            Returns (0, 0) for non-seismic sensors.

    Note:
        The filter bands are optimized for different distance ranges:
        - < 50 km: 2.0-15 Hz
        - 50-100 km: 1.7-12 Hz
        - 100-250 km: 1.5-10 Hz
        - 250-500 km: 1.4-8 Hz
        - 500-1000 km: 1.3-6 Hz
        - 1000-2500 km: 1.2-5 Hz
        - 2500-5000 km: 1.1-4 Hz
        - 5000-10000 km: 1.0-3 Hz
        - > 10000 km: 0.7-2 Hz
    """
    distance_km = tr.stats.distance_km
    nyq = tr.stats.sampling_rate/2 - 0.1
    senstype = tr.stats.channel[1]

    if senstype not in ['H','N']:
        return 0,0 # flagged elsewhere

    if distance_km < 50:
        f0,f1 = 2.0,15
    elif distance_km < 100:
        f0,f1 = 1.7,12
    elif distance_km < 250:
        f0,f1 = 1.5,10
    elif distance_km < 500:
        f0,f1 = 1.4,8
    elif distance_km < 1000:
        f0,f1 = 1.3,6
    elif distance_km < 2500:
        f0,f1 = 1.2,5
    elif distance_km < 5000:
        f0,f1 = 1.1,4     
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
        """Initialize the WaveformFilterMenu.

        Args:
            settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
        """
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
        """Check for changes in filter settings and trigger UI updates.

        This method compares current filter settings with previous state and
        triggers a UI refresh if changes are detected. It also handles saving
        of filter settings.

        Note:
            The method uses Streamlit's rerun mechanism to update the UI
            when changes are detected.
        """
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
        """Update the list of available channels based on the current stream.

        This method extracts unique channel codes from the provided stream
        and updates the available_channels list.

        Args:
            stream (Stream): ObsPy Stream object containing waveform data.

        Note:
            The method handles different types of stream objects and ensures
            "All channels" remains as the first option in the list.
        """
        if not stream:
            self.available_channels = ["All channels"]
            return

        channels = set()

        # Handle different types of stream objects
        if isinstance(stream, Stream):
            # Case 1: ObsPy Stream object
            for tr in stream:
                if hasattr(tr.stats, 'channel'):
                    channels.add(tr.stats.channel)
        elif isinstance(stream, list):
            # Case 2: List of traces or Stream objects
            for item in stream:
                if isinstance(item, Trace):
                    # Individual trace
                    if hasattr(item.stats, 'channel'):
                        channels.add(item.stats.channel)
                elif isinstance(item, Stream):
                    # Stream object in a list
                    for tr in item:
                        if hasattr(tr.stats, 'channel'):
                            channels.add(tr.stats.channel)
                else:
                    # Try to handle as a generic object with stats.channel
                    try:
                        if hasattr(item, 'stats') and hasattr(item.stats, 'channel'):
                            channels.add(item.stats.channel)
                    except:
                        pass

        # If we found any channels, update the available_channels list
        # Ensure "All channels" is always at the top by separating it from the sorted list
        if channels:
            sorted_channels = sorted(list(channels))
            self.available_channels = ["All channels"] + sorted_channels
        else:
            self.available_channels = ["All channels"]

        # Reset channel filter if current selection is invalid
        if self.channel_filter not in self.available_channels:
            self.channel_filter = "All channels"

    def render(self, stream=None):
        """Render the waveform filter menu interface.

        This method creates the UI for waveform filtering and control, including:
        - Network, station, and channel filters
        - Display limit controls
        - Status information
        - Reset functionality

        Args:
            stream (Stream, optional): Current waveform stream to filter.
                If None, only basic controls are shown.

        Note:
            The interface is organized in expandable sections for better
            user experience and space management.
        """
        st.sidebar.title("Waveform Controls")

        # Step 1: Data Retrieval Settings
        with st.sidebar.expander("Step 1: Data Source", expanded=True):
            st.subheader("🔍 Filter Events Around Individual Stations")
            cc1, cc2 = st.columns([1, 1])

            with cc1:
                min_radius = st.number_input("Minimum radius (degree)",
                    value=self.settings.event.min_radius or 0.0, 
                    step=0.5, min_value=0.0, max_value=180.0)
                if min_radius != self.settings.event.min_radius:
                    self.settings.event.min_radius = min_radius
                    self.refresh_filters()
            with cc2:
                max_radius = st.number_input("Maximum radius (degree)",
                    value=self.settings.event.max_radius or 90.0,
                    step=0.5, min_value=0.0, max_value=180.0)
                if max_radius != self.settings.event.max_radius:
                    self.settings.event.max_radius = max_radius
                    self.refresh_filters()

            st.subheader("🔍 Time Window")
            
            # Update time window settings with immediate refresh
            before_p = st.number_input(
                "Start (secs before P arrival):", 
                value=self.settings.event.before_p_sec or 20,
                step = 5,
                help="Time window before P arrival",
                key="before_p_input"
            )
            if before_p != self.settings.event.before_p_sec:
                self.settings.event.before_p_sec = before_p
                self.refresh_filters()

            after_p = st.number_input(
                "End (secs after P arrival):", 
                value=self.settings.event.after_p_sec or 100,
                step = 5,
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
                # Get network codes and sort them, ensuring "All networks" is at the top
                network_codes = list(set([inv.code for inv in self.settings.station.selected_invs]))
                network_codes.sort()  # Sort alphabetically
                networks = ["All networks"] + network_codes  # Ensure "All networks" is at the top

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
                # Get station codes and sort them, ensuring "All stations" is at the top
                station_codes = []
                for inv in self.settings.station.selected_invs:
                    station_codes.extend([sta.code for sta in inv])
                station_codes = list(dict.fromkeys(station_codes))  # Remove duplicates
                station_codes.sort()  # Sort alphabetically
                stations = ["All stations"] + station_codes  # Ensure "All stations" is at the top

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
    """A component for displaying and managing waveform data visualization.

    This class handles the display of seismic waveform data, including both
    event-based and station-based views, with support for filtering and pagination.
    IMAGES are cached to minimize re-processing.

    Attributes:
        settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
        filter_menu (WaveformFilterMenu): Menu component for filtering waveforms.
        client (Client): FDSN client for waveform data retrieval.
        ttmodel (TauPyModel): Travel-time model for seismic phases.
        stream (List[Stream]): List of waveform streams.
        processed_cache (Dict): Cache for processed waveform data.
        missing_data (Dict): Dictionary tracking missing data.
        console (ConsoleDisplay): Console for logging output.
    """

    def __init__(self, settings: SeismoLoaderSettings, filter_menu: WaveformFilterMenu):
        """Initialize the WaveformDisplay component.

        Args:
            settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
            filter_menu (WaveformFilterMenu): Menu component for filtering waveforms.
        """
        self.settings = settings
        self.filter_menu = filter_menu

        try:
            self.client = Client(self.settings.waveform.client)
        except ValueError as e:
            st.error(f"Error: {str(e)} Waveform client is set to {self.settings.waveform.client}, which seems to not exist..? Please navigate to the settings page and use the Clients tab to add the client or fix the stored config.cfg file.")
        self.ttmodel = TauPyModel("iasp91")
        self.stream = []
        self.processed_cache = {}  # NEW: Cache for processed waveforms
        self.figure_cache = {}  # NEW: Cache for matplotlib figures
        self.missing_data = {}
        self.console = ConsoleDisplay()  # Add console display

    def _get_processing_key(self, trace_id: str, filter_min: float, filter_max: float) -> str:
        """Generate a unique key for processed waveform caching."""
        response_level = self.settings.station.level if hasattr(self.settings.station, 'level') else "none"
        before_p = self.settings.event.before_p_sec
        after_p = self.settings.event.after_p_sec
        return f"{trace_id}_{response_level}_{filter_min}_{filter_max}_{before_p}_{after_p}"

    def _get_processed_trace(self, trace, filter_min: float, filter_max: float):
        """Get a processed trace from cache or process it if not cached."""
        trace_id = f"{trace.stats.network}.{trace.stats.station}.{trace.stats.location}.{trace.stats.channel}_{trace.stats.starttime}"
        cache_key = self._get_processing_key(trace_id, filter_min, filter_max)
        
        # Return cached version if available
        if cache_key in self.processed_cache:
            return self.processed_cache[cache_key].copy()
        
        # Process and cache the trace
        tr_copy = trace.copy()
        tr_copy.detrend()
        if self.settings.station.level == "response":
            tr_copy.taper(.05)
            tr_copy.remove_response(self.settings.station.selected_invs,pre_filt=[.03,.06,40,49])
        else:
            tr_copy.taper(.02)
        
        if hasattr(trace.stats, 'p_arrival'):
            p_time = UTCDateTime(trace.stats.p_arrival)
            before_p = self.settings.event.before_p_sec
            after_p = self.settings.event.after_p_sec
            window_start = p_time - before_p
            window_end = p_time + after_p
            tr_copy = tr_copy.slice(window_start, window_end)
        
        if tr_copy.stats.sampling_rate/2 > filter_min and filter_min<filter_max:
            tr_copy.filter('bandpass',freqmin=filter_min,freqmax=filter_max,zerophase=True)
        
        tr_copy.stats.filterband = (filter_min,filter_max)
        
        # Cache and return
        self.processed_cache[cache_key] = tr_copy.copy()
        return tr_copy

    def clear_cache(self):
        """Clear the processed waveform cache."""
        self.processed_cache.clear()
        self.figure_cache.clear()  # NEW: Also clear figure cache

    def apply_filters(self, stream) -> Stream:
        """Apply filters to the waveform stream based on user selections.

        Args:
            stream (Stream): Input ObsPy Stream object to filter.

        Returns:
            Stream: Filtered stream containing only traces matching the selected
                network, station, and channel filters.
        """
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
        """Fetch waveform data in a background thread with logging.

        This method sets up a custom logging system, retrieves waveform data,
        and handles any errors or cancellations during the process.

        Note:
            The method updates the session state with processing status and logs.
        """
        # Custom stdout/stderr handler that writes to both the original traces and our queue
        class QueueLogger:
            def __init__(self, original_stream, queue):
                self.original_stream = original_stream
                self.queue = queue
                self.buffer = ""

            def write(self, text):
                self.original_stream.write(text)
                self.buffer += text

                # Only flush when buffer gets large enough
                if len(self.buffer) > 80:  # Buffer getting too large, flush it
                    self.queue.put(self.buffer)
                    self.buffer = ""

            def flush(self):
                self.original_stream.flush()
                if self.buffer:  # Flush any remaining content in buffer
                    self.queue.put(self.buffer)
                    self.buffer = ""

        # Set up queue loggers
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = QueueLogger(original_stdout, log_queue)
        sys.stderr = QueueLogger(original_stderr, log_queue)

        try:
            print("Starting waveform download process...")
            stream_and_missing = run_event(self.settings, stop_event)
            if stream_and_missing:
                self.stream, self.missing_data = stream_and_missing
                self.clear_cache()  # NEW: Clear cache when new data is loaded
                success = True
                print("Download completed successfully.")
                # If stopped via the cancel button, reset it continue to plotting as normal
                stop_event.clear()
            else:
                success = False
                if stop_event.is_set():
                    print("Download was cancelled by user.")
                    st.session_state["download_cancelled"] = True
                else:
                    print("Download failed.")

            task_result["success"] = success

        except Exception as e:
            print(f"Error: {str(e)}")
            task_result["success"] = False
        finally:
            # Flush any remaining content
            sys.stdout.flush()
            sys.stderr.flush()

            # Ensure stop event is cleared
            stop_event.clear()

            # Restore original stdout/stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr

            task_completed.set()



    def retrieve_waveforms(self):
        """Initiate waveform retrieval in a background thread.

        This method starts a new thread for waveform data retrieval and updates
        the UI state accordingly.

        Note:
            The method handles thread creation, state management, and UI updates.
        """
        if not self.settings.event.selected_catalogs or not self.settings.station.selected_invs:
            st.warning("Please select events and stations before downloading waveforms.")
            return

        stop_event.clear()  # Reset cancellation flag
        task_completed.clear() # Reset completion flag

        st.session_state["query_thread"] = threading.Thread(target=self.fetch_data, daemon=True)
        st.session_state["query_thread"].start()

        st.session_state.update({
            "is_downloading": True,
            "query_done": False,
            "polling_active": True,
            "download_cancelled": False
        })

        st.rerun()

    def _get_trace_color(self, tr) -> str:
        """Get color for a trace based on its channel component.

        Args:
            tr (Trace): ObsPy Trace object.

        Returns:
            str: Color code for the trace based on its component:
                - 'Z': black
                - 'N' or '1': blue
                - 'E' or '2': green
                - others: gray
                - non-seismic sensors: tomato
        """
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

    def _calculate_figure_dimensions(self, num_traces: int) -> tuple:
        """Calculate figure dimensions based on number of traces.

        Args:
            num_traces (int): Number of traces to display.

        Returns:
            tuple: A tuple of (width, height) in inches for the figure.
                Width is fixed at 12 inches, height is calculated based on
                number of traces with a minimum of 4 inches.
        """
        width = 12  # Slightly wider for better readability
        height_per_trace = 1.0  # Reduced slightly to fit more traces
        
        # Remove maximum height limit, keep minimum
        total_height = num_traces * height_per_trace + 0.5
        total_height = max(4, total_height)  # Only keep minimum height limit
        
        return (width, total_height)

    def plot_event_view(self, event, stream: Stream, page: int, num_pages: int):
        """Plot event view with proper time alignment and improved layout.

        Args:
            event: Event object containing event information.
            stream (Stream): ObsPy Stream object containing waveform data.
            page (int): Current page number for pagination.
            num_pages (int): Total number of pages.

        Returns:
            Figure: Matplotlib figure object containing the plot.
        """
        if not stream:
            return

        # NEW: Check figure cache first - use trace IDs for stable cache key
        trace_ids = sorted([f"{tr.stats.network}.{tr.stats.station}.{tr.stats.channel}_{tr.stats.starttime}" for tr in stream])
        cache_key = f"event_{event.resource_id.id}_{page}_{hash(tuple(trace_ids))}_{self.filter_menu.display_limit}"
        if cache_key in self.figure_cache:
            return self.figure_cache[cache_key]

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
            ax = axes[i]

            # Calculate and add an appropriate filter for plotting
            filter_min,filter_max = get_tele_filter(tr)
            
            # NEW: Use cached processing instead of remove_instrument_response
            tr_windowed = self._get_processed_trace(tr, filter_min, filter_max)
            
            if hasattr(tr.stats, 'p_arrival'):
                p_time = UTCDateTime(tr.stats.p_arrival)
                before_p = self.settings.event.before_p_sec
                after_p = self.settings.event.after_p_sec
                
                # Calculate times relative to P arrival
                times = np.arange(tr_windowed.stats.npts) * tr_windowed.stats.delta
                relative_times = times - before_p  # This makes P arrival at t=0
                
                # Plot the trace
                ax.plot(relative_times, tr_windowed.data, '-', 
                       color=self._get_trace_color(tr), linewidth=0.8)
                
                # Add P arrival line (now at x=0)
                ax.axvline(x=0, color='red', linewidth=1, linestyle='-', alpha=0.8)
                
                # Format station label with distance (formatted much differently than station view for some reason!)
                station_info = f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location or ''}.{tr.stats.channel} -"
                if hasattr(tr.stats, 'distance_km'):
                    station_info += f" {tr.stats.distance_km:.1f} km"
                #adding event mag and region temporarily for debugging
                if hasattr(tr.stats, 'event_time'):
                    station_info += f", OT:{str(tr.stats.event_time)[0:19]}"                
                if hasattr(tr.stats, 'event_magnitude'):
                    station_info += f", M{tr.stats.event_magnitude:.1f}"
                if hasattr(tr.stats, 'event_region'):
                    station_info += f", {tr.stats.event_region}"                    
                if hasattr(tr_windowed.stats, 'filterband'):
                    station_info += f", {tr_windowed.stats.filterband[0]}-{tr_windowed.stats.filterband[1]}Hz"
                
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
                    ax.set_xlabel(f'Seconds relative to P ({str(p_time)})')
                
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
        
        # NEW: Cache the figure before returning
        self.figure_cache[cache_key] = fig
        
        return fig

    def plot_station_view(self, station_code: str, stream: Stream, page: int, num_pages: int):
        """Plot station view with event information.

        Args:
            station_code (str): Code of the station to display.
            stream (Stream): ObsPy Stream object containing waveform data.
            page (int): Current page number for pagination.
            num_pages (int): Total number of pages.

        Returns:
            Figure: Matplotlib figure object containing the plot.
        """
        if not stream:
            return

        # NEW: Check figure cache first - use trace IDs for stable cache key
        trace_ids = sorted([f"{tr.stats.network}.{tr.stats.station}.{tr.stats.channel}_{tr.stats.starttime}" for tr in stream])
        cache_key = f"station_{station_code}_{page}_{hash(tuple(trace_ids))}_{self.filter_menu.display_limit}"
        if cache_key in self.figure_cache:
            return self.figure_cache[cache_key]

        # Sort traces by distance
        for tr in stream:
            if not hasattr(tr.stats, 'distance_km') or not tr.stats.distance_km:
                tr.stats.distance_km = 99999

        stream = Stream(sorted(stream, key=lambda tr: tr.stats.distance_km)) #TODO users may prefer to sort by OT

        # Get current page's traces
        start_idx = page * self.filter_menu.display_limit
        end_idx = start_idx + self.filter_menu.display_limit
        current_stream = Stream(traces=stream.traces[start_idx:end_idx])

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
            
            # NEW: Use cached processing instead of remove_instrument_response
            tr_windowed = self._get_processed_trace(tr, filter_min, filter_max)

            if hasattr(tr.stats, 'p_arrival'):
                p_time = UTCDateTime(tr.stats.p_arrival)
                before_p = self.settings.event.before_p_sec
                after_p = self.settings.event.after_p_sec

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
                if hasattr(tr_windowed.stats, 'filterband'):
                    event_info.append(f"{tr_windowed.stats.filterband[0]}-{tr_windowed.stats.filterband[1]}Hz")

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
                    ax.set_xlabel(f'Seconds relative to P ({str(p_time)})')

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

        # NEW: Cache the figure before returning
        self.figure_cache[cache_key] = fig

        return fig

    def render(self):
        """Render the waveform display interface.

        This method creates the main UI for waveform visualization, including:
        - View type selection (Event/Station view)
        - Waveform display
        - Missing data information
        """
        view_type = st.radio(
            "Select View Type",
            ["Single Event - Multiple Stations", "Single Station - Multiple Events"],
            key="view_selector_waveform"
        )

        if not self.stream:
            st.info("No waveforms to display. Use the 'Get Waveforms' button to retrieve waveforms.")
            return

        if view_type == "Single Event - Multiple Stations":
            events = self.settings.event.selected_catalogs
            if not events:
                st.warning("No events available.")
                return

            # a list of event resource ids
            existing_event_resource_ids = [eq.resource_id for eq in events]

            # a list of EQ resource_ids to confirm what data actually exists
            existing_data_resource_ids = list(set([tr.stats.resource_id for tr in self.stream]))

            # map the events.. hanging onto the original indexes so users can keep track of what's happening
            valid_events_with_indices = [(i, event) for i, event in enumerate(events)
                            if hasattr(event, 'resource_id') and event.resource_id in existing_data_resource_ids]

            event_options = [
                f"Event {orig_idx+1}: {event.origins[0].time} "
                f"M{event.magnitudes[0].mag if hasattr(event, 'magnitudes') and event.magnitudes else 0.99:.1f} "
                f"{event.extra.get('region', {}).get('value', 'Unknown Region')}"
                for orig_idx, event in valid_events_with_indices
            ]

            valid_events = [event for _, event in valid_events_with_indices]

            selected_event_idx = st.selectbox(
                "Select Event",
                range(len(event_options)),
                format_func=lambda x: event_options[x]
            )

            selected_event = valid_events[selected_event_idx]    
            event_stream = Stream([tr for tr in self.stream if tr.stats.resource_id == selected_event.resource_id.id])
            filtered_stream = self.apply_filters(event_stream)

            if filtered_stream:

                # Calculate pagination
                num_pages = (len(filtered_stream) - 1) // self.filter_menu.display_limit + 1
                page = st.sidebar.selectbox(
                    "Page Navigation", 
                    range(1, num_pages + 1),
                    key="event_view_pagination"
                ) - 1
                
                fig = self.plot_event_view(
                    selected_event,
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
            if not self.stream:
                st.warning("No traces available.")
                return

            # Get unique stations from all traces
            filtered_stream = self.apply_filters(self.stream)
            stations = set([f"{tr.stats.network}.{tr.stats.station}" for tr in filtered_stream])

            if not stations:
                st.warning("No stations match the current filter criteria.")
                return

            # may have to check if there exists data for said station (TODO)
            station_options = sorted(list(stations))
            selected_station = st.selectbox(
                "Select Station",
                station_options
            )

            if selected_station:
                net, sta = selected_station.split(".")

                # select for pertinent station
                station_stream = filtered_stream.select(network=net,station=sta)
                
                if station_stream:
                    # Calculate pagination
                    num_pages = (len(station_stream) - 1) // self.filter_menu.display_limit + 1
                    page = st.sidebar.selectbox(
                        "Page Navigation", 
                        range(1, num_pages + 1),
                        key="station_view_pagination"
                    ) - 1

                    # Use plot_station_view
                    try:
                        fig = self.plot_station_view(selected_station, station_stream, page, num_pages)
                    except Exception as e:
                        print(f"waveform.plot_station_view issue:\n {e}")

                    if fig:
                        st.session_state.current_figure = fig
                        st.pyplot(fig)
                else:
                    st.warning("No waveforms available for the selected station.")
        # Create missing data display before checking stream
        missing_data_display = MissingDataDisplay(
            self.stream,
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

        # Initialize console with logs from session state if they exist
        if "log_entries" in st.session_state and st.session_state["log_entries"]:
            self.console.accumulated_output = st.session_state["log_entries"]

        # Pass console to WaveformDisplay
        self.waveform_display.console = self.console

        # Initialize session state
        required_states = {
            "is_downloading": False,
            "query_done": False,
            "polling_active": False,
            "query_thread": None,
            "trigger_rerun": False,
            "log_entries": []
        }
        for key, val in required_states.items():
            if key not in st.session_state:
                st.session_state[key] = val

    def render_polling_ui(self):
        """
        Handles UI updates while monitoring background thread status
        """
        if st.session_state.get("is_downloading", False):
            if task_completed.is_set():
                # Update session state from the main thread
                st.session_state.update({
                    "is_downloading": False,
                    "query_done": True,
                    "query_thread": None,
                    "polling_active": False,
                    "success": task_result.get("success", False),
                    "download_cancelled": st.session_state.get("download_cancelled", False)
                })
                task_completed.clear()  # Reset for next time
                st.rerun()
                return

            # Process any new log entries from the queue
            new_logs = False
            while not log_queue.empty():
                try:
                    log_entry = log_queue.get_nowait()
                    if not self.console.accumulated_output:
                        self.console.accumulated_output = []
                    self.console.accumulated_output.append(log_entry)
                    new_logs = True
                except queue.Empty:
                    break
            
            # Save logs to session state if updated
            if new_logs:
                st.session_state["log_entries"] = self.console.accumulated_output
                # Trigger rerun to update the UI with new logs
                st.rerun()
            
            if query_thread and not query_thread.is_alive():
                try:
                    query_thread.join()
                except Exception as e:
                    st.error(f"Error in background thread: {e}")
                    # Add error to console output
                    if not self.console.accumulated_output:
                        self.console.accumulated_output = []
                    self.console.accumulated_output.append(f"Error: {str(e)}")
                    st.session_state["log_entries"] = self.console.accumulated_output

                st.session_state.update({
                    "is_downloading": False,
                    "query_done": True,
                    "query_thread": None,
                    "polling_active": False
                })

                st.rerun()

            # Always trigger a rerun while polling is active to check for new logs
            if st.session_state.get("polling_active"):
                sleep(0.2)  # Shorter pause for more frequent updates
                st.rerun()

    def render(self):
        if self.settings.selected_workflow == WorkflowType.CONTINUOUS:
            self.continuous_components.render()
            return

        # Initialize tab selection in session state if not exists
        if "active_tab" not in st.session_state:
            st.session_state["active_tab"] = 0  # Default to waveform tab
        
        # Auto-switch to log tab during download if new logs are available
        if st.session_state.get("is_downloading", False) and log_queue.qsize() > 0:
            st.session_state["active_tab"] = 0  # Keep on waveform tab to show real-time logs
        
        # Create tabs for Waveform and Log views
        tab_names = ["📊 Waveform View", "📝 Log View"]
        waveform_tab, log_tab = st.tabs(tab_names)
        
        # Get the current stream and update available channels before rendering filter menu
        current_stream = None
        if self.waveform_display.stream:
            # The stream can be either a list of traces or a Stream object
            # We need to pass the actual stream data to update_available_channels
            current_stream = self.waveform_display.stream
            # Update available channels with the current stream
            self.filter_menu.update_available_channels(current_stream)
        
        # Always render filter menu (sidebar) first
        self.filter_menu.render(current_stream)

        # Handle content based on active tab
        with waveform_tab:
            self._render_waveform_view()
        
        with log_tab:
            # If we're switching to log tab and download is complete, 
            # make sure all logs are transferred from queue to accumulated_output
            if not st.session_state.get("is_downloading", False):
                # Process any remaining logs in the queue
                while not log_queue.empty():
                    try:
                        log_entry = log_queue.get_nowait()
                        if not self.console.accumulated_output:
                            self.console.accumulated_output = []
                        self.console.accumulated_output.append(log_entry)
                    except queue.Empty:
                        break

                # Save to session state
                if self.console.accumulated_output:
                    st.session_state["log_entries"] = self.console.accumulated_output
            
            self._render_log_view()


    def _render_waveform_view(self):
        st.title("Event Arrivals")

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
                width='stretch'
            )

        # Cancel Download button in third column
        with col3:
            if st.button("Cancel Download", 
                        key="cancel_download",
                        disabled=not st.session_state.get("is_downloading", False),
                        width='stretch'):
                stop_event.set()  # Signal cancellation
                st.warning("Cancelling download...")
                st.session_state.update({
                    "download_cancelled": True  # Set cancellation flag
                })
                st.rerun()

        # Download status indicator
        status_container = st.empty()

        # Show appropriate status message
        if get_waveforms_button:
            status_container.info("Starting waveform download...")
            self.waveform_display.retrieve_waveforms()
        elif st.session_state.get("is_downloading"):
            st.spinner("Downloading waveforms... (this may take several minutes)")

            # Display real-time logs in the waveform view during download
            log_container = st.empty()

            # Process any new log entries from the queue
            new_logs = False
            while not log_queue.empty():
                try:
                    log_entry = log_queue.get_nowait()
                    if not self.console.accumulated_output:
                        self.console.accumulated_output = []
                    self.console.accumulated_output.append(log_entry)
                    new_logs = True
                except queue.Empty:
                    break

            # Save logs to session state if updated
            if new_logs or self.console.accumulated_output:
                st.session_state["log_entries"] = self.console.accumulated_output

                # Display logs in the waveform view
                if self.console.accumulated_output:
                    # Add the initial header line if it's not already there
                    if not any("Running run_event" in line for line in self.console.accumulated_output):
                        self.console.accumulated_output.insert(0, "Running run_event\n-----------------")
                        st.session_state["log_entries"] = self.console.accumulated_output

                    #raw_content = "".join(self.console.accumulated_output)
                    #escaped_content = escape(raw_content)
                    content = self.console._preserve_whitespace(''.join(self.console.accumulated_output))

                    log_text = (
                        '<div class="terminal" id="log-terminal" style="max-height: 700px; background-color: black; color: #ffffff; padding: 10px; border-radius: 5px; overflow-y: auto;">'
                        f'<pre style="margin: 0; white-space: pre; tab-size: 4; font-family: \'Courier New\', Courier, monospace; font-size: 14px; line-height: 1.4;">{content}</pre>'
                        '</div>'
                        '<script>'
                        'if (window.terminal_scroll === undefined) {'
                        '    window.terminal_scroll = function() {'
                        '        var terminalDiv = document.getElementById("log-terminal");'
                        '        if (terminalDiv) {'
                        '            terminalDiv.scrollTop = terminalDiv.scrollHeight;'
                        '        }'
                        '    };'
                        '}'
                        'window.terminal_scroll();'
                        '</script>'
                    )

                    log_container.markdown(log_text, unsafe_allow_html=True)
            
            self.render_polling_ui()
        elif st.session_state.get("query_done") and self.waveform_display.stream:
            status_container.success(f"Successfully retrieved waveforms for {len(self.waveform_display.stream)} channels.")
        elif st.session_state.get("query_done"):
            if st.session_state.get("download_cancelled", False):
                status_container.warning("Waveform download was cancelled by user.")
                # Reset the flag after displaying
                st.session_state["download_cancelled"] = False
            else:
                status_container.warning("No waveforms retrieved. Please check your selection criteria and log view.")

        # Display waveforms if they exist
        if self.waveform_display.stream:
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
                    width='stretch'
                )
            else:
                st.button("Download PNG", disabled=True, width='stretch')


    def _render_log_view(self):
        st.title("Waveform Retrieval Logs")
        self.console._init_terminal_style()  # Initialize terminal styling

        # Process any pending log entries from the queue
        logs_updated = False
        while not log_queue.empty():
            try:
                log_entry = log_queue.get_nowait()
                if not self.console.accumulated_output:
                    self.console.accumulated_output = []
                self.console.accumulated_output.append(log_entry)
                logs_updated = True
            except queue.Empty:
                break

        # Save logs to session state if updated
        if logs_updated:
            st.session_state["log_entries"] = self.console.accumulated_output

        if self.console.accumulated_output:
            # Add the initial header line if it's not already there
            if not any("Running run_event" in line for line in self.console.accumulated_output):
                self.console.accumulated_output.insert(0, "Running run_event\n-----------------")
                st.session_state["log_entries"] = self.console.accumulated_output

            content = self.console._preserve_whitespace(''.join(self.console.accumulated_output))

            log_text = (
                '<div class="terminal" id="log-terminal" style="max-height: 700px; background-color: black; color: #ffffff; padding: 10px; border-radius: 5px; overflow-y: auto;">'
                f'<pre style="margin: 0; white-space: pre; tab-size: 4; font-family: \'Courier New\', Courier, monospace; font-size: 14px; line-height: 1.4;">{content}</pre>'
                '</div>'
                '<script>'
                'if (window.terminal_scroll === undefined) {'
                '    window.terminal_scroll = function() {'
                '        var terminalDiv = document.getElementById("log-terminal");'
                '        if (terminalDiv) {'
                '            terminalDiv.scrollTop = terminalDiv.scrollHeight;'
                '        }'
                '    };'
                '}'
                'window.terminal_scroll();'
                '</script>'
            )

            st.markdown(log_text, unsafe_allow_html=True)
        else:
            st.info("Perform a waveform download first :)")

class MissingDataDisplay:
    """A component for displaying information about missing waveform data.

    This class provides a user interface for showing which events or stations
    have missing data and what specific channels are missing.

    Attributes:
        stream (List[Stream]): List of waveform streams.
        missing_data (Dict): Dictionary tracking missing data.
        settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
    """

    def __init__(self, stream: List[Stream], missing_data: Dict[str, Union[List[str], str]], settings: SeismoLoaderSettings):
        """Initialize the MissingDataDisplay component.

        Args:
            stream (List[Stream]): List of waveform streams.
            missing_data (Dict[str, Union[List[str], str]]): Dictionary mapping event IDs to missing data information.
            settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
        """
        self.stream = stream #is this needed? i think we can drop it TODO
        self.missing_data = missing_data
        self.settings = settings
    
    def _format_event_time(self, event) -> str:
        """Format event time in a readable way.

        Args:
            event: Event object containing event information.

        Returns:
            str: Formatted event time string.
        """
        return event.origins[0].time.strftime('%Y-%m-%d %H:%M:%S')

    def _get_missing_events(self):
        """Identify events with no data and their missing channels.

        Returns:
            List[Dict]: List of dictionaries containing information about events
                with missing data, including event ID, time, magnitude, region,
                and missing channels.
        """
        missing_events = []

        # sort events by time
        try:
            catalog = self.settings.event.selected_catalogs.copy() #need copy?
            catalog.events.sort(key=lambda x: getattr(x.origins[0], 'time', UTCDateTime(0)) if x.origins else UTCDateTime(0))
        except Exception as e:
            print("catalog sort problem",e)

        for event in catalog:
            resource_id = str(event.resource_id)

            # Create a string for NSLCs which should have been downloaded (e.g. within search radius) but weren't (e.g. missing on server)
            try:
                if resource_id not in self.missing_data.keys():
                    continue

                results = []
                for station_key, value in self.missing_data[resource_id].items():
                    if value == "ALL":
                        results.append(f"{station_key}.*")  # Indicate all channels missing
                    elif value == '':
                        continue
                    elif isinstance(value, list):
                        if value:  # If list not empty
                            results.extend(value)  # Add all missing channels
                if results:
                    missing_data_str = ','.join(results)
                else:
                    missing_data_str = None

            except Exception as e:
                missing_data_str = None
                print("DEBUG missing data dict issue: ",e)

            if missing_data_str:
                # Combine event ot, mag, region into one column
                event_str = f"{self._format_event_time(event)},  M{event.magnitudes[0].mag:.1f},  {event.extra.get('region', {}).get('value', 'Unknown Region')}"

                # Event completely missing
                missing_events.append({
                    'EQ Resource ID': resource_id,
                    'Event': event_str,
                    'Missing Data': missing_data_str
                })

        return missing_events


    def render(self):
        """Render the missing data display interface.

        This method creates a table showing events with missing data, including:
        - Event information (time, magnitude, region)
        - Missing channel information
        - Dynamic height adjustment based on number of entries
        """
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
                width='stretch',
                height=height,
                hide_index=True
            )


if st.session_state.get("trigger_rerun", False):
    st.session_state["trigger_rerun"] = False  # Reset flag to prevent infinite loops
    st.rerun()  # 🔹 Force UI update