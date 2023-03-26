# pylint: disable=import-error
# NOTE: Only import this package locally (not in a module scope)
# because it needs a local cms install
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Union
from uuid import uuid4

import cms.conf  # type: ignore
import cmscommon.constants as cmsconst  # type: ignore
import gevent  # type: ignore
from cms import ServiceCoord  # type: ignore
from cms.db import (  # type: ignore
    Attachment,
    Contest,
    Dataset,
    File,
    LanguageTemplate,
    Manager,
    Meme,
    Participation,
    SessionGen,
    Statement,
    Submission,
    SubmissionResult,
    Task,
    Testcase,
    TestManager,
    User,
    test_db_connection,
)
from cms.db.filecacher import FileCacher  # type: ignore
from cms.grading.languagemanager import LANGUAGES  # type: ignore
from cms.io import RemoteServiceClient  # type: ignore
from cmscontrib.importing import update_task  # type: ignore

from cmsaoi.const import (
    CONF_ATTACHMENTS,
    CONF_CHECKER,
    CONF_CODENAME,
    CONF_DECIMAL_PLACES,
    CONF_DEFAULT_INPUT,
    CONF_EDITOR_TEMPLATES,
    CONF_FEEDBACK_LEVEL,
    CONF_FILE,
    CONF_GEN_NUMBER,
    CONF_GRADER,
    CONF_INITIAL,
    CONF_INPUT,
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
    CONF_SCORE_OPTIONS,
    CONF_STATEMENT_HTML,
    CONF_STATEMENTS,
    CONF_STDIN_FILENAME,
    CONF_STDOUT_FILENAME,
    CONF_SUBTASKS,
    CONF_TASK_TYPE,
    CONF_TEST_GRADER,
    CONF_TEST_SUBMISSIONS,
    CONF_TESTCASES,
    CONF_TIME_LIMIT,
    CONF_TOKENS,
    CONF_TYPE,
    CONF_USER_IO,
    CONF_WEIGHT,
    FEEDBACK_LEVEL_FULL,
    FEEDBACK_LEVEL_RESTRICTED,
    SCORE_MODE_MAX,
    SCORE_MODE_MAX_TOKENED_LAST,
    SCORE_MODE_SUM_SUBTASK_BEST,
    SCORE_TYPE_GROUP_MIN,
    SCORE_TYPE_GROUP_MUL,
    SCORE_TYPE_GROUP_THRESHOLD,
    SCORE_TYPE_SUM,
    TASK_TYPE_BATCH,
    TASK_TYPE_COMMUNICATION,
    TASK_TYPE_OJUZ,
    TASK_TYPE_OUTPUT_ONLY,
    TOKEN_MODE_DISABLED,
    TOKEN_MODE_FINITE,
    TOKEN_MODE_INFINITE,
)
from cmsaoi.core import CMSAOIError

_LOGGER = logging.getLogger(__name__)
_LOGGER.parent.handlers.pop()  # type: ignore

def get_task_info(taskname):
    try:
        test_db_connection()
    except cms.conf.ConfigError as err:
        raise CMSAOIError(f"Database is offline: {err}") from err

    with SessionGen() as session:
        task = session.query(Task).filter(Task.name == taskname).first()
        print(f"ID of task {taskname} is {task.id}")

def upload_task(config, all_rules, contest, no_tests):
    try:
        test_db_connection()
    except cms.conf.ConfigError as err:
        raise CMSAOIError(f"Database is offline: {err}") from err

    file_cacher = FileCacher()

    def put_file(path: Union[str, Path], description):
        if isinstance(path, str):
            path = Path(path)
        return file_cacher.put_file_from_path(str(path), description)

    task = construct_task(config, all_rules, put_file)

    # Commit changes
    commit_task(task, contest)

    if not no_tests:
        if not run_test_submissions(config, put_file):
            return 1
    return 0


def filename_to_langname(contest, filename):
    ext_index = filename.rfind(".")
    if ext_index == -1:
        return None
    ext = filename[ext_index:]
    names = sorted(
        lx.name
        for lx in LANGUAGES
        if ext in lx.source_extensions and lx.name in contest.languages
    )
    return None if len(names) == 0 else names[0]


def run_test_submissions(config, put_file):
    if CONF_TEST_SUBMISSIONS not in config:
        return True

    _LOGGER.info("Uploading test submissions:")

    name = config[CONF_NAME]
    with SessionGen() as session:
        # Re-fetch task (cannot use task object after session closed)
        task: Task = session.query(Task).filter(Task.name == name).one()  # type: ignore

        query = (
            session.query(Participation)
            .join(Participation.user)
            .filter(User.username == "trainer")
        )
        if task.contest is not None:
            query = query.filter(Participation.contest_id == task.contest_id)
        participation = query.first()
        if participation is None:
            raise CMSAOIError(
                f"Test user trainer for uploading test submissions does not exist "
                f"in contest {task.contest_id}"
            )

        if task.contest is None:
            # Set contest of the task to the trainer user contest
            task.contest = participation.contest

        # Upload test submissions
        submissions = []
        for path, points in config[CONF_TEST_SUBMISSIONS].items():
            digest = put_file(path, f"Test submission file {path} for {name}")
            comment = f"Test {Path(path).name} for {points}P"
            lang = filename_to_langname(task.contest, path)
            assert lang is not None
            submission = Submission(
                uuid=str(uuid4()),
                timestamp=datetime.utcnow(),
                language=lang,
                participation=participation,
                task=task,
                comment=comment,
            )
            session.add(
                File(filename=f"{task.name}.%l", digest=digest, submission=submission)
            )
            session.add(submission)
            _LOGGER.info("  - Submission %s for %s points", path, points)
            submissions.append((path, submission, points))
        session.commit()
        # Change submissions array to use submission ID (can't use the object after session closed)
        submissions = [(x, sub.id, z) for x, sub, z in submissions]

    # Connect to Evaluation service and notify of new submission
    _LOGGER.info("Submitting submissions to EvaluationService")
    rs = RemoteServiceClient(ServiceCoord("EvaluationService", 0))
    rs.connect()
    # Wait until connected (and use gevent.sleep to let the greenlet run)
    while not rs.connected:
        gevent.sleep(1)
    for path, subid, points in submissions:
        rs.new_submission(submission_id=subid)
    # Wait a bit to let rs greenlet run (timing issues)
    gevent.sleep(1)
    rs.disconnect()

    _LOGGER.info("Waiting for submissions to be evaluated")

    # Store which submissions have already been scored
    seen = set()
    failed = False
    while True:
        gevent.sleep(1)
        # Recreate session each time (otherwise we'd constantly be seeing the "old" state)
        with SessionGen() as session:
            for path, subid, points in submissions:
                if subid in seen:
                    continue
                # Query database for submission result
                ret: Optional[SubmissionResult] = (
                    session.query(SubmissionResult)
                    .join(SubmissionResult.submission)
                    .filter(Submission.id == subid)
                    .join(Submission.task)
                    .filter(SubmissionResult.filter_scored())
                    .first()
                )
                if ret is None:
                    # Submission has not been scored yet
                    break
                if ret.score != points:
                    _LOGGER.warning(
                        "%s does not have correct score! Expected %sP but returned %sP",
                        path,
                        points,
                        ret.score,
                    )
                    failed = True
                else:
                    _LOGGER.info("%s test passed successfully!", path)
                seen.add(subid)
            else:
                # All submissions scored
                break
    return not failed


def commit_task(task, contest_id):
    with SessionGen() as session:
        # Find existing task (by name)
        old_task = session.query(Task).filter(Task.name == task.name).first()
        if old_task is None:
            # No task with matching name yet, add it as a new one
            _LOGGER.info("Adding task to database")
            session.add(task)
        else:
            # Task already exists, update the object dynamically
            _LOGGER.info("Updating task with ID %s", old_task.id)
            update_task(old_task, task)

        if contest_id is not None:
            contest = session.query(Contest).filter(Contest.id == contest_id).first()
            if contest is None:
                raise CMSAOIError(f"Could not find a contest with ID {contest_id}")
            if contest.id != task.contest_id:
                _LOGGER.info("Adding task to contest %s", contest.id)
                if task.num is None:
                    task.num = len(contest.tasks)
                task.contest_id = contest.id
        # Commit changes
        session.commit()


def construct_task(config, all_rules, put_file):
    _LOGGER.info("Task config:")

    name = config[CONF_NAME]
    _LOGGER.info("  - Name: %s", name)
    long_name = config[CONF_LONG_NAME]
    _LOGGER.info("  - Long Name: %s", long_name)
    _LOGGER.info("")

    score_opt = config[CONF_SCORE_OPTIONS]
    # ================ STATEMENTS ================
    statements = {}
    for lang, pdf in config[CONF_STATEMENTS].items():
        digest = put_file(pdf, f"Statement for task {name} (lang: {lang})")
        statements[lang] = Statement(language=lang, digest=digest)
        _LOGGER.info(
            "  - Statement for language %s: '%s'",
            lang,
            lookup_friendly_filename(all_rules, pdf),
        )
    if not statements:
        _LOGGER.info("  - No task statements!")

    args = {}
    # If there's only one statement, mark it as the primary statement
    if len(statements) == 1:
        args["primary_statements"] = [next(iter(statements.keys()))]
        _LOGGER.info("  - Primary statement: %s", args["primary_statements"][0])

    if CONF_STATEMENT_HTML in config:
        digest = put_file(
            config[CONF_STATEMENT_HTML], f"HTML statement for task {name}"
        )
        args["statement_html_digest"] = digest
        _LOGGER.info(
            "  - HTML statement: '%s'",
            lookup_friendly_filename(all_rules, config[CONF_STATEMENT_HTML]),
        )
    if CONF_DEFAULT_INPUT in config:
        digest = put_file(config[CONF_DEFAULT_INPUT], f"Default input for task {name}")
        args["default_input_digest"] = digest
        _LOGGER.info(
            "  - Default input: '%s'",
            lookup_friendly_filename(all_rules, config[CONF_DEFAULT_INPUT]),
        )

    # ================ ATTACHMENTS ================
    attachments = {}
    for fname, attachment in config[CONF_ATTACHMENTS].items():
        digest = put_file(attachment, f"Attachment {fname} for task {name}")
        attachments[attachment] = Attachment(filename=fname, digest=digest)
        _LOGGER.info(
            "  - Attachment %s: '%s'",
            fname,
            lookup_friendly_filename(all_rules, attachment),
        )
    if not attachments:
        _LOGGER.info("  - No task attachments!")
    _LOGGER.info("")

    subtasks = config[CONF_SUBTASKS]

    # ================ SUBMISSION FORMAT ================
    # Submission format (what the uploaded files are to be called, .%l is replaced by file suffix)
    submission_format = [f"{name}.%l"]
    if config[CONF_TASK_TYPE][CONF_TYPE] == TASK_TYPE_OUTPUT_ONLY:
        # Output only has file for each testcase
        submission_format.clear()
        for i, subtask in enumerate(subtasks, start=1):
            for j, testcase in enumerate(subtask[CONF_TESTCASES], start=1):
                codename = testcase.get(CONF_CODENAME, f"{i:02d}_{j:02d}")
                submission_format.append(f"output_{codename}.txt")
    _LOGGER.info("  - Submission format: '%s'", ", ".join(submission_format))

    # ================ FEEDBACK LEVEL / SCORING ================
    feedback_level = {
        FEEDBACK_LEVEL_FULL: cms.FEEDBACK_LEVEL_FULL,
        FEEDBACK_LEVEL_RESTRICTED: cms.FEEDBACK_LEVEL_RESTRICTED,
    }[config[CONF_FEEDBACK_LEVEL]]
    _LOGGER.info("  - Feedback level: %s", feedback_level)

    score_precision = score_opt[CONF_DECIMAL_PLACES]
    _LOGGER.info("  - Score precision: %s", score_precision)

    cms_score_mode = {
        SCORE_MODE_MAX_TOKENED_LAST: cmsconst.SCORE_MODE_MAX_TOKENED_LAST,
        SCORE_MODE_SUM_SUBTASK_BEST: cmsconst.SCORE_MODE_MAX_SUBTASK,
        SCORE_MODE_MAX: cmsconst.SCORE_MODE_MAX,
    }[score_opt[CONF_MODE]]
    _LOGGER.info("  - Score mode: %s", cms_score_mode)

    tokens = config[CONF_TOKENS]

    cms_token_mode = {
        TOKEN_MODE_DISABLED: "disabled",
        TOKEN_MODE_FINITE: "finite",
        TOKEN_MODE_INFINITE: "infinite",
    }[tokens[CONF_MODE]]

    if CONF_MEMES in config:
        memes = args["memes"] = []
        for conf in config[CONF_MEMES]:
            fname = Path(conf[CONF_FILE]).name
            digest = put_file(conf[CONF_FILE], f"Meme {fname} for task {name}")
            memes.append(
                Meme(
                    filename=fname,
                    digest=digest,
                    min_score=conf[CONF_MIN_SCORE],
                    max_score=conf[CONF_MAX_SCORE],
                    factor=conf[CONF_WEIGHT],
                )
            )

    task = Task(
        name=name,
        title=long_name,
        submission_format=submission_format,
        feedback_level=feedback_level,
        score_precision=score_precision,
        score_mode=cms_score_mode,
        statements=statements,
        attachments=attachments,
        token_mode=cms_token_mode,
        token_gen_initial=tokens[CONF_INITIAL],
        token_gen_number=tokens[CONF_GEN_NUMBER],
        **args,
    )

    _LOGGER.info("")

    # ================ DATASET ================
    # Managers = additional files attached to the dataset (checker, grader files)
    managers = []
    test_managers = []
    language_templates = []

    # ================ GRADER ================
    # How the submission is compiled (alone or with additional grader files)
    compilation_param = "alone"
    for grader in config[CONF_GRADER]:
        # Add grader (files that are compiled together with the user's file)
        grader_path = Path(grader)
        suffix = grader_path.suffix
        digest = put_file(grader, f"Grader for task {name} and ext {suffix}")
        fname = grader_path.name
        if grader_path.suffix == ".cpp":
            if (
                isinstance(config[CONF_TASK_TYPE], dict)
                and config[CONF_TASK_TYPE].get(CONF_TYPE) == "BATCH"
            ):
                fname = "grader.cpp"
            elif (
                isinstance(config[CONF_TASK_TYPE], dict)
                and config[CONF_TASK_TYPE].get(CONF_TYPE) == "COMMUNICATION"
            ):
                fname = "stub.cpp"
            else:
                continue
        managers.append(Manager(filename=fname, digest=digest))
        _LOGGER.info("  - Grader: '%s' (as %s)", grader, fname)
        compilation_param = "grader"
    if not config[CONF_GRADER]:
        _LOGGER.info("  - No graders, submission is compiled directly.")

    # ================ CHECKER ================
    if CONF_CHECKER in config:
        # Check submissions with a checker - a program that is called with parameters:
        #  <INPUT_FILE> <CONTESTANT_OUTPUT> <OUTPUT_FILE>
        # Should print a number from 0.0 (incorrect) to 1.0 (correct)
        digest = put_file(config[CONF_CHECKER], f"Manager for task {name}")
        managers.append(Manager(filename="checker", digest=digest))
        evaluation_param = "comparator"
        _LOGGER.info(
            "  - Testcase output is checked by checker '%s'",
            lookup_friendly_filename(all_rules, config[CONF_CHECKER]),
        )
    else:
        # No checker, validate output with a simple diff (ignoring whitespace)
        evaluation_param = "diff"
        _LOGGER.info("  - Testcase output is checked with an output diff.")

    # ================ SCORE TYPE ================
    # Score type: How scores of the individual testcases are combined to the score of a submission
    score_type = score_opt[CONF_TYPE]
    if score_type == "SUM":
        # Sum score type, add points of all testcases together
        score_type_params = sum(x[CONF_POINTS] for x in subtasks)
        _LOGGER.info("  - Score is computed by a SUM of all testcases.")
    elif score_type == "GROUP_MIN":
        # Group min - For each subtask, multiply lowest testcase result with a fixed number of points
        # In practice means a subtask gets points iff all testcases finish successfully
        score_type_params = [
            (subt[CONF_POINTS], len(subt[CONF_TESTCASES])) for subt in subtasks
        ]
        _LOGGER.info(
            "  - Score is computed by the sum of the minimum score across each subtask."
        )
    else:
        # Other score types not implemented yet
        raise NotImplementedError
    _LOGGER.info("")

    # ================ TESTCASES ================
    testcases = []
    for i, subtask in enumerate(subtasks, start=1):
        _LOGGER.info("  - Subtask %s worth %s points:", i, subtask[CONF_POINTS])
        for j, testcase in enumerate(subtask[CONF_TESTCASES], start=1):
            input_digest = put_file(testcase[CONF_INPUT], f"Input {j} for task {name}")
            output_digest = put_file(
                testcase[CONF_OUTPUT], f"Output {j} for task {name}"
            )
            codename = testcase.get(CONF_CODENAME, f"{i:02d}_{j:02d}")

            tc = Testcase(
                codename=codename,
                public=testcase[CONF_PUBLIC],
                input=input_digest,
                output=output_digest,
            )
            testcases.append(tc)

            _LOGGER.info(
                "    - Testcase %s: Input '%s', Output '%s'",
                codename,
                lookup_friendly_filename(all_rules, testcase[CONF_INPUT]),
                lookup_friendly_filename(all_rules, testcase[CONF_OUTPUT]),
            )
        _LOGGER.info("")
    _LOGGER.info("")

    # ================ TASK TYPE ================
    conf = config[CONF_TASK_TYPE]
    if conf.get(CONF_TYPE) == TASK_TYPE_BATCH:
        # Batch task type, user program is called and a checker (or whitespace diff) is perfomed on output
        # to determine outcome
        task_type_params = [
            # compiled alone (`alone`) or with grader (`grader`)
            compilation_param,
            # I/O, empty for stdin/stdout. Otherwise filenames for input/output files
            [conf[CONF_STDIN_FILENAME], conf[CONF_STDOUT_FILENAME]],
            # Evaluated by white-diff (`diff`) or with checker (`comparator`)
            evaluation_param,
        ]
        task_type = "Batch"
    elif conf.get(CONF_TYPE) == TASK_TYPE_COMMUNICATION:
        task_type_params = [
            # Number of user processes spawned
            conf[CONF_NUM_PROCESSES],
            # compiled alone (`alone`) or with grader (`stub`)
            "stub" if compilation_param == "grader" else "alone",
            # User I/O on stdin/out (std_io) or via fifos (fifo_io)
            conf[CONF_USER_IO],
        ]
        digest = put_file(conf[CONF_MANAGER], f"Communication manager for task {name}")
        managers.append(Manager(filename="manager", digest=digest))
        task_type = "Communication"
    elif conf[CONF_TYPE] == TASK_TYPE_OUTPUT_ONLY:
        task_type_params = [
            # Evaluated by white-diff (`diff`) or with checker (`comparator`)
            evaluation_param
        ]
        task_type = "OutputOnly"
    elif conf.get(CONF_TYPE) == TASK_TYPE_OJUZ:
        task_type_params = [
            # compiled alone (`alone`) or with grader (`grader`)
            compilation_param,
            # I/O, empty for stdin/stdout. Otherwise filenames for input/output files
            ["", ""],
            # Evaluated by white-diff (`diff`) or with checker (`comparator`)
            evaluation_param,
            config[CONF_TASK_TYPE][CONF_OJUZ_KEY],
        ]
        task_type = "Ojuz"
    else:
        raise NotImplementedError

    for path in config[CONF_TEST_GRADER]:
        fname = Path(path).name
        digest = put_file(path, f"Test grader {fname} for task {name}")
        test_managers.append(TestManager(filename=fname, digest=digest))
        _LOGGER.info("  - Test Grader: '%s' (as %s)", path, fname)
    for path in config[CONF_EDITOR_TEMPLATES]:
        fname = Path(path).name
        digest = put_file(path, f"Editor template {fname} for task {name}")
        language_templates.append(LanguageTemplate(filename=fname, digest=digest))
        _LOGGER.info("  - Editor template: '%s' (as %s)", path, fname)
    _LOGGER.info("  - Task Type: %s", task_type)

    # ================ LIMITS ================
    time_limit = config[CONF_TIME_LIMIT]
    _LOGGER.info("  - Time limit: %s s", time_limit)
    memory_limit = int(config[CONF_MEMORY_LIMIT])
    _LOGGER.info("  - Memory limit: %s MiB", memory_limit)
    _LOGGER.info("")

    cms_score_type = {
        SCORE_TYPE_GROUP_MIN: "GroupMin",
        SCORE_TYPE_GROUP_MUL: "GroupMul",
        SCORE_TYPE_GROUP_THRESHOLD: "GroupThreshold",
        SCORE_TYPE_SUM: "Sum",
    }[score_type]

    dataset = Dataset(
        task=task,
        description="Default",
        # managers+testcases are mapped to filename/codename
        managers={m.filename: m for m in managers},
        testcases={tc.codename: tc for tc in testcases},
        time_limit=time_limit,
        memory_limit=memory_limit * 1048576,
        task_type=task_type,
        score_type=cms_score_type,
        task_type_parameters=task_type_params,
        score_type_parameters=score_type_params,
        language_templates={x.filename: x for x in language_templates},
        test_managers={x.filename: x for x in test_managers},
    )
    # Set dataset as the active one
    task.active_dataset = dataset
    return task


def lookup_friendly_filename(all_rules, fname):
    path = Path(fname).absolute()
    if path in all_rules:
        r = all_rules[path]
        if hasattr(r, "friendly_name"):
            return r.friendly_name
        return str(r)
    return fname
