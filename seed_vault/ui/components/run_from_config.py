import streamlit as st
import os
import jinja2
from pathlib import Path

from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_main

from .display_log import ConsoleDisplay


class RunFromConfigComponent:
    settings: SeismoLoaderSettings
    is_editing: bool = False
    edited_config_str: str = None
    config_str: str = None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings  = settings
        self.console   = ConsoleDisplay()


    def process_run_main(self, from_file: Path):
        """Process direct run from config with console output"""
        def process_func():
            # No need to set values as they're already in settings
            return run_main(settings=None, from_file=from_file)
            
        return self.console.run_with_logs(
            process_func=process_func,
            status_message="Running the queries..."
        )


    def _copy_from_main_config(self):
        pass

    def render_config(self):

        current_directory = os.path.dirname(os.path.abspath(__file__))
        target_file = os.path.join(current_directory, '../../service')
        target_file = os.path.abspath(target_file)       
        fileName = "config_direct.cfg"

        validation_placeholder = st.empty()

        c1, c2 = st.columns([1, 1])

        if "is_editing" not in st.session_state:
            st.session_state.is_editing = False

        if "is_running" not in st.session_state:
            st.session_state.is_running = False

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
            st.session_state.is_running = True

        # Left column
        with c1:
            if st.session_state.is_running:
                st.info("The configuration is currently running. Editing is disabled.")
                with st.container(height=600):                    
                    st.code(self.config_str, language="python")
            else:
                c11, c12 = st.columns([1,1])
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
                    if not st.session_state.is_running:
                        st.button("Run", disabled=st.session_state.is_running, on_click=run_process)


        with c2:
          
            if st.session_state.is_running:
                success = self.process_run_main(from_file=os.path.join(target_file, fileName))
                    # run_main(settings=None, from_file=os.path.join(target_file, fileName))
                if success:
                    st.success("Query data processing completed successfully!")
                else:
                    st.error("Error processing the queries. Check the logs for details.")
                st.session_state.is_running = False

    def render(self):
        self.render_config()