# CMS AOI

CMS import system for AOI.

## Installation

0. Clone the repo

   ```bash
   $ git clone https://gitlab.com/aoi-dev/cms-aoi-import.git
   $ cd cms-aoi-import
   ```

1. Install requirements:

 - [ninja-build](https://ninja-build.org/) (varies on platform)
 - A recent [pandoc](https://github.com/jgm/pandoc/releases) install (for `!mdcompile`)

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

### Folder structure

cmsAOI expects each task to be in its own folder. The file `task.yaml` in this
folder is where you can configure the task.

Example folder structure

```
$ tree .
.
├── attachment
│   ├── cpp
│   │   ├── grader.cpp
│   │   ├── mvv.cpp
│   │   └── mvv.h
│   └── typescript
│       ├── grader.ts
│       └── mvv.ts
├── private
│   ├── cpp
│   │   ├── grader.cpp
│   │   └── mvv.h
│   └── typescript
│       └── grader.ts
├── solution
│   ├── n2.cpp
│   └── nlogn.ts
├── statement
│   ├── mvv.md
│   ├── mvv.tex
│   └── sample.png
├── task.yaml
└── tc
    └── gen.py
$ cmsAOI build .
```

### Basics

The task is configured in the `task.yaml` file in the YAML format. Before
a task is built/uploaded, the YAML file is parsed and validated (so extra/misspelled keys etc will turn into an error).

Some options (such as `name` or `author`) just expect a _string_ as the value.
Others, such as `statements[:][value]` accept _files_. For example for a statement
the following would cause the file `statement/mvv.pdf` to be uploaded.

```yaml
statements:
  de: statement/mvv.pdf
```

### Tags

For these options that accept files you can use **tags** to automatically perform an action.
Tags start with an exclamation mark, then the tag type, plus arguments (if any).
Tags always _produce_ a file, so they can only be used for config options that accept
a file.

For example, the following would apply the `!latexcompile` flag with the parameter `statement/mvv.tex`, and internally produces a PDF file (the output of latexmk).

```yaml
statements:
  de: !latexcompile statement/mvv.tex
```

- `!latexcompile`: Accepts a tex file as input, and produces a PDF file (by running it through `latexmk`)
- `!cppcompile`: Accepts one or more cpp file paths as input, and produces a compiled binary.
- `!cpprun`: Compiles the .cpp file specified in the first argument, and runs it with the arguments specified afterwards. The stdout of this run is the produced file.
- `!shell`: Runs a shell command and captures the stdout in a file.
- `!pyrun`: Runs the given .py file with optional arguments (after the filename), and captures the stdout in a file.

  Example: `input: !pyrun tc/gen.py 1 1000`
- `!raw`: Puts the argument string into a file (so converts a string argument to a file argument)

  Example:
  ```yaml
  input: !raw |
    3
    RRRRG
  ```

- `!pyinline`: Runs the argument string as a python script and captures the stdout.

  Example:
  ```yaml
  input: !pyinline |
   N, M = 100000, 100000-1
   print(N, M)
   for i in range(1, M+1):
      print(i, i+1)
  ```

- `!zip`: Compresses the files specified as arguments into a zip file.

  Supports the wildcard `*` to match any file in a folder. Additionally, arguments can also be of form `ZIP_NAME=LOCAL_PATH` to put `LOCAL_PATH` with the path `ZIP_NAME` inside the zip file.

- `!mdcompile`: Accepts as argument a markdown file, and converts it to a HTML file (with any resources/images embedded as base64 strings).

  Example: `statement_html: !mdcompile mvv/mvv.md`

- `!gunzip`: Unzips the gzip file specified as the first argument.

- `!xzunzip`: Unzips the xz file specified as the first argument.

- `!xzunzip`: Unzips the xz file specified as the first argument.

### YAML Schema

```yaml
# extends (optional, path): specify a YAML file here to use all options
# specified there as the base. Any changes made in the task.yaml 
# file will overwrite the options in the "extended" file.
extends: ../base-task.yaml

# name (REQUIRED, string): specify the short codename of the task
name: MVV

# long_name (REQUIRED, string): specify the long name of the task
long_name: Sitzdesign

# author (optional, string): Add an author tag for bookkeeping, not used
# for anything in cmsAOI.
author: 'Flo'

# attribution (optional, string): Add an attribution tag for bookkeeping, 
# not used for anything in cmsAOI.
attribution: 'Flo'

# uses (optional, list of strings): A list of times this task was used.
# Not used for anything in cmsAOI.
uses:
  - AOI 2020 1. Wien Qualifikation

# statements (required): A mapping of language code to a statement PDF file.
statements:
  de: !latexcompile statement/mvv.tex

# statement_html (optional, file): An optional HTML file to display in
# the left description panel in frontendv2.
statement_html: !mdcompile statement/mvv.md

# default_input (optional, file): An optional file to prepulate the
# stdin field in test mode with frontendv2.
default_input: !raw |
   3
   GBR

# attachments (optional): A mapping of filename to attachments to add
# to the task (!zip is useful here).
attachments:
  mvv.zip: !zip attachment/*

# feedback_level (optional, string): The CMS feedback level (i.e. if all testcase
# outcomes are shown, or only up to the last successful one in a subtask).
# Either `RESTRICTED` or `FULL`. Defaults to `restricted`.
feedback_level: FULL

# score_options: additional options for CMS scoring
score_options:
  # decimal_places (optional, int): The number of decimal places to round
  # the score for this task to. Defaults to 0.
  decimal_places: 0

  # mode (optional, string): The CMS score mode (how subtasks scores are combined), options:
  #  - MAX_TOKENED_LAST: best of the tokened submissions and the last one
  #  - SUM_SUBTASK_BEST: Sum of the best result for each subtask
  #  - MAX: Plain max of all submissions
  # Defaults to SUM_SUBTASK_BEST
  mode: SUM_SUBTASK_BEST

  # type (optional, string): The CMS score type (how testcase outcomes
  # are combined to the score of a subtask), options:
  #  - GROUP_MIN: subtask score = min(testcase outcomes)
  #  - GROUP_MUL: subtask score = prod(testcase outcomes)
  #  - SUM: subtask score = sum(testcase outcomes)
  # Defaults to GROUP_MIN.
  type: GROUP_MIN

# time_limit (required, string): The time limit for this task, with unit s
time_limit: 1.5s

# memory_limit (required, string): The memory limit for this task, with unit MiB
memory_limit: 512MiB

# sample_solution (optional, file): A file to execute to automatically compute testcase outputs (in case they're not already given).
sample_solution: !cppcompile samplesol.cpp

# grader (optional, list of files): A list of files to upload as graders/managers
# in CMS. These will (depending on the extension), be included in the compilation
# environment
grader:
  - private/cpp/grader.cpp
  - private/cpp/mvv.h

# task_type (required): settings for the task type in CMS
task_type:
  # There are three types: batch, output_only and communication
  
  # ======== BATCH TYPE ========
  type: BATCH
  # stdin_filename (optional, string): If given, puts the input file at that location. Otherwise just pipes the input into the process via stdin.
  stdin_filename: ""
  # stdout_filename (optional, string): If given, puts the output file at that location. Otherwise just takes the stdout of the process as output.
  stdout_filename: ""
  # for checker, see top-level checker option

  # ======== OUTPUT_ONLY TYPE ========
  type: OUTPUT_ONLY
  # no further options
  # for checker, see top-level checker option

  # ======== COMMUNICATION TYPE ========
  type: COMMUNICATION
  # manager (required, file): A binary to coordinate the child processes.
  # Receives as arguments the child process input and output FIFOs.
  manager: !cppcompile private/manager.cpp
  # num_processes (optional, int): The number of user processes to start,
  # defaults to 1.
  num_processes: 2
  # user_io (optional, string): Whether to use stdio or files (given as arguments
  # to the graders) as input/output to the manager. 
  # Options: `std_io` or `fifo_io`. Defaults to `std_io`
  user_io: std_io

# subtasks (required, list): A list of subtasks (for no subtasks just 
# give a single subtask here)
subtasks:
    # points (required, int): The amount of points to award for this subtask
    # Note: for SUM score type this is the amount to give _per_ testcase
  - points: 30
  
    # public (optional, boolean): Whether the subtask outcome is public.
    # Defaults to true
    public: true

    # testcases (required, list): A list of testcases for this subtask
    testcases:
        # input (optional, file): The input file for this testcase.
      - input: tc/1-01.in
        # output (optional, file): The output file for this testcase.
        # If not given, the sample_solution is used to automatically compute this
        output: tc/1-01.out

        # public (optional, boolean): Whether this testcase's outcome is public (visible to user). Defaults to true.
        public: True

        # codename (optional, string): A codename for this testcase, defaults to an automatically generated one like 1-01.

        # Notes:
        #  - if an input/output filename ends with .gz, it's automatically extracted
        #  - you can use wildcards to match multiple input/output files
        input: tc/1-*.in
        output: tc/1-*.out

# checker (optional, file): An executable to run the user's output against to determine
# how many points they get (and a message). See CMS docs for more information.
checker: !cppcompile checker.cpp

# testcase_checker (optional, file): An executable to run each testcase against
# before uploading (to do some sanity checks for the testcases).
# The executable gets as the only argv argument the subtask number
# The testcase input is piped in via stdin.
testcase_checker: testcase_checker.py

# test_submissions (optional, mapping): A mapping of file to expected number of points.
# After the task has been uploaded, each of these submissions is uploaded to the server.
# If any test submission does not receive the expected number of points, it's shown here.
test_submissions:
  solution/nlogn.cpp: 100

# editor_templates (optional, list of files): What the prepopulate the
# editor screen with in frontendv2 depending on the language.
editor_templates:
  - attachment/cpp/mvv.cpp
  - attachment/csharp/MVV.cs

# test_grader (optional, list of files): Like grader, but used for test mode
# in frontendv2. These are separate from the grader option because some graders
# use secret strings to validate the output authenticity.
test_grader:
  - attachment/cpp/grader.cpp
  - attachment/cpp/mvv.h
```
