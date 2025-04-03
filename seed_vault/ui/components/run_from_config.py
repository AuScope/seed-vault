import streamlit as st
import os
import jinja2
import threading
import sys
import queue
from pathlib import Path
from html import escape
from time import sleep

from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_main
from seed_vault.utils.constants import DOC_BASE_URL

from .display_log import ConsoleDisplay

# Create a global stop event for cancellation
stop_event = threading.Event()
# Create a global queue for logs
log_queue = queue.Queue()

class RunFromConfigComponent:
    """A component for running seismic data processing from a configuration file.

    This component provides a user interface for loading, editing, and executing
    seismic data processing configurations. It supports real-time logging and
    background processing with cancellation capabilities.

    Attributes:
        settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
        is_editing (bool): Flag indicating if the configuration is being edited.
        edited_config_str (str): The current edited configuration string.
        config_str (str): The original configuration string.
    """

    settings: SeismoLoaderSettings
    is_editing: bool = False
    edited_config_str: str = None
    config_str: str = None

    def __init__(self, settings: SeismoLoaderSettings):
        """Initialize the RunFromConfigComponent.

        Args:
            settings (SeismoLoaderSettings): Configuration settings for seismic data processing.
        """
        self.settings = settings
        self.console = ConsoleDisplay()
        
        # Initialize session state for background processing
        if "config_is_running" not in st.session_state:
            st.session_state.config_is_running = False
        if "config_process_thread" not in st.session_state:
            st.session_state.config_process_thread = None
        if "config_log_entries" not in st.session_state:
            st.session_state.config_log_entries = []

    def process_config_in_background(self, from_file: Path):
        """Process the configuration file in a background thread with logging.

        This method sets up a custom logging system that captures both stdout and stderr,
        processes the configuration file, and handles any errors or cancellations.

        Args:
            from_file (Path): Path to the configuration file to process.

        Note:
            This method runs in a background thread and updates the session state
            with processing status and logs.
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
            print("Starting config processing...")
            
            # Check if already cancelled before starting
            if stop_event.is_set():
                print("Processing was cancelled before it started.")
                return
            
            # Run the main function with stop_event for cancellation
            result = run_main(settings=None, from_file=from_file, stop_event=stop_event)
            
            # Check again for cancellation
            if stop_event.is_set():
                print("Processing was cancelled by user.")
            elif result:
                print("Processing completed successfully.")
            else:
                print("Processing failed or returned no results.")
                
        except Exception as e:
            print(f"Error during processing: {str(e)}")
        finally:
            # Flush any remaining content
            sys.stdout.flush()
            sys.stderr.flush()
            
            # Restore original stdout/stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            
            # Update session state
            st.session_state.config_is_running = False

    def start_background_process(self, from_file: Path):
        """Start the background processing thread for configuration execution.

        This method initializes and starts a new thread to process the configuration
        file, handling state management and thread lifecycle.

        Args:
            from_file (Path): Path to the configuration file to process.

        Note:
            The thread is created as a daemon thread and will be terminated when
            the main program exits.
        """
        # Reset the stop event
        stop_event.clear()
        
        # Reset session state
        st.session_state.cancel_clicked = False
        
        # Clear previous log entries
        st.session_state.config_log_entries = []
        
        # Create and start the thread
        process_thread = threading.Thread(
            target=self.process_config_in_background,
            args=(from_file,),
            daemon=True
        )
        process_thread.start()
        
        # Update session state
        st.session_state.config_process_thread = process_thread
        st.session_state.config_is_running = True

    def render_logs(self, container):
        """Render logs in the provided Streamlit container.

        This method processes any new log entries from the queue and displays them
        in a terminal-style format with auto-scrolling.

        Args:
            container: A Streamlit container object where logs will be displayed.

        Note:
            The logs are displayed in a terminal-style format with custom styling
            and auto-scrolling functionality.
        """
        # Process any new log entries from the queue
        new_logs = False
        while not log_queue.empty():
            try:
                log_entry = log_queue.get_nowait()
                st.session_state.config_log_entries.append(log_entry)
                new_logs = True
            except queue.Empty:
                break
        
        # Display logs
        if st.session_state.config_log_entries:
            # Initialize terminal styling
            self.console._init_terminal_style()
            
            # Prepare log content
            escaped_content = escape('\n'.join(st.session_state.config_log_entries))
            
            log_text = (
                '<div class="terminal" id="config-log-terminal" style="max-height: 600px; overflow-y: auto;">'
                f'<pre style="margin: 0; white-space: pre; tab-size: 4;">{escaped_content}</pre>'
                '</div>'
                '<script>'
                'if (window.terminal_scroll === undefined) {'
                '    window.terminal_scroll = function() {'
                '        var terminalDiv = document.getElementById("config-log-terminal");'
                '        if (terminalDiv) {'
                '            terminalDiv.scrollTop = terminalDiv.scrollHeight;'
                '        }'
                '    };'
                '}'
                'window.terminal_scroll();'
                '</script>'
            )
            
            container.markdown(log_text, unsafe_allow_html=True)
        else:
            container.info("No logs available yet.")

    def check_process_status(self):
        """Check the status of the background process and update UI accordingly.

        This method monitors the background processing thread and updates the UI
        based on the process status, handling completion, errors, and cancellations.

        Note:
            The method triggers UI updates through Streamlit's rerun mechanism
            and manages the session state for process status.
        """
        if st.session_state.config_is_running:
            process_thread = st.session_state.config_process_thread
            
            # Check if thread is still alive
            if process_thread and not process_thread.is_alive():
                try:
                    process_thread.join()
                except Exception as e:
                    st.error(f"Error in background thread: {e}")
                
                # Reset session state
                st.session_state.config_is_running = False
                if "cancel_clicked" in st.session_state:
                    st.session_state.cancel_clicked = False
                
                # Determine final status
                if stop_event.is_set():
                    st.warning("Processing was cancelled by user.")
                else:
                    # Check logs for success/failure indicators
                    logs = '\n'.join(st.session_state.config_log_entries)
                    if "completed successfully" in logs and "error" not in logs.lower():
                        st.success("Processing completed successfully!")
                    else:
                        st.error("Processing encountered errors. Check the logs for details.")
                
                # Force a rerun to update the UI
                st.rerun()
            
            # If still running, trigger a rerun after a short delay to check again
            if st.session_state.config_is_running:
                sleep(0.2)
                st.rerun()

    def _copy_from_main_config(self):
        pass

    def render_config(self):
        """Render the configuration interface with editing capabilities.

        This method creates the main UI for configuration management, including:
        - Configuration file display and editing
        - Validation messages
        - Process controls (run, cancel, edit)
        - Real-time log display

        The interface is split into two columns:
        - Left column: Configuration display and editing
        - Right column: Log display and process status
        """
        current_directory = os.path.dirname(os.path.abspath(__file__))
        target_file = os.path.join(current_directory, '../../service')
        target_file = os.path.abspath(target_file)       
        fileName = "config_direct.cfg"

        validation_placeholder = st.empty()

        c1, c2 = st.columns([1, 1])

        if "is_editing" not in st.session_state:
            st.session_state.is_editing = False

        if "validation_messages" not in st.session_state:
            st.session_state.validation_messages = {"errors": None, "warnings": None}
        
        def validate_config(file_path):
            """Validate the configuration file and store messages."""
            settings = SeismoLoaderSettings.from_cfg_file(cfg_source=file_path)
            errors = None
            warnings = None
            if settings.status_handler.has_errors():
                errors = settings.status_handler.generate_status_report("errors")
            if settings.status_handler.has_warnings():
                warnings = settings.status_handler.generate_status_report("warnings")
            st.session_state.validation_messages["errors"] = errors
            st.session_state.validation_messages["warnings"] = warnings

        def display_validation_messages():
            """Display stored validation messages in the placeholder."""
            with validation_placeholder.container():
                if st.session_state.validation_messages["errors"]:
                    st.error(f'{st.session_state.validation_messages["errors"]}\n\n**Please review the errors. Resolve them before proceeding.**')

                if st.session_state.validation_messages["warnings"]:
                    st.warning(st.session_state.validation_messages["warnings"])

        with open(os.path.join(target_file, fileName), 'r') as f:
            if not st.session_state.validation_messages["errors"] and not st.session_state.validation_messages["warnings"]:
                validate_config(os.path.join(target_file, fileName))
            self.edited_config_str = f.read()
            self.config_str = self.edited_config_str

        display_validation_messages()

        def toggle_editing():
            st.session_state.is_editing = not st.session_state.is_editing

        def reset_config():
            settings = SeismoLoaderSettings.create_default()
            current_directory = os.path.dirname(os.path.abspath(__file__))
            target_file = os.path.join(current_directory, '../../service')
            target_file = os.path.abspath(target_file)
            
            template_loader = jinja2.FileSystemLoader(searchpath=target_file)  
            template_env = jinja2.Environment(loader=template_loader)
            template = template_env.get_template("config_template.cfg")
            config_dict = settings.add_to_config()
            config_str = template.render(**config_dict)    
            st.session_state.edited_config_str = config_str 
            save_config()

        def save_config():
            save_path = os.path.join(target_file, fileName)
            with open(save_path, "w") as f:
                f.write(st.session_state.edited_config_str)
            st.session_state.is_editing = False
            validate_config(save_path)
            with c1:            
                st.success("Configuration saved.")

        def run_process():
            # Start the background process
            self.start_background_process(os.path.join(target_file, fileName))

        def cancel_process():
            # Signal cancellation
            stop_event.set()
            st.warning("Cancelling processing...")
            # Update session state to prevent duplicate UI elements
            st.session_state.cancel_clicked = True
            # Force a rerun to update the UI immediately
            st.rerun()

        # Left column
        with c1:
            if st.session_state.config_is_running:
                st.info("The configuration is currently running. Editing is disabled.")
                
                # Add cancel button when running - use session state to prevent multiple clicks
                if "cancel_clicked" not in st.session_state:
                    st.session_state.cancel_clicked = False
                
                # Only show the cancel button if it hasn't been clicked yet
                if not st.session_state.cancel_clicked:
                    if st.button("Cancel Processing", key="cancel_config_processing"):
                        cancel_process()
                        return  # Exit the function to prevent further processing
                else:
                    st.warning("Cancellation in progress...")
                
                with st.container(height=600):                    
                    st.code(self.config_str, language="python")
            else:
                c11, c12, c13 = st.columns([1,1,1])
                with c11:
                    st.button(
                        "Edit config" if not st.session_state.is_editing else "Stop Editing",
                        on_click=toggle_editing,
                    )
                with c12:
                    st.button(
                        "Reset",
                        on_click=reset_config,
                    )

                with c13:
                    st.link_button("Help", f"{DOC_BASE_URL}/flows/run_from_parameters.html#parameter-reference")

                if st.session_state.is_editing:
                    st.session_state.edited_config_str = st.text_area(
                        "Edit Configuration",
                        self.edited_config_str,
                        height=600,
                    )
                    st.button("Save Config", on_click=save_config)
                else:
                    with st.container(height=600):                    
                        st.code(self.config_str, language="python")
                    if not st.session_state.config_is_running:
                        st.button("Run", disabled=st.session_state.config_is_running, on_click=run_process)

        # Right column
        with c2:
            # Create a container for logs
            log_container = st.empty()
            
            # Display logs
            self.render_logs(log_container)
            
            # Check process status
            if st.session_state.config_is_running:
                self.check_process_status()

    def render(self):
        self.render_config()