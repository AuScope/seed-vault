===============
Getting Started
===============

Requirements
============

* At least 8 GB RAM

* Python >= v3.10

Installation
============

Install via pip (easy way)
--------------------------

.. code-block:: sh

   python3 -m pip install seed-vault

NB:

1. If you get an "error: externally-managed-environment" error, you will need to install and activate a new Python environment
   
   e.g.

.. code-block:: sh

    python3 -m venv ./venv
    . ./venv/bin/activate

2. Assumes python & 'pip', 'venv' packages are installed

   e.g. for Ubuntu, as root:

.. code-block:: sh

    apt update
    apt install -y python3 python3-dev python3-pip python3-venv


Install from source (if you insist!)
------------------------------------

Step 1: Clone repository
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: sh

   git clone https://github.com/AuScope/seed-vault.git


Step 2: Setup and run
^^^^^^^^^^^^^^^^^^^^^

Then can build via pip:

.. code-block:: sh

   python3 -m pip install ./seed-vault


Or,

**Linux/MacOS**

.. code-block:: sh

   cd seed-vault
   source setup.sh
   source run.sh

**Windows**

Open a powershell and run following commands:

.. code-block:: sh

   cd seed-vault
   .\setup-win.ps1
   .\run-win.ps1


**NOTES:**

1. Requires get, sudo & python3 software packages:

   e.g. for Ubuntu you may need install (as root):

.. code-block:: sh

   apt update
   apt install -y git sudo
   apt install -y python3 python3-dev python3-pip python3-venv

Starting the Application
========================

.. code-block:: sh

   seed-vault

Getting to the Opening Page
===========================

You'll get a message like this:

.. code-block:: sh

   Collecting usage statistics. To deactivate, set browser.gatherUsageStats to false.


   You can now view your Streamlit app in your browser.

   Local URL: http://localhost:8501
   Network URL: http://222.111.001.002:8501
   External URL: http://222.111.001.002:8501

Enter a URL into your brower, and you should see the opening page:

.. image:: _static/images/startup-page.png

From here you can select one of three options, then hit the "Start" button:

* A. Event based
* B. Station based
* C. Continuous Data


i. Event Based Workflow
=======================


"Step 1: Search & Select Events" Page
-------------------------------------

.. image:: _static/images/step1-select-events.png

1. Hit the "Load Events" button (circled in green)
2. Select events from the map and/or directly in the table 
3. Hit the "Next" button (circled in orange)

"Step 2: Search & Select Stations" Page
---------------------------------------

.. image:: _static/images/step2-select-stations.png

1. Hit the "Load Stations" button (circled in orange)
2. Select stations from the map and/or directly in the table
3. Hit the "Next" button (circled in green)

"Step 3: Waveforms" Page
------------------------

.. image:: _static/images/waveform-analysis.png

1. Click on the "Get Waveforms" button (circled in pink)



ii. Station Based
=================

"Step 1: Search & Select Stations" Page
---------------------------------------

.. image:: _static/images/step1-select-stations.png

1. Hit the "Load Stations" button (circled in yellow)
2. Select stations from the map and/or directly in the table
3. Hit the "Next" button (circled in pink)

"Step 2: Search & Select Events" Page
-------------------------------------

.. image:: _static/images/step2-select-events.png

1. Hit the "Load Events" button (circled in purple)
2. Select events from the map and/or directly in the table
3. Hit the "Next" button (circled in green)

"Step 3: Waveforms" Page
------------------------

.. image:: _static/images/waveform-analysis.png

1. Click on the "Get Waveforms" button (circled in pink)



iii. Continuous Downloads
=========================

"Step 1: Search & Select Stations" Page
---------------------------------------

.. image:: _static/images/step1-select-stations.png

1. Hit the "Load Stations" button (circled in yellow)
2. Select stations from the map or directly in the table
3. Hit the "Next" button (circled in pink)

"Step 2: Get Waveforms" Page
----------------------------

.. image:: _static/images/continuous-waveform.png

Hit the "Download Waveforms" button, wait for download to complete


