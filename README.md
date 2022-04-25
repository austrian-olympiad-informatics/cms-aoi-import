# CMS AOI

CMS import system for AOI.

## Installation

0. Clone the repo

   ```bash
   $ git clone https://gitlab.com/aoi-dev/cms-aoi-import.git
   $ cd cms-aoi-import
   ```

1. Install requirements: [ninja-build](https://ninja-build.org/) (varies on platform)

2. (Optional) Install to virtual env (to not pollute user env)

   ```bash
   $ python3 -m venv venv
   $ source venv/bin/activate
   # Must repeat the source each time using this tool!
   ```

3. Install the tool

   ```bash
   $ pip3 install -e .
   ```

4. (Optional) Include a local CMS - needed for uploading tasks to cms

    ```bash
    # in cms repo
    $ pip3 install -e .
    ```

Commands:
- **build** - build testcases and other files

  ```bash
  $ cmsAOI build dijkstra
  ```

  Built testcases will be put in .aoi-temp/result local folder

- **upload** - build and upload to cms (needs a CMS install)

- **clean** - clean up build files

## YAML Schema

TODO
