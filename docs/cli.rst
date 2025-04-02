CLI Commands
============

In addition to its web interface, `seed-vault` also supports several operations via command-line interface (CLI) commands. This feature is especially useful if you prefer automating tasks or bypassing the UI when configuring your downloads.

Using a base configuration file, you can easily adapt settings for different use cases. The CLI behavior is similar to the "Run from Parameters" mode, where users configure their inputs through a `.cfg` file (e.g., `input.cfg`). The full list of supported parameters can be found in the :ref:`parameter-reference` section.

Available CLI commands are outlined below:

Run the Web Server
------------------
To launch the Streamlit web server on `localhost`, use the following command:

::
    seed-vault


Run from a Configuration File
-----------------------------
Use this command to download seismic data directly to your local drive using a `.cfg` configuration file.

As mentioned earlier, this file follows the same format as the parameter definitions used in "Run from Parameters." Example configuration files are available in the [examples directory](https://github.com/AuScope/seed-vault/tree/main/examples).

::

    seed-vault -f input.cfg

or

::

    seed-vault --file input.cfg



Sync Local Database
-------------------
If you've already downloaded seismic data and want to avoid re-downloading it, you need to sync its metadata with the local `seed-vault` database. This can be done either via the UI or with the CLI:


::

    seed-vault sync-db sds_path="/path/to/your/downloaded data" db_path="/path/to/seed-vault db"


Optional parameters for `sync-db` include:

- `-sp`, `--search-patterns`: *(default: "??.*.*.???.?.????.???")*  
  Comma-separated list of search patterns to include in the inventory search.

- `-nt`, `--newer-than`:  
  Date in `YYYY-MM-DD` format. Only includes time series newer than this date.

- `-c`, `--cpu`: *(default: 0)*  
  Number of processes to use. Set to `0` to use all available cores.

- `-g`, `--gap-tolerance`: *(default: 60)*  
  Tolerance for gaps in time series data, in seconds.

