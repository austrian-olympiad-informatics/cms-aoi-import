import shlex
import zipfile
from pathlib import Path

import voluptuous as vol

from cmsaoi import rule
from cmsaoi.const import (
    CONF_ADDITIONAL_FILES,
    CONF_ATTACHMENTS,
    CONF_ATTRIBUTION,
    CONF_AUTHOR,
    CONF_CHECKER,
    CONF_CODENAME,
    CONF_CPP_CONFIG,
    CONF_DECIMAL_PLACES,
    CONF_EDITOR_TEMPLATES,
    CONF_FEEDBACK_LEVEL,
    CONF_FILE,
    CONF_GCC_ARGS,
    CONF_GEN_NUMBER,
    CONF_GRADER,
    CONF_INITIAL,
    CONF_INPUT,
    CONF_INPUT_TEMPLATE,
    CONF_LATEX_CONFIG,
    CONF_LATEXMK_ARGS,
    CONF_LONG_NAME,
    CONF_MANAGER,
    CONF_MAX_SCORE,
    CONF_MEMES,
    CONF_MEMORY_LIMIT,
    CONF_MIN_SCORE,
    CONF_MODE,
    CONF_NAME,
    CONF_NUM_PROCESSES,
    CONF_OJUZ_KEY,
    CONF_OUTPUT,
    CONF_POINTS,
    CONF_PUBLIC,
    CONF_SAMPLE_SOLUTION,
    CONF_SCORE_OPTIONS,
    CONF_STATEMENTS,
    CONF_STDIN_FILENAME,
    CONF_STDOUT_FILENAME,
    CONF_SUBTASKS,
    CONF_TASK_TYPE,
    CONF_TEST_GRADER,
    CONF_TEST_SUBMISSIONS,
    CONF_TESTCASE_CHECKER,
    CONF_TESTCASES,
    CONF_TIME_LIMIT,
    CONF_TOKENS,
    CONF_TYPE,
    CONF_USER_IO,
    CONF_USES,
    CONF_WEIGHT,
    FEEDBACK_LEVELS,
    SCORE_MODES,
    SCORE_TYPES,
    TOKEN_MODES,
)
from cmsaoi.yaml_loader import AOITag


def validate_file(value):
    if isinstance(value, str):
        p = Path(value)
        if not p.is_file():
            raise vol.Invalid(f"File {value} does not exist!")
        return value
    if not isinstance(value, AOITag):
        raise vol.Invalid(f"File must be either a string or Tag, not {type(value)}")
    return value


def validate_file_autoextract(value):
    # Validate a file but automatically extract
    value = validate_file(value)
    if not isinstance(value, str):
        return value
    suffixes = Path(value).suffixes
    if not suffixes:
        return value
    if ".gz" == suffixes[-1]:
        return AOITag(Path.cwd(), "!gunzip", rule.GunzipNinja, value)
    if ".xz" == suffixes[-1]:
        return AOITag(Path.cwd(), "!xzunzip", rule.XZUnzipNinja, value)
    if ".zip" == suffixes[-1]:
        ret = []
        with zipfile.ZipFile(Path(value), "r") as zipf:
            for info in zipf.infolist():
                if info.is_dir() or Path(info.filename).name.startswith("."):
                    continue
                # TODO
                ret.append(
                    AOITag(
                        Path.cwd(),
                        "!unzip",
                        # pylint: disable=undefined-variable
                        None,
                        shlex.join([value, info.filename]),
                    )
                )
        return ret
    return value


def validate_file_glob(value):
    try:
        return validate_file_autoextract(value)
    except vol.Invalid as err:
        first_err = err

    try:
        items = list(sorted(map(str, Path.cwd().glob(value))))
    except Exception:
        raise first_err from None
    if not items:
        raise first_err from None
    return list(map(validate_file_autoextract, items))


def flatten_testcase_globs(value):
    testcases = value
    new_testcases = []
    for testcase in testcases:
        inp = testcase[CONF_INPUT]
        out = testcase.get(CONF_OUTPUT)
        if not isinstance(inp, list):
            if isinstance(out, list):
                raise vol.Invalid("Output cannot be a glob expression if input is not!")
            new_testcases.append(testcase)
            continue

        if out is not None:
            if not isinstance(out, list):
                raise vol.Invalid("Both input and output must be a glob expression!")
            if len(inp) != len(out):
                raise vol.Invalid(
                    f"Number of items matched by input glob ({len(inp)}) must match number "
                    f"of items in output glob ({len(out)})!"
                )
            for a, b in zip(inp, out):
                new_testcases.append({**testcase, "input": a, "output": b})
        else:
            for a in inp:
                new_testcases.append({**testcase, "input": a})
    return new_testcases


def one_of(*values):
    option_s = ", ".join(map(str, values))

    def validator(value):
        if value not in values:
            raise vol.Invalid(
                f"{value} is not a valid option, must be one of {option_s}."
            )
        return value

    return validator


def float_with_unit(unit: str):
    def validator(value):
        if not isinstance(value, str):
            raise vol.Invalid(f"{value} needs a unit. Please write {value}{unit}.")
        if not value.endswith(unit):
            raise vol.Invalid(f"{value} must end with unit {unit}.")
        fvalue = value[: -len(unit)]
        return vol.Coerce(float)(fvalue)

    return validator


def string(value: str):
    if not isinstance(value, str):
        raise vol.Invalid(f"Only string types allowed here, not {type(value)}")
    return value


def copy_public_to_testcases(config):
    testcases = config[CONF_TESTCASES]
    new_testcases = []
    for tc in testcases:
        tc = tc.copy()
        if CONF_PUBLIC not in tc:
            tc[CONF_PUBLIC] = config[CONF_PUBLIC]
        new_testcases.append(tc)
    config = config.copy()
    config[CONF_TESTCASES] = new_testcases
    return config


def simple_batch(value):
    if isinstance(value, str) and value == "BATCH":
        return {
            CONF_TYPE: "BATCH",
            CONF_STDIN_FILENAME: "",
            CONF_STDOUT_FILENAME: "",
        }
    raise vol.Invalid("Not simple batch")


CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): string,
        vol.Required(CONF_LONG_NAME): string,
        vol.Optional(CONF_AUTHOR): string,
        vol.Optional(CONF_ATTRIBUTION): string,
        vol.Optional(CONF_USES): [string],
        vol.Required(CONF_STATEMENTS): {
            string: validate_file,
        },
        vol.Optional(CONF_ATTACHMENTS, default={}): {
            string: validate_file,
        },
        vol.Optional(CONF_FEEDBACK_LEVEL, default="RESTRICTED"): one_of(
            *FEEDBACK_LEVELS
        ),
        vol.Required(CONF_SCORE_OPTIONS): {
            vol.Optional(CONF_DECIMAL_PLACES, default=0): int,
            vol.Optional(CONF_MODE, default="SUM_SUBTASK_BEST"): one_of(*SCORE_MODES),
            vol.Optional(CONF_TYPE, default="GROUP_MIN"): one_of(*SCORE_TYPES),
        },
        vol.Required(CONF_TIME_LIMIT): float_with_unit("s"),
        vol.Required(CONF_MEMORY_LIMIT): float_with_unit("MiB"),
        vol.Optional(CONF_SAMPLE_SOLUTION): validate_file,
        vol.Optional(CONF_GRADER, default=[]): [validate_file],
        vol.Required(CONF_TASK_TYPE): vol.Any(
            simple_batch,
            {
                vol.Required(CONF_TYPE): "BATCH",
                vol.Optional(CONF_STDIN_FILENAME, default=""): str,
                vol.Optional(CONF_STDOUT_FILENAME, default=""): str,
            },
            "OUTPUT_ONLY",
            {
                vol.Required(CONF_TYPE): "COMMUNICATION",
                vol.Required(CONF_MANAGER): validate_file,
                vol.Optional(CONF_NUM_PROCESSES, default=1): vol.Coerce(int),
                vol.Optional(CONF_USER_IO, default="std_io"): vol.Any(
                    "std_io", "fifo_io"
                ),
            },
            {
                vol.Required(CONF_TYPE): "OJUZ",
                vol.Required(CONF_OJUZ_KEY): str,
            },
        ),
        vol.Required(CONF_SUBTASKS): [
            vol.All(
                vol.Schema(
                    {
                        vol.Required(CONF_POINTS): vol.Coerce(float),
                        vol.Optional(CONF_PUBLIC, default=True): vol.Coerce(bool),
                        vol.Required(CONF_TESTCASES): vol.All(
                            [
                                vol.Schema(
                                    {
                                        vol.Optional(CONF_INPUT): validate_file_glob,
                                        vol.Optional(CONF_OUTPUT): validate_file_glob,
                                        vol.Optional(CONF_PUBLIC): vol.Coerce(bool),
                                        vol.Optional(CONF_CODENAME): string,
                                    },
                                    extra=vol.ALLOW_EXTRA,
                                )
                            ],
                            flatten_testcase_globs,
                        ),
                    },
                    extra=vol.ALLOW_EXTRA,
                ),
                copy_public_to_testcases,
            )
        ],
        vol.Optional(CONF_CHECKER): validate_file,
        vol.Optional(CONF_TESTCASE_CHECKER): validate_file,
        vol.Optional(CONF_TEST_SUBMISSIONS): {
            validate_file: vol.Coerce(float),
        },
        vol.Optional(CONF_CPP_CONFIG, default={}): {
            vol.Optional(CONF_GCC_ARGS, default="-O2 -std=gnu++11 -static -s"): string,
        },
        vol.Optional(CONF_LATEX_CONFIG, default={}): {
            vol.Optional(
                CONF_LATEXMK_ARGS,
                default="latexmk -latexoption=-interaction=nonstopmode -pdf -cd",
            ): string,
            vol.Optional(CONF_ADDITIONAL_FILES, default=[]): [validate_file],
            vol.Optional(CONF_INPUT_TEMPLATE): string,
        },
        vol.Optional(CONF_TOKENS, default={}): {
            vol.Optional(CONF_MODE, default="DISABLED"): one_of(*TOKEN_MODES),
            vol.Optional(CONF_INITIAL, default=2): vol.Coerce(int),
            vol.Optional(CONF_GEN_NUMBER, default=2): vol.Coerce(int),
        },
        vol.Optional(CONF_MEMES): [
            {
                vol.Required(CONF_FILE): validate_file,
                vol.Optional(CONF_MIN_SCORE, default=0.0): vol.Coerce(float),
                vol.Optional(CONF_MAX_SCORE, default=100.0): vol.Coerce(float),
                vol.Optional(CONF_WEIGHT, default=1.0): vol.Coerce(float),
            }
        ],
        vol.Optional(CONF_EDITOR_TEMPLATES, default=[]): [validate_file],
        vol.Optional(CONF_TEST_GRADER, default=[]): [validate_file],
    }
)
