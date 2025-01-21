import streamlit as st
import os
import jinja2

from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_main


class RunFromConfigComponent:
    settings: SeismoLoaderSettings
    is_editing: bool = False
    edited_config_str: str = None
    config_str: str = None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings  = settings


    def _copy_from_main_config(self):
        pass

    def render_config(self):

        current_directory = os.path.dirname(os.path.abspath(__file__))
        target_file = os.path.join(current_directory, '../../service')
        target_file = os.path.abspath(target_file)
        template_loader = jinja2.FileSystemLoader(searchpath=target_file)  
        template_env = jinja2.Environment(loader=template_loader)
        template = template_env.get_template("config_template.cfg")

        # INITIATE
        if self.config_str is None or self.config_str == "":
            config_dict = self.settings.add_to_config()
            self.config_str = template.render(**config_dict)
            self.edited_config_str = self.config_str
        
        fileName = "config_direct.cfg"
        

        c1, c2 = st.columns([1, 1])
        
        
        with c1:
            self.edited_config_str = st.text_area("Edit Configuration", self.edited_config_str, height=600)
            c11, c12 = st.columns([1, 1])
            with c11:
                if st.button("Save Config"):
                    save_path = os.path.join(target_file, fileName)
                    with open(save_path, "w") as f:
                        f.write(self.edited_config_str)
                    st.success(f"Configuration saved.")
                    self.config_str = self.edited_config_str

            with c12:
                if st.button("Run"):
                    run_main(settings=None, from_file=os.path.join(target_file, fileName))
                    

            # is_editing = st.toggle("Edit config", value=False)
            # if is_editing:
            #     self.edited_config_str = st.text_area("Edit Configuration", self.edited_config_str, height=600)
            #     if st.button("Save Config"):
            #         save_path = os.path.join(target_file, fileName)
            #         with open(save_path, "w") as f:
            #             f.write(self.edited_config_str)
            #         st.success(f"Configuration saved.")
            #         self.config_str = self.edited_config_str
            # else:
            #     st.code(self.config_str, language="python")
    

    def render(self):
        self.render_config()