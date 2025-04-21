from io import StringIO
import streamlit as st
import threading
from time import sleep
from contextlib import redirect_stdout, redirect_stderr
from typing import Callable
from queue import Queue
from html import escape

class ConsoleDisplay:
    def __init__(self):
        self.last_position = 0
        self.accumulated_output = []
        
    def _init_terminal_style(self):
        """Initialize terminal styling"""
        st.markdown("""
            <style>
                /* Terminal container styling */
                .terminal {
                    background-color: black;
                    color: #ffffff;
                    padding: 10px;
                    border-radius: 5px;
                    height: 800px;
                    overflow-y: auto;
                    white-space: pre;
                    tab-size: 4;
                }
                
                /* Terminal text styling */
                .terminal pre,
                .terminal code,
                .terminal span,
                .terminal div {
                    margin: 0;
                    white-space: pre-wrap;
                    word-wrap: break-word;
                    tab-size: 4;
                    font-family: 'Courier New', Courier, monospace !important;
                    font-size: 14px !important;
                    line-height: 1.4 !important;
                }
                
                /* Ensure consistent scrolling behavior */
                .stMarkdown {
                    overflow-y: auto;
                    max-height: 800px;
                }
                
                /* Ensure consistent font size in all contexts */
                .terminal * {
                    font-size: 14px !important;
                }
            </style>
        """, unsafe_allow_html=True)

    def _preserve_whitespace(self, text: str) -> str:
        """
        Preserve leading whitespace by converting spaces to non-breaking spaces
        but only at the start of each line
        """
        lines = text.splitlines(True)  # Keep line endings
        preserved_lines = []

        for line in lines:
            # Count leading spaces
            leading_space_count = len(line) - len(line.lstrip(' '))
            if leading_space_count > 0:
                # Replace leading spaces with &nbsp;
                preserved_line = '&nbsp;' * leading_space_count + escape(line[leading_space_count:])
                preserved_lines.append(preserved_line)
            else:
                preserved_lines.append(escape(line))

        return ''.join(preserved_lines)

    def _update_logs(self, output_buffer: StringIO, log_container: st.empty):
        """Update logs in terminal style"""
        output_buffer.seek(self.last_position)
        new_output = output_buffer.read()

        if new_output:
            # Add new output to accumulated output
            self.accumulated_output.append(new_output)

            # Preserve whitespace while escaping content
            preserved_content = self._preserve_whitespace(''.join(self.accumulated_output))

            # Create terminal display
            log_text = (
                '<div class="terminal" id="log-terminal">'
                f'<pre>{preserved_content}</pre>'
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

            # Update the display
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
                    print("Starting downloads...")

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
                        sleep(0.05)

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