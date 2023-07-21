import argparse
import io
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict

import voluptuous as vol  # type: ignore
import yaml
import yaml.constructor
from voluptuous.humanize import humanize_error  # type: ignore

from cmsaoi import ninja_syntax, rule
from cmsaoi.const import (
    CONF_ATTACHMENTS,
    CONF_CHECKER,
    CONF_CPP_CONFIG,
    CONF_EXTENDS,
    CONF_GCC_ARGS,
    CONF_GRADER,
    CONF_INPUT,
    CONF_LATEX_CONFIG,
    CONF_LATEXMK_ARGS,
    CONF_OUTPUT,
    CONF_SAMPLE_SOLUTION,
    CONF_STATEMENTS,
    CONF_SUBTASKS,
    CONF_TESTCASE_CHECKER,
    CONF_TESTCASES,
)
from cmsaoi.core import CMSAOIError, core
from cmsaoi.log import setup_log
from cmsaoi.util import write_if_changed
from cmsaoi.validation import CONFIG_SCHEMA
from cmsaoi.yaml_loader import AOITag, load_yaml

_LOGGER = logging.getLogger(__name__)


def recursive_visit(config, func):
    def visit(value, path):
        value = func(value, path)
        if isinstance(value, list):
            value = [visit(x, [*path, i]) for i, x in enumerate(value)]
        elif isinstance(value, dict):
            value = {
                visit(k, [*path, k]): visit(v, [*path, k]) for k, v in value.items()
            }
        return value

    return visit(config, [])


def merge_visit(full_base, full_extends):
    def visit(base, extends):
        if extends is None:
            return base
        if isinstance(base, list):
            if not isinstance(extends, list):
                return base
            return [visit(x, y) for x, y in zip(base, extends)]
        if isinstance(base, dict):
            if not isinstance(extends, dict):
                return base
            ret = extends.copy()
            for k, v in base.items():
                ret[k] = visit(v, extends.get(k))
            return ret
        if base is None:
            return extends
        return base

    return visit(full_base, full_extends)


def load_yaml_with_extends(path: Path):
    config = load_yaml(path)
    if CONF_EXTENDS in config:
        extend_config = load_yaml(path.parent / Path(config[CONF_EXTENDS]))
        config = merge_visit(config, extend_config)
        config.pop(CONF_EXTENDS)
    return config


def main():
    setup_log()

    parser = argparse.ArgumentParser(description="Austrian CMS Task Upload System")
    subparsers = parser.add_subparsers(help="Action", dest="action", required=True)

    build_parser = subparsers.add_parser(
        "build", help="Build testcases and other files"
    )
    build_parser.add_argument("task_dir", help="The directory of task to build.")

    test_parser = subparsers.add_parser(
        "test", help="Build testcases and test them locally"
    )
    test_parser.add_argument("task_dir", help="The directory of task to test.")

    clean_parser = subparsers.add_parser(
        "clean", help="Delete all temporary build files"
    )
    clean_parser.add_argument("task_dir", help="The directory of task to clean.")

    upload_parser = subparsers.add_parser(
        "upload", help="Build the configuration and upload it to CMS"
    )
    upload_parser.add_argument("task_dir", help="The directory of task to upload.")

    upload_parser.add_argument(
        "-c", "--contest", help="The contest ID to add the task to (integer).", type=int
    )
    upload_parser.add_argument(
        "--no-tests", help="Don't run any submission tests.", action="store_true"
    )

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="Compile and evaluate the given source file"
    )
    evaluate_parser.add_argument("task_dir", help="The directory of task to upload.")
    evaluate_parser.add_argument("source_file", help="The source file to test.")

    info_parser = subparsers.add_parser(
        "info", help="Finally a way to get this *** id."
    )
    info_parser.add_argument("task", help="The name of the task to find")

    args = parser.parse_args()

    action = {
        "build": command_build,
        "test": command_test,
        "clean": command_clean,
        "upload": command_upload,
        "evaluate": command_evaluate,
        "info": command_info,
    }[args.action]

    try:
        return action(args) or 0
    except CMSAOIError as err:
        _LOGGER.error(str(err))
        return 1


def _load_config(task_dir):
    td = Path(task_dir)
    if not td.is_dir():
        raise CMSAOIError(f"{td} is not a directory (must contain a task.yaml)")
    os.chdir(str(td))
    core.task_dir = Path.cwd()
    task_file = core.task_dir / "task.yaml"
    if not task_file.is_file():
        raise CMSAOIError(f"{task_file} does not exist!")

    # Load config
    try:
        config = load_yaml_with_extends(task_file)
    except yaml.YAMLError as err:
        _LOGGER.error("Invalid YAML syntax:")
        _LOGGER.error(str(err))
        return 1

    # Validate config
    try:
        config = CONFIG_SCHEMA(config)
    except vol.Invalid as err:
        _LOGGER.error("Invalid configuration:")
        _LOGGER.error(humanize_error(config, err))
        raise CMSAOIError() from err

    latex_config = config[CONF_LATEX_CONFIG]
    core.latexmk_args = latex_config[CONF_LATEXMK_ARGS]
    core.gcc_args = config[CONF_CPP_CONFIG][CONF_GCC_ARGS]
    core.config = config
    return config


def _build_config(config):
    all_rules, config = find_rules(config)
    core.config = config
    patch_pth()

    core.internal_dir.mkdir(exist_ok=True)
    core.result_dir.mkdir(exist_ok=True)

    # Execute all rules synchronously
    ninja_build_file = core.internal_dir / "build.ninja"
    fh = io.StringIO()
    writer = ninja_syntax.Writer(fh)
    writer.variable("TASKDIR", str(core.task_dir))
    for klass in rule.registered_rules.values():
        klass.write_rule(writer)
    for rule_ in all_rules.values():
        rule_.write_build(writer)
    fh.seek(0)
    content = fh.read()
    fh.close()

    write_if_changed(content, ninja_build_file)

    _LOGGER.info("Running ninja -f %s", ninja_build_file)
    try:
        subprocess.run(["ninja", "-f", str(ninja_build_file)], check=True)
    except subprocess.CalledProcessError as err:
        _LOGGER.error("Build failed, please see log output above")
        raise CMSAOIError() from err
    except FileNotFoundError as err:
        _LOGGER.error("ninja build system is not installed, exiting")
        raise CMSAOIError() from err

    _LOGGER.info(f"Build result written to {core.result_dir}")
    return all_rules


def command_info(args):
    from cmsaoi.cms_upload import get_task_info

    return get_task_info(args.task)


def command_build(args):
    config = _load_config(args.task_dir)
    _build_config(config)
    return 0


def command_test(args):
    _LOGGER.error("Sorry, not implemented yet.")
    _LOGGER.error(
        "Instead you can use `cmsAOI build` to build testcases and run the locally"
    )
    return 1


def command_clean(args):
    temp_dir = Path(args.task_dir) / ".aoi-temp"
    if temp_dir.is_dir():
        shutil.rmtree(temp_dir)
        _LOGGER.info(f"Removed {temp_dir}")
    else:
        _LOGGER.info("Nothing to clean.")
    return 0


def command_upload(args):
    config = _load_config(args.task_dir)
    all_rules = _build_config(config)

    from cmsaoi.cms_upload import upload_task

    return upload_task(core.config, all_rules, args.contest, args.no_tests)


def command_evaluate(args):
    if not Path(args.source_file).is_file():
        raise ValueError(f"Could not find source file {args.source_file}")
    config = _load_config(args.task_dir)
    _build_config(config)
    config = core.config

    from concurrent.futures import ThreadPoolExecutor
    from multiprocessing import cpu_count

    from cmsaoi.evaluate import compile_submission, evaluate_submission

    executable = compile_submission(config, args.source_file)
    with ThreadPoolExecutor(max_workers=max(1, cpu_count() - 1)) as thread_pool:
        evaluate_submission(thread_pool, config, args.source_file, executable)


def patch_pth():
    # Ugly way to patch the .pth file into site-packages
    site_packages = Path([x for x in sys.path if "site-packages" in x][-1])
    target = site_packages / "cmsaoi.pth"
    if target.exists():
        return
    _LOGGER.info(f"Installing cmsaoi.pth to {target}...")
    try:
        target.write_text(
            "import os;'CMS_AOI_SEED' in os.environ and __import__('random').seed(int(os.environ['CMS_AOI_SEED']))"
        )
    except OSError:
        _LOGGER.info(
            "Installing cmsaoi.path failed! Testcases won't have a stable random seed!"
        )


def find_rules(config):
    all_rules: Dict[Path, rule.NinjaRule] = {}

    def register_rule(rule_: rule.NinjaRule):
        outfile = rule_.output.absolute()
        all_rules[outfile] = rule_
        for dep in rule_.extra_rules:
            # Add dependencies to all_rules table too
            register_rule(dep)
        return str(outfile.relative_to(core.task_dir))

    def visit_item(value, path):
        if isinstance(value, AOITag):
            rule.base_directory.set(value.base_directory)
            rule.path_in_config.set(path)
            rule_ = value.rule_type(value.value)
            rule_.friendly_name = f"{value.tag} {value.value}".replace("\n", "")[:32]

            return str(register_rule(rule_))
        return value

    # Recursively visit all parts of config to find all rules to be evaluated
    config = recursive_visit(config, visit_item)
    # Compile output for each testcase with sample solution
    if CONF_SAMPLE_SOLUTION in config:
        sample_solution = config[CONF_SAMPLE_SOLUTION]
        sample_sol_file = Path(sample_solution).absolute()
        for i, subtask in enumerate(config[CONF_SUBTASKS], start=1):
            for j, testcase in enumerate(subtask[CONF_TESTCASES], start=1):
                if CONF_OUTPUT in testcase:
                    # Output already exists
                    continue
                inp = Path(testcase[CONF_INPUT]).absolute()
                rule_ = rule.InternalSampleSolutionNinja(str(sample_sol_file), str(inp))
                testcase[CONF_OUTPUT] = register_rule(rule_)
    else:
        for i, subtask in enumerate(config[CONF_SUBTASKS], start=1):
            for j, testcase in enumerate(subtask[CONF_TESTCASES], start=1):
                if CONF_OUTPUT in testcase:
                    # Output already exists
                    continue
                rule_ = rule.RawNinja("")
                testcase[CONF_OUTPUT] = register_rule(rule_)

    for i, subtask in enumerate(config[CONF_SUBTASKS], start=1):
        for j, testcase in enumerate(subtask[CONF_TESTCASES], start=1):
            tc_name = f"{i:02d}_{j:02d}"
            result_in = core.result_dir / f"{tc_name}.in"
            result_out = core.result_dir / f"{tc_name}.out"

            register_rule(rule.InternalCopyNinja(testcase[CONF_INPUT], result_in))
            register_rule(rule.InternalCopyNinja(testcase[CONF_OUTPUT], result_out))

            if CONF_TESTCASE_CHECKER in config:
                tc_checker_file = Path(config[CONF_TESTCASE_CHECKER]).absolute()
                register_rule(
                    rule.InternalTestcaseCheckerNinja(
                        str(tc_checker_file), str(result_in), i, tc_name
                    )
                )

    for lang, statement in config[CONF_STATEMENTS].items():
        register_rule(
            rule.InternalCopyNinja(statement, core.result_dir / f"{lang}.pdf")
        )
    for fname, attachment in config[CONF_ATTACHMENTS].items():
        register_rule(rule.InternalCopyNinja(attachment, core.result_dir / fname))
    if CONF_CHECKER in config:
        register_rule(
            rule.InternalCopyNinja(config[CONF_CHECKER], core.result_dir / "checker")
        )
    for grader in config[CONF_GRADER]:
        register_rule(
            rule.InternalCopyNinja(grader, core.result_dir / Path(grader).name)
        )
    if CONF_SAMPLE_SOLUTION in config:
        register_rule(
            rule.InternalCopyNinja(
                config[CONF_SAMPLE_SOLUTION], core.result_dir / "samplesol"
            )
        )

    return all_rules, config


if __name__ == "__main__":
    sys.exit(main() or 0)
