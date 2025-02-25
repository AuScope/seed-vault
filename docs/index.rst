.. Seed Vault documentation master file, created by
   sphinx-quickstart on Fri Feb 14 11:47:19 2025.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to Seed Vault Documentation
===================================

.. image:: screenshots/Step1.png
  :width: 600
  :alt: Screenshot of Step 1 selecting events via world map

A seismology GUI application that is

* Open Source, built to service the FDSN community
* Access every kind of seismic data
* Designed for expert and novice alike

Features
--------

* Download & view EQ arrival data via a station-to-event OR an event-to-station search
* Quickly download and archive bulk continuous data, saving your progress along the way
* View and plot event arrivals
* A CLI scripting tool to automate common jobs
* Search, export, or import earthquake event catalogs and station metadata
* Download restricted/embargoed data by storing auth passwords in local config
* Add and use custom FDSN servers
* Saves all downloaded data as miniseed in a local SDS database to speed up future retrievals
* Local sqlite3 database editor
* Load and save search parameters and configuration


Platforms
---------

Runs on:

  * Linux
  * Windows
  * MacOS


Dual Access
-----------

Can run:

  * As web service (local-only unsecured mode)
  * From the command line (CLI)


.. note::

   **This project is sponsored by AuScope: We provide research tools, data, analytics and support to
   Australia’s geoscience community. https://www.auscope.org.au/**

   **AuScope is an NCRIS-funded organisation**

   .. image:: _static/images/AuScope_NCRIS_Logo.png
      :width: 400
      :alt: AuScope and NCRIS logos

.. toctree::
   :maxdepth: 2
   :caption: Contents:
   :hidden:

   introduction
   usage
   app
   cli
   modules
   

Indices
=======

* :ref:`genindex`
* :ref:`modindex`


