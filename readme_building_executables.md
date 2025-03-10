
# Building Executables for macOS, Linux, and Windows - Running in Browser Option

This readme outlines the steps to create executables for macOS, Linux, and Windows using **Python**, **Poetry**, and **PyInstaller**. The process is similar across platforms with some platform-specific adjustments.

---

## Initial Setup

### 1. Clean Previous Builds (if necessary)
Before starting, it's good to clean up any previous builds:
```bash
rm -rf dist build *.spec
sudo rm -rf /mnt/c/MyFiles/050-FDSN/seed-vault/.venv
```

### 2. Install Python, Poetry, and PyInstaller
For each platform (Linux, macOS, Windows):
- Install **Python** from [python.org](https://www.python.org/downloads/).
- Install **Poetry** by running the following command:
  ```bash
  (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -
  ```
- Install **PyInstaller** using Poetry or pip:
  ```bash
  poetry add --dev pyinstaller
  ```

### 3. Install Project Dependencies with Poetry
Once Poetry is installed, install all dependencies for your project:
```bash
poetry install
poetry shell
poetry show --with dev
```

---

## Streamlit Adjustments
[https://github.com/jvcss/PyInstallerStreamlit]
### Modify Streamlit to Run in PyInstaller

#### Add Content to `run_app.py`
Create a file called `run_app.py` with the following content:
```python
from streamlit.web import cli

if __name__ == '__main__':
    cli._main_run_clExplicit('seed_vault/ui/1_🌎_main_flows.py', is_hello=False)
```

#### Modify Streamlit's CLI
Navigate to the Streamlit path in your virtual environment:
```
.env\Lib\site-packages\streamlit\web\cli.py
```
Add the following function to `cli.py`:
```python
def _main_run_clExplicit(file, is_hello, args=[], flag_options={}):
    bootstrap.run(file, is_hello, args, flag_options)
```

#### Create a Hook to Collect Streamlit Metadata
Create a new hook file `hook-streamlit.py` under the `./hooks` directory:
```python
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata('streamlit')
```

---

## Compile the App with PyInstaller

### For Linux
Use the following command to compile the app on Linux:
```bash
pyinstaller --name seed-vault \
            --onefile \
            --additional-hooks-dir=./hooks \
            --collect-all streamlit \
            --collect-all folium \
            --collect-all obspy \
            --collect-all streamlit-folium \
            --specpath . \
            --clean \
            run_app.py
```

### For Windows
For Windows, use PowerShell and the following command:
```bash
pyinstaller --name seed-vault `
            --onefile `
            --additional-hooks-dir=.\hooks `
            --collect-all streamlit `
            --collect-all folium `
            --collect-all obspy `
            --collect-all streamlit-folium `
            --specpath . `
            --clean `
            run_app.py
```

### For macOS
For macOS, the command is similar to Linux:
```bash
pyinstaller --name seed-vault \
            --onefile \
            --additional-hooks-dir=./hooks \
            --collect-all streamlit \
            --collect-all folium \
            --collect-all obspy \
            --collect-all streamlit-folium \
            --specpath . \
            --clean \
            run_app.py
```

---

## Streamlit Configuration

Create the following configuration file for Streamlit to specify server options.

### `.streamlit/config.toml`:
```toml
[global]
developmentMode = false

[server]
port = 8502
```

Add this file either to the project root or the `dist` output folder after building.

### Copy Configuration and Files
After building, copy configuration and source files to the `dist` folder:
```bash
xcopy /s /e ".\.streamlit" "dist\.streamlit"
Copy-Item -Path "seed_vault" -Destination "dist\seed_vault" -Recurse
```

---

## Modify the Spec File for Each Platform

### Linux Spec File
For Linux, the `datas` and `hiddenimports` sections in the `.spec` file should look like this:
```python
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, copy_metadata, collect_submodules
import os
import pkg_resources  

datas = []
binaries = []
hiddenimports = []

for package in ['streamlit', 'folium', 'obspy', 'streamlit-folium']:
    tmp_ret = collect_all(package)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

datas += collect_data_files('obspy', subdir='imaging/data')
datas += collect_data_files('obspy', subdir='taup/data')

binaries += collect_dynamic_libs('obspy')

obspy_release_version_path = os.path.join(os.getcwd(), ".venv", "lib", "python3.12", "site-packages", "obspy", "RELEASE-VERSION")
datas.append((obspy_release_version_path, "obspy/"))

for dist in pkg_resources.working_set:
    datas += copy_metadata(dist.project_name)

hiddenimports += collect_submodules('requests')  
datas += collect_data_files('requests')          

hiddenimports += collect_submodules('streamlit_ace')
datas += collect_data_files('streamlit_ace')

# Collect required package files
datas += collect_data_files('matplotlib')  
datas += collect_data_files('scipy')       
datas += collect_data_files('numpy')       

datas += [
    (".venv/lib/python3.12/site-packages/altair/vegalite/v5/schema/vega-lite-schema.json", "./altair/vegalite/v5/schema/"),
    (".venv/lib/python3.12/site-packages/streamlit/static", "./streamlit/static"),
    (".venv/lib/python3.12/site-packages/streamlit/runtime", "./streamlit/runtime"),
    (".venv/lib/python3.12/site-packages/streamlit_folium", "streamlit_folium"),
    ("seed_vault", "seed_vault"),
    ("data", "data"),
    (".streamlit/config.toml", ".streamlit/config.toml"),
]

hiddenimports += [
    'numpy', 'scipy', 'lxml', 'sqlalchemy', 'setuptools', 'requests', 'urllib3', 'packaging',
    'matplotlib', 'matplotlib.pyplot', 'matplotlib.backends.backend_agg',
    'obspy.core', 'obspy.clients', 'obspy.io', 'obspy.taup',
    'obspy.signal', 'obspy.imaging', 'tqdm', 'streamlit-folium', 
    'pydantic', 'jupyter', 'seaborn', 'plotly',
    'pandas', 'click', 'tabulate', 'streamlit-extras', 'streamlit-ace', 'decorator'
]


a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['./hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='seed-vault',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

### Windows Spec File
For Windows, adjust the paths to Windows-style:
```python
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, copy_metadata, collect_submodules
import os
import pkg_resources  

datas = []
binaries = []
hiddenimports = []

for package in ['streamlit', 'folium', 'obspy', 'streamlit-folium']:
    tmp_ret = collect_all(package)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

datas += collect_data_files('obspy', subdir='imaging/data')
datas += collect_data_files('obspy', subdir='taup/data')

binaries += collect_dynamic_libs('obspy')

obspy_release_version_path = os.path.join(os.getcwd(), ".venv", "Lib", "site-packages", "obspy", "RELEASE-VERSION")
datas.append((obspy_release_version_path, "obspy/"))


for dist in pkg_resources.working_set:
    datas += copy_metadata(dist.project_name)

hiddenimports += collect_submodules('requests')  
datas += collect_data_files('requests')         

hiddenimports += collect_submodules('streamlit_ace')  
datas += collect_data_files('streamlit_ace')  

datas += collect_data_files('matplotlib')  
datas += collect_data_files('scipy')       
datas += collect_data_files('numpy')       
datas += [
    (".venv\\Lib\\site-packages\\altair\\vegalite\\v5\\schema\\vega-lite-schema.json", "./altair/vegalite/v5/schema/"),
    (".venv\\Lib\\site-packages\\streamlit\\static", "./streamlit/static"),
    (".venv\\Lib\\site-packages\\streamlit\\runtime", "./streamlit/runtime"),
    (".venv\\Lib\\site-packages\\streamlit_folium", "streamlit_folium"),
    ("seed_vault", "seed_vault"),
    ("data", "data"),
    (".streamlit\\config.toml", ".streamlit/config.toml"),
]

hiddenimports += [
    'numpy', 'scipy', 'lxml', 'sqlalchemy', 'setuptools' ,'requests', 'urllib3', 'packaging',
    'matplotlib', 'obspy.core', 'obspy.clients', 'obspy.io', 'obspy.taup',
    'obspy.signal', 'obspy.imaging', 'tqdm', 'streamlit-folium', 
    'pydantic', 'jupyter', 'seaborn', 'plotly',
    'pandas', 'click', 'tabulate', 'streamlit-extras', 'streamlit-ace', 'decorator'
]

a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],  
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='seed-vault',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

```

### macOS Spec File
For macOS, use the same style as Linux, with paths similar to Linux paths:
```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, copy_metadata, collect_submodules
import os
import pkg_resources  

datas = []
binaries = []
hiddenimports = []

for package in ['streamlit', 'folium', 'obspy', 'streamlit-folium']:
    tmp_ret = collect_all(package)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

datas += collect_data_files('obspy', subdir='imaging/data')
datas += collect_data_files('obspy', subdir='taup/data')

binaries += collect_dynamic_libs('obspy')

obspy_release_version_path = os.path.join(os.getcwd(), ".venv", "lib", "python3.12", "site-packages", "obspy", "RELEASE-VERSION")
datas.append((obspy_release_version_path, "obspy/"))

for dist in pkg_resources.working_set:
    datas += copy_metadata(dist.project_name)

hiddenimports += collect_submodules('requests')  
datas += collect_data_files('requests')          

hiddenimports += collect_submodules('streamlit_ace')
datas += collect_data_files('streamlit_ace')

# Collect required package files
datas += collect_data_files('matplotlib')  
datas += collect_data_files('scipy')       
datas += collect_data_files('numpy')       

# Additional required data files (macOS paths)
datas += [
    (".venv/lib/python3.12/site-packages/altair/vegalite/v5/schema/vega-lite-schema.json", "./altair/vegalite/v5/schema/"),
    (".venv/lib/python3.12/site-packages/streamlit/static", "./streamlit/static"),
    (".venv/lib/python3.12/site-packages/streamlit/runtime", "./streamlit/runtime"),
    (".venv/lib/python3.12/site-packages/streamlit_folium", "streamlit_folium"),
    ("seed_vault", "seed_vault"),
    ("data", "data"),
    (".streamlit/config.toml", ".streamlit/config.toml"),
]

# Hidden imports (to prevent missing dependencies)
hiddenimports += [
    'numpy', 'scipy', 'lxml', 'sqlalchemy', 'setuptools', 'requests', 'urllib3', 'packaging',
    'matplotlib', 'matplotlib.pyplot', 'matplotlib.backends.backend_agg',
    'obspy.core', 'obspy.clients', 'obspy.io', 'obspy.taup',
    'obspy.signal', 'obspy.imaging', 'tqdm', 'streamlit-folium', 
    'pydantic', 'jupyter', 'seaborn', 'plotly',
    'pandas', 'click', 'tabulate', 'streamlit-extras', 'streamlit-ace', 'decorator'
]

# PyInstaller analysis
a = Analysis(
    ['run_app.py'],
    pathex=[os.getcwd()],  
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[], 
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='seed-vault',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",  # Ensure compatibility with macOS (modify for Apple Silicon if needed)
    codesign_identity=None,
    entitlements_file=None,
)

```

---

## Build the Executable

Finally, to build the executable on any platform, run:
```bash
pyinstaller seed-vault.spec --clean
```

---

## Conclusion

By following these steps, you can build standalone executables for macOS, Linux, and Windows using **Poetry** and **PyInstaller**. Each platform requires slight adjustments, such as path formatting, but the overall process remains consistent across environments.


# Building as Desktop app

## How to build

@stlite/desktop can be used to build a desktop app with Steamlit. Follow the below step:

- Create a `package.json`. There is already one created in the project (see https://github.com/whitphx/stlite/blob/main/packages/desktop/README.md)
- Make sure all required project files are available in `package.json`
- Make sure `requirements.txt` is available for lib dependencies
- `npm install` -> this will install required node_modules
- `npm run dump` -> builds the app
- `npm run serve` -> serves the app
- `npm run dist` -> creates executable

## Main Challenge - Lib dependecies

stlite only accept libraries that have pure wheels, i.e., they are built for webassembly. `pyodide` (https://pyodide.org/en/stable/usage/faq.html#why-can-t-micropip-find-a-pure-python-wheel-for-a-package) seems to be reponsible to bundle the app. This library already comes with a list of famous libs such as `pandas`. But it does not support less famous/widely used libs such as `obspy`.

Packagin a lib in to a webassembly wheel seems to be quite complicated and not worthy of much try. And this is the main blocker of this approach.

**NOTE:** packages with pure wheel will have `*py3-none-any.whl` in their naming.
