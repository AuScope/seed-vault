# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
sys.path.insert(0, os.path.abspath('..'))  # Ensure Sphinx finds your project

extensions = [
    "sphinx.ext.autodoc",          # Automatically generate docs from docstrings
    "sphinx.ext.napoleon",         # Support Google/NumPy docstrings
    "sphinx.ext.viewcode",         # Add links to source code
    "sphinx.ext.intersphinx",      # Reference external documentation
    "myst_parser",                 # Enable Markdown support
    "sphinx_autodoc_typehints",    # Include Python type hints in docs
]

# Set Theme
html_theme = "sphinx_rtd_theme"


# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Seed Vault'
copyright = '2025, Ben Motevalli, Neda Taherifar, Yunlong Li, Robert Pickle, Vincent Fazio, Pavel Golodoniuc'
author = 'Ben Motevalli, Neda Taherifar, Yunlong Li, Robert Pickle, Vincent Fazio, Pavel Golodoniuc'
release = '0.1.2'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = []

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'alabaster'
html_static_path = ['_static']
