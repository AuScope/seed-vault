Getting Started
===============

Installation
------------

Install via pip (easy way)
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: sh

   python3 pip install seed-vault


Install from source (if you insist!)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Step 1: Clone repository
""""""""""""""""""""""""

.. code-block:: sh

   git clone https://github.com/AuScope/seed-vault.git


Step 2: Setup and run
"""""""""""""""""""""

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

1. For Win OS, you would need to convert the shell scripts to PowerShell. Or simply follow the steps in the shell scripts to set up the app.
2. Requires python3 venv software package e.g. For python v10 on Ubuntu you may need to:

.. code-block:: sh

   sudo apt update
   sudo apt install python3.10-venv

Starting
--------

There are two ways to start the application:

1. Run from script
2. Run as Python library


Run from script
^^^^^^^^^^^^^^^

.. code-block:: sh

   source run.sh


Run as Python Library
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: sh

    seed-vault

