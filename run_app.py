from streamlit.web import cli
import os

script_path = os.path.join(os.path.dirname(__file__), "seed_vault/ui/1_🌎_main_flows.py")

if __name__ == '__main__':
    cli._main_run_clExplicit(script_path, is_hello=False)   
    # cli._main_run_clExplicit('seed_vault/ui/1_🌎_main_flows.py', is_hello=False)
