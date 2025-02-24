Introduction
============

Seismology services around the globe utilise the FDSN protocol, a well-defined free and open standard for
transmission and archiving of seismic waveform data, metadata, and earthquake information.

Unfortunately this only benefits those who have the software skills to wrangle with low-level HTTP requests and responses.

For the beginners, hobbyists and less software-savvy, the available pool of fully featured, open source, easy to use
GUI driven software tools is very limited.

To solve this problem we have created **seed-vault** an easy to use, open source GUI that has all the features required to access
and store seismic data.


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


Flexible
--------

Can run:

  * As web service (local-only unsecured mode)
  * From the command line (CLI)


.. note::

   **This project is under active development.**
