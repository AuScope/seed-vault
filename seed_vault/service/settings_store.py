"""Loading and persisting app configuration, independent of any UI toolkit.

The GUI keeps two config files next to the service module:

* ``config.cfg``         - the interactive workflow settings (filters, clients, paths)
* ``config_direct.cfg``  - the "Run from Parameters" config, edited as text
"""
import os
from typing import Optional

import jinja2

from seed_vault.models.config import SeismoLoaderSettings

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_CONFIG_PATH = os.path.join(SERVICE_DIR, "config.cfg")
DIRECT_CONFIG_PATH = os.path.join(SERVICE_DIR, "config_direct.cfg")
TEMPLATE_NAME = "config_template.cfg"


def clear_geo_constraints(settings: SeismoLoaderSettings) -> SeismoLoaderSettings:
    if settings.event:
        settings.event.geo_constraint = []
    if settings.station:
        settings.station.geo_constraint = []
    return settings


def load_settings(path: str = APP_CONFIG_PATH, empty_geo: bool = True) -> SeismoLoaderSettings:
    settings = SeismoLoaderSettings.from_cfg_file(path)
    settings.client_url_mapping.load()
    if empty_geo:
        clear_geo_constraints(settings)
    return settings


def render_config(settings: SeismoLoaderSettings) -> str:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(searchpath=SERVICE_DIR))
    return env.get_template(TEMPLATE_NAME).render(**settings.add_to_config())


def save_settings(settings: SeismoLoaderSettings, path: str = APP_CONFIG_PATH) -> str:
    with open(path, "w") as f:
        f.write(render_config(settings))
    return path


def default_settings() -> SeismoLoaderSettings:
    return SeismoLoaderSettings.create_default()


def validate_config_file(path: str) -> "tuple[Optional[str], Optional[str]]":
    """Return (errors, warnings) report strings for a config file (None when clean)."""
    s = SeismoLoaderSettings.from_cfg_file(cfg_source=path)
    errors = s.status_handler.generate_status_report("errors") if s.status_handler.has_errors() else None
    warnings = s.status_handler.generate_status_report("warnings") if s.status_handler.has_warnings() else None
    return errors, warnings


# Sections of the config owned by each part of the GUI. Saving only your own
# sections means the Settings page and an in-progress workflow can't overwrite
# each other's changes on disk.
WORKFLOW_SECTIONS = ("event", "station", "waveform", "selected_workflow", "download_type")
APP_SECTIONS = ("db_path", "sds_path", "processing", "auths")


def save_sections(settings: SeismoLoaderSettings, sections, path: str = APP_CONFIG_PATH) -> str:
    """Write only ``sections`` of ``settings`` to disk, keeping everything else as stored."""
    try:
        current = load_settings(path, empty_geo=False)
    except Exception:
        current = default_settings()
    for name in sections:
        setattr(current, name, getattr(settings, name))
    return save_settings(current, path)


def refresh_sections(settings: SeismoLoaderSettings, sections=APP_SECTIONS, path: str = APP_CONFIG_PATH):
    """Pull ``sections`` from disk into ``settings`` (e.g. paths/credentials edited on the Settings page)."""
    try:
        current = load_settings(path, empty_geo=False)
    except Exception:
        return settings
    for name in sections:
        setattr(settings, name, getattr(current, name))
    settings.client_url_mapping.load()
    return settings
