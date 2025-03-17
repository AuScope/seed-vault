Main Flows
==========

SEED-vault supports multiple operational workflows to accommodate different seismic data analysis needs. Each workflow shares common components but differs in sequence and focus.

.. toctree::
   :maxdepth: 1
   
   workflow_comparison
   flows/events_based
   flows/station_based
   flows/continuous_based
   .. flows/run_from_parameters

Workflow Components
------------------

All workflows involve some combination of these key components:

* **Event Selection**: Choosing earthquake events based on criteria like time, magnitude, and location
* **Station Selection**: Selecting seismic stations based on network, location, or other parameters
* **Waveform Download**: Retrieving seismic waveform data for the selected events and stations
* **Continuous Data Download**: Retrieving continuous time series data from selected stations
* **Parameter Configuration**: Setting processing parameters for data retrieval and analysis

For a detailed comparison of workflows and guidance on which to choose, see the :doc:`workflow_comparison` page. 