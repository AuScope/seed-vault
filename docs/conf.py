# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.pardir)))
# sys.path.insert(0, os.path.abspath(os.path.join(os.pardir, 'seed_vault')))


# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

autoclass_content = "both"  # include both class docstring and __init__

autodoc_default_flags = [
        # Make sure that any autodoc declarations show the right members
        "members",
        "inherited-members",
        "private-members",
        "show-inheritance",
]
autosummary_generate = True  # Make _autosummary files and include them


extensions = [
    "sphinx.ext.todo", 
    "sphinx.ext.viewcode", 
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme' # 'sphinx_material'
html_static_path = ['_static']
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 4,
    "style_external_links": True,
    "titles_only": False
}

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Seed Vault'
copyright = '2025, CSIRO'
author = 'Ben Motevalli, Neda Taherifar, Yunlong Li, Robert Pickle, Vincent Fazio, Pavel Golodoniuc'
release = '0.1.2'

