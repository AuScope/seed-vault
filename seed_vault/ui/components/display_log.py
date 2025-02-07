from io import StringIO
import streamlit as st
import threading
import time
from contextlib import redirect_stdout, redirect_stderr
from typing import Callable, List
from queue import Queue

class ConsoleDisplay:
    def __init__(self):
        self.last_position = 0
        self.accumulated_output = []
        
    def _init_terminal_style(self):
        """Initialize terminal styling"""
        st.markdown("""
            <style>
                .terminal {
                    background-color: black;
                    color: #00ff00;
                    font-family: 'Courier New', Courier, monospace;
                    padding: 10px;
                    border-radius: 5px;
                    height: 400px;
                    overflow-y: auto;
                }
                .stMarkdown {
                    overflow-y: auto;
                    max-height: 400px;
                }
            </style>
        """, unsafe_allow_html=True)

    def _update_logs(self, output_buffer: StringIO, log_container: st.empty):
        """Update logs in terminal style"""
        output_buffer.seek(self.last_position)
        new_output = output_buffer.read()
        
        if new_output:
            # Split new output into lines and add to accumulated output
            new_lines = new_output.splitlines()
            self.accumulated_output.extend(new_lines)
            
            # Create terminal display with auto-scroll
            log_text = (
                '<div class="terminal" id="log-terminal">'
                '<pre>{}</pre>'
                '</div>'
                '<script>'
                'var terminalDiv = document.getElementById("log-terminal");'
                'if (terminalDiv) {{'
                '    var observer = new MutationObserver(function(mutations) {{'
                '        terminalDiv.scrollTop = terminalDiv.scrollHeight;'
                '    }});'
                '    observer.observe(terminalDiv, {{ childList: true, subtree: true }});'
                '    terminalDiv.scrollTop = terminalDiv.scrollHeight;'
                '}}'
                '</script>'
            ).format('\n'.join(self.accumulated_output))
            
            log_container.markdown(log_text, unsafe_allow_html=True)
            
            # Update buffer position
            self.last_position = output_buffer.tell()

    def run_with_logs(self, process_func: Callable, status_message: str = "Processing...") -> tuple[bool, str]:
        """
        Run a process with terminal-style logging
        
        Args:
            process_func: Function to execute
            status_message: Status message to display
            
        Returns:
            tuple[bool, str]: (success status, error message if any)
        """
        output_buffer = StringIO()
        self.last_position = 0
        self.accumulated_output = []
        error_message = ""
        
        status = st.status(status_message, expanded=True)
        with status:
            self._init_terminal_style()
            log_container = st.empty()
            log_container.markdown('<div class="terminal"></div>', unsafe_allow_html=True)
            
            try:
                with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
                    print("Starting process...")
                    
                    # Create a queue to get the return value from the thread
                    result_queue = Queue()
                    
                    def wrapped_func():
                        try:
                            result = process_func()
                            result_queue.put(("success", result))
                        except Exception as e:
                            result_queue.put(("error", str(e)))
                    
                    process_thread = threading.Thread(target=wrapped_func)
                    process_thread.start()
                    
                    while process_thread.is_alive():
                        self._update_logs(output_buffer, log_container)
                        time.sleep(0.1)
                    
                    process_thread.join()
                    self._update_logs(output_buffer, log_container)
                    
                    # Get the result from the queue
                    status, result = result_queue.get()
                    if status == "error":
                        return False, result
                    return True, ""

            except Exception as e:
                error_message = str(e)
                return False, error_message 