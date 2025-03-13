Workflow Comparison
==================

SEED-vault offers four main workflows for accessing seismic data. This guide will help you choose the most appropriate workflow for your needs.

.. list-table:: Workflow Comparison
   :header-rows: 1
   :widths: 15 21 21 21 21

   * - Feature
     - Events-Based
     - Station-Based
     - Continuous-Based
     - Run from Parameters
   * - **Starting Point**
     - Earthquake events
     - Seismic stations
     - Seismic stations
     - Configuration file
   * - **Workflow Steps**
     - 1. Select Events
       2. Select Stations
       3. Download Waveforms
     - 1. Select Stations
       2. Select Events
       3. Download Waveforms
     - 1. Select Stations
       2. Download Continuous Data
     - 1. Load and Execute Configuration
   * - **Best For**
     - Studying specific earthquakes
     - Station-specific studies
     - Background noise analysis
     - Automated processing
   * - **Data Type**
     - Event-triggered waveforms
     - Event-triggered waveforms
     - Continuous time series
     - Both event and continuous
   * - **Time Selection**
     - Around earthquake events
     - Around earthquake events
     - Any time period
     - Defined in configuration
   * - **Visualization**
     - Waveform plots
     - Waveform plots
     - Log output (raw data)
     - Log output (raw data)
   * - **User Interaction**
     - Interactive selection
     - Interactive selection
     - Interactive selection
     - Minimal (configuration-based)

Choosing the Right Workflow
--------------------------

**Use Events-Based Workflow When:**
   * You're interested in specific earthquake events
   * You want to study how different stations recorded the same event
   * You're researching particular seismic events

**Use Station-Based Workflow When:**
   * You're focused on specific seismic stations
   * You want to study all events recorded at particular stations
   * You're conducting station-specific research or calibration

**Use Continuous-Based Workflow When:**
   * You need time series data not tied to specific events
   * You're studying background noise or ambient seismic fields
   * You need large volumes of continuous data for machine learning or other analyses

**Use Run from Parameters Workflow When:**
   * You need to automate repetitive data retrieval tasks
   * You're running batch processing operations
   * You want to ensure reproducible research with identical parameters
   * You're integrating with scripts or scheduled tasks 