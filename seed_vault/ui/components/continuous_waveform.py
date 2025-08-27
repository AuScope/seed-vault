# seed_vault/ui/components/continuous_waveform.py

from typing import List
import streamlit as st
from datetime import datetime, date, timezone
from copy import deepcopy
import threading
import sys
from time import sleep
import queue
from html import escape
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_continuous
from seed_vault.ui.components.display_log import ConsoleDisplay
from seed_vault.service.utils import convert_to_datetime, get_time_interval, shift_time, parse_inv
from seed_vault.ui.app_pages.helpers.common import save_filter

# Create a global stop event for cancellation
stop_event = threading.Event()
# Create a global queue for logs
log_queue = queue.Queue()
# Track threading task status
task_completed = threading.Event()
task_result = {"success": False}

class ContinuousFilterMenu:
    """A menu component for filtering and controlling continuous waveform data.

    This class provides a user interface for managing continuous waveform data
    retrieval, including time range selection and station filtering.

    Attributes:
        settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
        old_settings (SeismoLoaderSettings): Previous state of settings for change detection.
        old_time_state (dict): Previous time range state for change detection.
        last_button_pressed (str): Last button interaction for UI state management.
        todo_nets (List[str]): List of networks to process.
    """

    def __init__(self, settings: SeismoLoaderSettings):
        """Initialize the ContinuousFilterMenu.

        Args:
            settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
        """
        self.settings = settings
        self.old_settings = deepcopy(settings)
        # Track previous time state
        self.old_time_state = {
            'start_time': self.settings.station.date_config.start_time,
            'end_time': self.settings.station.date_config.end_time
        }
        self.last_button_pressed = None
        self.todo_nets = None
        
        # Check if date range is valid
        self.validate_date_range()

    def validate_date_range(self):
        """Validate that the selected date range is valid.

        This method checks that the end time is not earlier than the start time
        and updates the session state accordingly.

        Note:
            The validation result is stored in st.session_state["date_range_valid"].
        """
        start_time = self.settings.station.date_config.start_time
        end_time = self.settings.station.date_config.end_time
        
        # Check if dates exist
        if start_time is None or end_time is None:
            st.session_state["date_range_valid"] = False
            return
        
        # Convert to datetime objects with UTC timezone
        try:
            # Handle string inputs
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time).replace(tzinfo=timezone.utc)
            # Handle datetime inputs
            elif hasattr(start_time, 'tzinfo'):
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
            
            if isinstance(end_time, str):
                end_time = datetime.fromisoformat(end_time).replace(tzinfo=timezone.utc)
            elif hasattr(end_time, 'tzinfo'):
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=timezone.utc)
            
            # Now we can safely compare
            st.session_state["date_range_valid"] = end_time > start_time
        except (ValueError, AttributeError, TypeError):
            # Catch any conversion or comparison errors
            st.session_state["date_range_valid"] = False


    def refresh_filters(self):
        """Check for changes in time range and settings, trigger UI updates.

        This method compares current settings with previous state and triggers
        a UI refresh if changes are detected. It also handles saving of settings.

        Note:
            The method uses Streamlit's rerun mechanism to update the UI
            when changes are detected.
        """
        current_time_state = {
            'start_time': self.settings.station.date_config.start_time,
            'end_time': self.settings.station.date_config.end_time
        }
        
        # Check if time state changed - use deep comparison for datetime objects
        # it doesn't seem to stay updated always.. possible not working correctly in __init__
        time_changed = (current_time_state['start_time'] != self.old_time_state['start_time'] or 
                       current_time_state['end_time'] != self.old_time_state['end_time'])
        
        if time_changed:
            self.old_time_state = {
                'start_time': current_time_state['start_time'],
                'end_time': current_time_state['end_time']
            }
            # Validate date range whenever time changes
            self.validate_date_range()
            save_filter(self.settings)
            st.rerun()

        # Check if other settings changed
        changes = self.settings.has_changed(self.old_settings)
        if changes.get('has_changed', False):
            self.old_settings = deepcopy(self.settings)
            save_filter(self.settings)
            st.rerun()

    def refresh_filters_OLD(self):
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
        """Render the continuous waveform filter menu interface.

        This method creates the UI for continuous waveform data management, including:
        - Time range selection with year/month/week controls
        - Date and time input fields
        - Quick selection buttons for common time ranges
        - Network/station/location/channel information display

        The interface is organized in expandable sections:
        - Time Range Adjustment
        - Submitted NSLCs Information

        Note:
            The interface provides both manual input and quick selection options
            for time range management.
        """
        st.sidebar.title("Download Parameters")

        ## Get the list of items about to be downloaded
        # ...For some reason this snippet only works in render
        #    & we don't want to re-run it needlessly
        if not self.todo_nets:
            self.todo_nets,self.todo_stas,self.todo_locs,self.todo_chas = \
            parse_inv(self.settings.station.selected_invs)
        
        with st.sidebar.expander("Adjust Time Range?", expanded=True):
            start_date, start_time = convert_to_datetime(self.settings.station.date_config.start_time)
            end_date, end_time = convert_to_datetime(self.settings.station.date_config.end_time)
            min_date = date(1800,1,1)
            max_date = date(2100,1,1)

            # Row 1: Year controls
            col1, col2, col3, col4 = st.columns(4)
            # Row 2: Month controls
            col5, col6, col7, col8 = st.columns(4)
            # Row 3: Week controls
            col9, col10, col11, col12 = st.columns(4)
            # Row 4: Day controls
            #col13, col14, col15, col16 = st.columns(4)
            
            # Year controls
            with col1:
                if st.button("-Year", key="start-year-minus"):
                    self.settings.station.date_config.start_time = shift_time(
                        self.settings.station.date_config.start_time, 'year', -1)
                    self.validate_date_range()
                    self.refresh_filters()
            
            with col2:
                if st.button("+Year", key="start-year-plus"):
                    self.settings.station.date_config.start_time = shift_time(
                        self.settings.station.date_config.start_time, 'year', 1)
                    self.validate_date_range()
                    self.refresh_filters()
            with col3:
                if st.button("-Year", key="end-year-minus"):
                    self.settings.station.date_config.end_time = shift_time(
                        self.settings.station.date_config.end_time, 'year', -1)
                    self.validate_date_range()
                    self.refresh_filters()
            
            with col4:
                if st.button("+Year", key="end-year-plus"):
                    self.settings.station.date_config.end_time = shift_time(
                        self.settings.station.date_config.end_time, 'year', 1)
                    self.validate_date_range()
                    self.refresh_filters()                   
            
            # Month controls
            with col5:
                if st.button("-Month", key="start-month-minus"):
                    self.settings.station.date_config.start_time = shift_time(
                        self.settings.station.date_config.start_time, 'month', -1)
                    self.validate_date_range()
                    self.refresh_filters()
            
            with col6:
                if st.button("+Month", key="start-month-plus"):
                    self.settings.station.date_config.start_time = shift_time(
                        self.settings.station.date_config.start_time, 'month', 1)
                    self.validate_date_range()
                    self.refresh_filters()
            with col7:
                if st.button("-Month", key="end-month-minus"):
                    self.settings.station.date_config.end_time = shift_time(
                        self.settings.station.date_config.end_time, 'month', -1)
                    self.validate_date_range()
                    self.refresh_filters()
            
            with col8:
                if st.button("+Month", key="end-month-plus"):
                    self.settings.station.date_config.end_time = shift_time(
                        self.settings.station.date_config.end_time, 'month', 1)
                    self.validate_date_range()
                    self.refresh_filters()                    
            
            # Week controls
            with col9:
                if st.button("-Week", key="start-week-minus"):
                    self.settings.station.date_config.start_time = shift_time(
                        self.settings.station.date_config.start_time, 'week', -1)
                    self.validate_date_range()
                    self.refresh_filters()
            
            with col10:
                if st.button("+Week", key="start-week-plus"):
                    self.settings.station.date_config.start_time = shift_time(
                        self.settings.station.date_config.start_time, 'week', 1)
                    self.validate_date_range()
                    self.refresh_filters()
            with col11:
                if st.button("-Week", key="end-week-minus"):
                    self.settings.station.date_config.end_time = shift_time(
                        self.settings.station.date_config.end_time, 'week', -1)
                    self.validate_date_range()
                    self.refresh_filters()
            
            with col12:
                if st.button("+Week", key="end-week-plus"):
                    self.settings.station.date_config.end_time = shift_time(
                        self.settings.station.date_config.end_time, 'week', 1)
                    self.validate_date_range()
                    self.refresh_filters()
            
            # Day controls (...overkill)
            """
            with col13:
                if st.button("- Day", key="start-day-minus"):
                    self.settings.station.date_config.start_time = shift_time(
                        self.settings.station.date_config.start_time, 'day', -1)
                    self.refresh_filters()
            
            with col14:
                if st.button("+ Day", key="start-day-plus"):
                    self.settings.station.date_config.start_time = shift_time(
                        self.settings.station.date_config.start_time, 'day', 1)
                    self.refresh_filters()
            with col15:
                if st.button("- Day", key="end-day-minus"):
                    self.settings.station.date_config.end_time = shift_time(
                        self.settings.station.date_config.end_time, 'day', -1)
                    self.refresh_filters()
            
            with col16:
                if st.button("+ Day", key="end-day-plus"):
                    self.settings.station.date_config.end_time = shift_time(
                        self.settings.station.date_config.end_time, 'day', 1)
                    self.refresh_filters()
            """


            c1, c2 = st.columns([1,1])
            with c1:
                new_start_date = st.date_input("Start Date", min_value=min_date, max_value=max_date, value=start_date)
                new_start_time = st.time_input("Start Time (UTC)", value=start_time)
                
                # Handle cases where only date or only time has changed
                date_changed = new_start_date != start_date
                time_changed = new_start_time != start_time
                
                if date_changed or time_changed:
                    new_start = datetime.combine(new_start_date, new_start_time)
                    self.settings.station.date_config.start_time = new_start
                    self.last_button_pressed = None
                    self.validate_date_range()
                    self.refresh_filters()

            with c2:
                new_end_date = st.date_input("End Date", min_value=min_date, max_value=max_date, value=end_date)                
                new_end_time = st.time_input("End Time (UTC)", value=end_time)
                
                # Handle cases where only date or only time has changed
                date_changed = new_end_date != end_date
                time_changed = new_end_time != end_time
                
                if date_changed or time_changed:
                    new_end = datetime.combine(new_end_date, new_end_time)
                    self.settings.station.date_config.end_time = new_end
                    self.last_button_pressed = None
                    self.validate_date_range()
                    self.refresh_filters()

            # Display validation message if date range is invalid
            if not st.session_state.get("date_range_valid", True):
                st.error("End time must be > start time")

            # also keep the last month/week/day options
            c21,c22,c23 = st.columns([1,1,1])
            with c21:
                if st.button('Last Month', key="station-set-last-month"):
                    end_time, start_time = get_time_interval('month')
                    self.settings.station.date_config.end_time = end_time
                    self.settings.station.date_config.start_time = start_time
                    self.refresh_filters()

            with c22:
                if st.button('Last Week', key="station-set-last-week"):
                    end_time, start_time = get_time_interval('week')
                    self.settings.station.date_config.end_time = end_time
                    self.settings.station.date_config.start_time = start_time
                    self.refresh_filters()

            with c23:
                if st.button('Last Day', key="station-set-last-day"):
                    end_time, start_time = get_time_interval('day')
                    self.settings.station.date_config.end_time = end_time
                    self.settings.station.date_config.start_time = start_time
                    self.refresh_filters()

        with st.sidebar.expander("Submitted NSLCs:", expanded=True):
            st.caption(f"Networks: {','.join(self.todo_nets)  if self.todo_nets else 'None'}")
            st.caption(f"Stations: {','.join(self.todo_stas)  if self.todo_stas else 'None'}")
            st.caption(f"Locations: {','.join([loc if loc != '' else '--' for loc in self.todo_locs]) if self.todo_locs else 'None'}")
            st.caption(f"Channels: {','.join(self.todo_chas)  if self.todo_chas else 'None'}")


class ContinuousDisplay:
    """A component for displaying and managing continuous waveform data.

    This class handles the display and processing of continuous waveform data,
    including data retrieval, logging, and UI updates.

    Attributes:
        settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
        filter_menu (ContinuousFilterMenu): Menu component for filtering waveforms.
        console (ConsoleDisplay): Console for logging output.
    """

    def __init__(self, settings: SeismoLoaderSettings, filter_menu: ContinuousFilterMenu):
        """Initialize the ContinuousDisplay component.

        Args:
            settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
            filter_menu (ContinuousFilterMenu): Menu component for filtering waveforms.
        """
        self.settings = settings
        self.filter_menu = filter_menu
        self.console = ConsoleDisplay()
        
    def process_continuous_data(self):
        """Process continuous waveform data in a background thread with logging.

        This method sets up a custom logging system, retrieves continuous waveform data,
        and handles any errors or cancellations during the process.

        Note:
            The method updates the session state with processing status and logs.
        """
        # Custom stdout/stderr handler that writes to both the original streams and our queue
        class QueueLogger:
            def __init__(self, original_stream, queue):
                self.original_stream = original_stream
                self.queue = queue
                self.buffer = ""

            def write(self, text):
                self.original_stream.write(text)
                self.buffer += text
                if '\n' in text:
                    lines = self.buffer.split('\n')
                    for line in lines[:-1]:  # All complete lines
                        if line:  # Skip empty lines
                            self.queue.put(line)
                    self.buffer = lines[-1]  # Keep any partial line
                # Also handle case where no newline but we have content
                elif text and len(self.buffer) > 80:  # Buffer getting long, flush it
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
            # Print initial message to show logging is working
            print("Starting continuous waveform download process...")

            # Run the continuous download with stop_event for cancellation
            result = run_continuous(self.settings, stop_event)
            if result:
                success = True
                print("Download completed successfully.")
            else:
                success = False
                print("Download failed or was cancelled.")

            task_result["success"] = success

        except Exception as e:
            print(f"Error: {str(e)}")  # This will be captured in the output
            task_result["success"] = False         
        finally:
            # Flush any remaining content
            sys.stdout.flush()
            sys.stderr.flush()

            # Restore original stdout/stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            
            task_completed.set()
        
    def render(self):
        """Render the continuous waveform display interface.

        This method creates the main UI for continuous waveform visualization, including:
        - Download controls
        - Status indicators
        - Real-time log display
        - Progress tracking
        """
        st.title("Continuous Waveform Archiving")
        
        # Create three columns for the controls
        col1, col2 = st.columns(2)
        
        # Get Waveforms button in first column
        with col1:
            get_waveforms_button = st.button(
                "Download Waveforms",
                key="download_continuous",
                disabled=st.session_state.get("is_downloading", False) or not st.session_state.get("date_range_valid", True),
                width='stretch'
            )

        # Cancel Download button in second column
        with col2:
            if st.button("Cancel Download", 
                        key="cancel_continuous_download",
                        disabled=not st.session_state.get("is_downloading", False),
                        width='stretch'):
                stop_event.set()  # Signal cancellation
                st.warning("Cancelling download...")
                st.session_state.update({
                    "is_downloading": False,
                    "polling_active": False,
                    "download_cancelled": True  # Add this flag to track cancellation
                })
                st.rerun()

        # Download status indicator
        status_container = st.empty()
        
        # Show appropriate status message
        if get_waveforms_button:
            status_container.info("Starting continuous waveform download...")
            self.retrieve_waveforms()
        elif st.session_state.get("is_downloading"):
            st.spinner("Downloading continuous waveforms... (this may take a long time!)")
            
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
                    if not any("Running run_continuous" in line for line in self.console.accumulated_output):
                        self.console.accumulated_output.insert(0, "Running run_continuous\n-----------------------")
                        st.session_state["log_entries"] = self.console.accumulated_output

                    # Initialize terminal styling
                    self.console._init_terminal_style()

                    content = self.console._preserve_whitespace('\n'.join(self.console.accumulated_output))

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
        elif st.session_state.get("download_cancelled"):
            status_container.warning("Download was cancelled by user.")
        elif st.session_state.get("query_done"):
            status_container.success("Continuous data downloading completed successfully!")

    def retrieve_waveforms(self):
        """Initiate continuous waveform retrieval in a background thread.

        This method starts a new thread for continuous waveform data retrieval and
        updates the UI state accordingly.

        Note:
            The method handles thread creation, state management, and UI updates.
        """
        stop_event.clear()  # Reset cancellation flag
        task_completed.clear() # Reset completion flag

        # Start thread with the wrapper function
        st.session_state["query_thread"] = threading.Thread(
            target=self.process_continuous_data,
            daemon=True
        )
        st.session_state["query_thread"].start()
        
        st.session_state.update({
            "is_downloading": True,
            "query_done": False,
            "polling_active": True,
            "download_cancelled": False
        })
        
        st.rerun()

class ContinuousComponents:
    """A component for managing continuous waveform data processing.

    This class coordinates the interaction between the filter menu, display,
    and logging components for continuous waveform data processing.

    Attributes:
        settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
        filter_menu (ContinuousFilterMenu): Menu component for filtering waveforms.
        display (ContinuousDisplay): Display component for waveform visualization.
        console (ConsoleDisplay): Console for logging output.
    """

    def __init__(self, settings: SeismoLoaderSettings):
        """Initialize the ContinuousComponents.

        Args:
            settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
        """
        self.settings = settings
        self.filter_menu = ContinuousFilterMenu(settings)
        self.display = ContinuousDisplay(settings, self.filter_menu)
        self.console = ConsoleDisplay()
        
        # Initialize console with logs from session state if they exist
        if "log_entries" in st.session_state and st.session_state["log_entries"]:
            self.console.accumulated_output = st.session_state["log_entries"]
        
        # Pass console to ContinuousDisplay
        self.display.console = self.console
        
        # Initialize session state
        required_states = {
            "is_downloading": False,
            "query_done": False,
            "polling_active": False,
            "query_thread": None,
            "trigger_rerun": False,
            "log_entries": [],
            "date_range_valid": True
        }
        for key, val in required_states.items():
            if key not in st.session_state:
                st.session_state[key] = val
    
    def render_polling_ui(self):
        """Handle UI updates while monitoring background thread status.

        This method processes log entries from the queue and updates the UI
        based on the background thread's status.

        Note:
            The method uses Streamlit's rerun mechanism to update the UI
            when new logs are available or when the thread status changes.
        """
        if st.session_state.get("is_downloading", False):
            # Check if the task has completed
            if task_completed.is_set():
                # Update session state from the main thread
                st.session_state.update({
                    "is_downloading": False,
                    "query_done": True,
                    "query_thread": None,
                    "polling_active": False,
                    "success": task_result.get("success", False)
                })
                task_completed.clear()  # Reset for next time
                st.rerun()
                return

            query_thread = st.session_state.get("query_thread")
            
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
        """Render the complete continuous waveform interface.

        This method creates the main UI for continuous waveform processing, including:
        - Download and log view tabs
        - Filter menu in sidebar
        - Real-time status updates
        - Log display and management
        """
        # Initialize tab selection in session state if not exists
        if "continuous_active_tab" not in st.session_state:
            st.session_state["continuous_active_tab"] = 0  # Default to download tab
        
        # Auto-switch to log tab during download if new logs are available
        if st.session_state.get("is_downloading", False) and log_queue.qsize() > 0:
            st.session_state["continuous_active_tab"] = 0  # Keep on download tab to show real-time logs
        
        # Create tabs for Download and Log views
        tab_names = ["📊 Download View", "📝 Log View"]
        download_tab, log_tab = st.tabs(tab_names)
        
        # Always render filter menu (sidebar) first
        self.filter_menu.render()

        # Handle content based on active tab
        with download_tab:
            self.display.render()
            # Handle polling for background thread updates
            self.render_polling_ui()
        
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
            
            # Render log view
            st.title("Continuous Waveform Logs")
            
            if self.console.accumulated_output:
                # Initialize terminal styling
                self.console._init_terminal_style()
                
                # Display logs
                content = self.console._preserve_whitespace('\n'.join(self.console.accumulated_output))
                
                log_text = (
                    '<div class="terminal" id="log-terminal">'
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
                st.info("No logs available. Start a download to generate logs.")