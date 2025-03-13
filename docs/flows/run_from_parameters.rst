Run from Parameters
=================

This workflow allows execution of operations using saved or predefined parameter sets, enabling automated and reproducible data processing without interactive selection.

Overview
--------

The Run from Parameters workflow enables users to execute operations using configuration files rather than interactive selection. This approach provides automation and reproducibility for various seismic data processing tasks, allowing users to quickly run common workflows without manual configuration.

Workflow Steps
-------------

Unlike the other workflows that require multiple interactive steps, the Run from Parameters workflow consists of a single step:

1. **Load and Execute Configuration**: Load a configuration file containing predefined parameters and execute the corresponding process

This workflow is particularly useful for:

* Batch processing of multiple datasets
* Reproducible research workflows
* Automated data collection routines
* Scheduled data retrieval tasks
* Sharing processing configurations with colleagues

Step 1: Load and Execute Configuration
------------------------------------

.. figure:: ../screenshots/run-parameters.png
   :alt: Run from Parameters Interface
   :width: 100%
   
   Run from Parameters interface showing configuration and execution log

The Run from Parameters interface allows you to execute seismic data operations using predefined configuration files:

**Configuration Display**:
   * View the currently loaded configuration file
   * See warnings about missing or default parameters
   * Configuration sections include:
     * [SDS] - Path settings for SeisComP Data Structure
     * [DATABASE] - Database connection settings
     * [PROCESSING] - Processing parameters like number of processes and gap tolerance
     * [AUTH] - Authentication credentials for restricted data access
     * [WAVEFORM] - Client selection and other waveform parameters

**Execution Controls**:
   * The configuration is automatically executed when loaded
   * "Cancel Processing" button to stop the execution
   * Real-time log output showing the progress of the operation

**Log Information**:
   * View detailed information about the execution process
   * See which operations are being performed (e.g., `get_events`, `get_stations`)
   * Monitor the results of each operation
   * Track overall progress of the workflow

**Technical Details**:
   * The system reads parameters directly from the configuration file
   * Parameters can specify event criteria, station selection, time windows, etc.
   * The system automatically determines whether to run event-based or continuous-based processing
   * Processing follows the same underlying logic as the interactive workflows
   * Results are stored in the same database and file structure as other workflows

This workflow effectively bypasses the interactive selection steps of the other workflows, allowing for automated execution based on predefined parameters.

Key Features
-----------

* Parameter-driven execution
* Configuration file-based operation
* Command-line interface (CLI) support for scripting
* Automated processing without user interaction
* Detailed logging of processing steps
* Support for both event-based and continuous data retrieval 