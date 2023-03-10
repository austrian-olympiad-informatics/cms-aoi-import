import concurrent.futures
import logging
import math
import os
import resource
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Tuple, cast

from tabulate import tabulate

from .const import (
    CONF_CHECKER,
    CONF_DECIMAL_PLACES,
    CONF_GRADER,
    CONF_INPUT,
    CONF_MANAGER,
    CONF_MEMORY_LIMIT,
    CONF_NAME,
    CONF_NUM_PROCESSES,
    CONF_OUTPUT,
    CONF_POINTS,
    CONF_SCORE_OPTIONS,
    CONF_STDIN_FILENAME,
    CONF_STDOUT_FILENAME,
    CONF_SUBTASKS,
    CONF_TASK_TYPE,
    CONF_TESTCASES,
    CONF_TIME_LIMIT,
    CONF_TYPE,
    CONF_USER_IO,
    SCORE_TYPE_GROUP_MIN,
    SCORE_TYPE_GROUP_MUL,
    SCORE_TYPE_SUM,
    TASK_TYPE_BATCH,
    TASK_TYPE_COMMUNICATION,
)

_LOGGER = logging.getLogger(__name__)


class Language(Enum):
    CPP20 = "CPP20"
    CSHARP = "CSHARP"
    GO = "GO"
    JAVA = "JAVA"
    JAVASCRIPT = "JAVASCRIPT"
    KOTLIN = "KOTLIN"
    PYTHON3 = "PYTHON3"
    RUST = "RUST"
    TYPESCRIPT = "TYPESCRIPT"
    HASKELL = "HASKELL"
    SWIFT = "SWIFT"


def match_language(fname: str | Path) -> Language:
    suffix = Path(fname).suffix.lower()
    lang_mapping = {
        ".cpp": Language.CPP20,
        ".cxx": Language.CPP20,
        ".c++": Language.CPP20,
        ".h": Language.CPP20,
        ".cs": Language.CSHARP,
        ".go": Language.GO,
        ".java": Language.JAVA,
        ".js": Language.JAVASCRIPT,
        ".kt": Language.KOTLIN,
        ".py": Language.PYTHON3,
        ".rs": Language.RUST,
        ".ts": Language.TYPESCRIPT,
        ".hs": Language.HASKELL,
        ".swift": Language.SWIFT,
    }
    if suffix not in lang_mapping:
        raise ValueError(
            f"Unknown file type {fname} (could not get language from suffix)"
        )
    return lang_mapping[suffix]


class CompilationError(Exception):
    pass


class EvaluationError(Exception):
    pass


def _compile_sub(source_path: Path, config, compile_dir: Path) -> Path:
    def execute(args):
        args_h = " ".join(shlex.quote(x) for x in args)
        _LOGGER.debug("Compile: Executing %s", args_h)
        try:
            subprocess.run(args, check=True, cwd=str(compile_dir))
        except subprocess.CalledProcessError:
            raise CompilationError(
                f"Command {args_h} in directory {str(compile_dir)} failed"
            )

    def copyfile(path: Path, fname: str):
        shutil.copyfile(path, compile_dir / fname)

    lang = match_language(source_path)
    task_name = config[CONF_NAME]
    grader_files: list[Path] = [
        Path(x) for x in config[CONF_GRADER] if match_language(x) == lang
    ]
    if lang == Language.CPP20:
        sources = []
        for path in grader_files:
            copyfile(path, path.name)
            if path.name.lower().endswith(".cpp"):
                sources.append(path.name)
        copyfile(source_path, f"{task_name}.cpp")
        sources.append(f"{task_name}.cpp")
        execute(
            [
                "/usr/bin/g++",
                "-DEVAL",
                "-std=c++20",
                "-O2",
                "-pipe",
                "-Wno-unused-result",
                "-s",
                "-o",
                task_name,
                *sources,
            ]
        )
        output_file = task_name
    elif lang == Language.CSHARP:
        sources = []
        for path in grader_files:
            copyfile(path, path.name)
            sources.append(path.name)
        copyfile(source_path, f"{task_name}.cs")
        sources.append(f"{task_name}.cs")
        execute(["/usr/bin/mcs", f"-out:{task_name}.exe", "-optimize+", *sources])
        output_file = f"{task_name}.exe"
    elif lang == Language.GO:
        sources = []
        for path in grader_files:
            copyfile(path, path.name)
            sources.append(path.name)
        copyfile(source_path, f"{task_name}.go")
        sources.append(f"{task_name}.go")
        execute(
            ["/usr/bin/go", "build", "-ldflags", "-s -w", "-o", task_name, *sources]
        )
        output_file = task_name
    elif lang == Language.HASKELL:
        sources = []
        for path in grader_files:
            copyfile(path, path.name)
            sources.append(path.name)
        copyfile(source_path, f"{task_name.title()}.hs")
        sources.append(f"{task_name.title()}.hs")
        execute(["/usr/bin/ghc", "-static", "-O2", "-Wall", "-o", task_name, *sources])
        output_file = task_name
    elif lang == Language.JAVA:
        sources = []
        for path in grader_files:
            copyfile(path, path.name)
            sources.append(path.name)
        copyfile(source_path, f"{task_name}.java")
        sources.append(f"{task_name}.java")
        execute(["/usr/bin/javac", *sources])
        class_files = [p.name for p in compile_dir.glob("*.class")]
        execute(
            [
                "/usr/bin/jar",
                "-cvfe",
                f"{task_name}.jar",
                next(iter(sources))[:-5],
                *class_files,
            ]
        )
        output_file = f"{task_name}.jar"
    elif lang == Language.KOTLIN:
        sources = []
        for path in grader_files:
            copyfile(path, path.name)
            sources.append(path.name)
        copyfile(source_path, f"{task_name}.kt")
        sources.append(f"{task_name}.kt")
        execute(
            ["/usr/bin/kotlinc", "-include-runtime", "-d", f"{task_name}.jar", *sources]
        )
        output_file = f"{task_name}.jar"
    elif lang == Language.PYTHON3:
        sources = []
        for path in grader_files:
            copyfile(path, path.name)
            sources.append(path.name)
        copyfile(source_path, f"{task_name.lower()}.py")
        sources.append(f"{task_name.lower()}.py")
        execute(["/usr/bin/python3", "-m", "compileall", "-b", "."])
        files_to_package = []
        for idx, fname in enumerate(sources):
            if idx == 0:
                shutil.move(compile_dir / (fname + "c"), compile_dir / "__main__.pyc")
                files_to_package.append("__main__.pyc")
            else:
                files_to_package.append(fname + "c")
        output_file = f"{task_name}.pyz"
        execute(["/usr/bin/zip", output_file, *files_to_package])
    elif lang == Language.RUST:
        sources = []
        for path in grader_files:
            copyfile(path, path.name)
            sources.append(path.name)
        copyfile(source_path, f"{task_name.lower()}.rs")
        sources.append(f"{task_name.lower()}.rs")
        # In Rust only the source file containing the main function has
        # to be passed to the compiler
        execute(
            [
                "/usr/bin/rustc",
                "-O",
                "-Cprefer-dynamic",
                "-o",
                task_name,
                next(iter(sources)),
            ]
        )
        output_file = task_name
    else:
        raise ValueError(f"Unknown language for compilation {lang}")
    return compile_dir / output_file


def _execute_command(
    config, lang: Language, executable_fname: str, args: list[str]
) -> list[str]:
    if lang == Language.CPP20:
        return [f"./{executable_fname}", *args]
    elif lang == Language.CSHARP:
        return ["/usr/bin/mono", executable_fname, *args]
    elif lang == Language.GO:
        return [f"./{executable_fname}", *args]
    elif lang == Language.HASKELL:
        return [f"./{executable_fname}", *args]
    elif lang == Language.JAVA:
        return [
            "/usr/bin/java",
            "-Deval=true",
            "-Xmx512M",
            "-Xss128M",
            "-jar",
            executable_fname,
            *args,
        ]
    elif lang == Language.KOTLIN:
        return [
            "/usr/bin/java",
            "-Deval=true",
            "-Xmx512M",
            "-Xss128M",
            "-jar",
            executable_fname,
            *args,
        ]
    elif lang == Language.PYTHON3:
        return ["/usr/bin/python3", executable_fname, *args]
    elif lang == Language.RUST:
        return [f"./{executable_fname}", *args]
    elif lang == Language.SWIFT:
        return [f"./{executable_fname}", *args]
    else:
        raise ValueError(f"Unknown language for execution {lang}")


def compile_submission(config, source_file: Path) -> Path:
    tmpdir = tempfile.mkdtemp(prefix="aoi-compile-")
    _LOGGER.info("Compiling %s in directory %s", source_file, tmpdir)
    output_file = _compile_sub(source_file, config, Path(tmpdir))
    _LOGGER.info("Compilation done")
    return output_file


@dataclass
class ExecuteStats:
    cpu_time: float
    wall_clock_time: float
    memory_usage: int


class Executor:
    def __init__(
        self,
        *,
        cmd: list[str],
        cwd: Path,
        time_limit_s: float | None = None,
        wall_clock_time_limit_s: float | None = None,
        memory_limit_bytes: int | None = None,
        stdin: Path | int = subprocess.DEVNULL,
        stdout: Path | int = subprocess.DEVNULL,
        stderr: Path | int = subprocess.DEVNULL,
    ) -> None:
        self._cmd = cmd
        self._cwd = cwd
        self._time_limit_s = time_limit_s
        self._wall_clock_time_limit_s = wall_clock_time_limit_s
        self._memory_limit_bytes = memory_limit_bytes
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._start_time = None
        self._end_time: float | None = None
        self._proc: subprocess.Popen | None = None
        self._cpu_time: float | None = None
        self._memory_used: int | None = None
        self.returncode: int | None = None
        self.wall_clock_limit_exceeded: bool = False

    def execute(self):
        stdin_fd = subprocess.DEVNULL
        if not isinstance(self._stdin, int):
            stdin_fd = os.open(self._stdin, os.O_RDONLY)
        stdout_fd = subprocess.DEVNULL
        if not isinstance(self._stdout, int):
            stdout_fd = os.open(
                self._stdout,
                os.O_WRONLY | os.O_TRUNC | os.O_CREAT,
                stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR,
            )
        stderr_fd = subprocess.DEVNULL
        if not isinstance(self._stderr, int):
            stderr_fd = os.open(
                self._stderr,
                os.O_WRONLY | os.O_TRUNC | os.O_CREAT,
                stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR,
            )

        def preexec_fn():
            os.chdir(str(self._cwd))
            if self._time_limit_s is not None:
                resource.setrlimit(
                    resource.RLIMIT_CPU,
                    (int(self._time_limit_s), int(self._time_limit_s)),
                )
            if self._memory_limit_bytes is not None:
                resource.setrlimit(
                    resource.RLIMIT_AS,
                    (self._memory_limit_bytes, self._memory_limit_bytes),
                )
                resource.setrlimit(
                    resource.RLIMIT_STACK,
                    (self._memory_limit_bytes, self._memory_limit_bytes),
                )
                resource.setrlimit(
                    resource.RLIMIT_DATA,
                    (self._memory_limit_bytes, self._memory_limit_bytes),
                )

        self._start_time = time.monotonic()
        self._proc = subprocess.Popen(  # pylint: disable=consider-using-with,subprocess-popen-preexec-fn
            self._cmd,
            stdin=stdin_fd,
            stdout=stdout_fd,
            stderr=stderr_fd,
            preexec_fn=preexec_fn,
            close_fds=True,
        )

        # Close the fds in the parent
        for fd in [stdin_fd, stdout_fd, stderr_fd]:
            if fd != subprocess.DEVNULL:
                os.close(fd)

        if self._proc.stdin:
            self._proc.stdin.close()

    def wait(self) -> None:
        if self._proc is None:
            raise ValueError("Executor not started")
        finished_event = threading.Event()

        def wall_clock_killer():
            finished_event.wait(timeout=self._wall_clock_time_limit_s)
            if self._proc.returncode is not None:
                return
            self.wall_clock_limit_exceeded = True
            try:
                self._proc.kill()
            except OSError:
                pass

        if self._wall_clock_time_limit_s:
            threading.Thread(target=wall_clock_killer).start()

        _, waits, rus = os.wait4(self._proc.pid, 0)
        self._end_time = time.monotonic()
        self._proc.returncode = os.waitstatus_to_exitcode(waits)
        finished_event.set()

        self._cpu_time = rus.ru_utime + rus.ru_stime
        self._memory_used = rus.ru_maxrss
        self.returncode = self._proc.returncode

    def stats(self) -> ExecuteStats:
        if (
            self._cpu_time is None
            or self._end_time is None
            or self._start_time is None
            or self._memory_used is None
        ):
            raise ValueError("Executor not finished")
        return ExecuteStats(
            cpu_time=self._cpu_time,
            wall_clock_time=self._end_time - self._start_time,
            memory_usage=self._memory_used,
        )


class EvaluateMessage(Enum):
    SUCCESS = "success"
    RETURNCODE = "returncode"
    SIGNAL = "signal"
    TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
    WALL_CLOCK_LIMIT_EXCEEDED = "wall_clock_limit_exceeded"


@dataclass
class EvaluateResult:
    type: EvaluateMessage = EvaluateMessage.SUCCESS
    cpu_time: float | None = None
    wall_clock_time: float | None = None
    memory_usage: int | None = None
    returncode: int | None = None
    signal: int | None = None
    signal_name: str | None = None
    score: float | None = None
    text: str | None = None
    directories: list[Path] | None = None


def _white_diff(fd1: BinaryIO, fd2: BinaryIO) -> bool:
    while True:
        b1 = fd1.readline()
        b2 = fd2.readline()
        if not b1 and not b2:
            return True

        if not b1 or not b2:
            if b1.strip() or b2.strip():
                return False

        if b1.split() != b2.split():
            return False


def evaluate_testcase(
    config,
    source_file: Path,
    executable: Path,
    input_file: Path,
    output_file: Path | None = None,
    correct_output_file: Path | None = None,
    enforce_limits: bool = True,
) -> EvaluateResult:
    lang = match_language(source_file)
    conf = config[CONF_TASK_TYPE]
    task_type = conf[CONF_TYPE]
    ret = EvaluateResult(directories=[], score=0.0)
    assert ret.directories is not None
    if task_type == TASK_TYPE_BATCH:
        exec_dir = Path(tempfile.mkdtemp(prefix="aoi-eval-"))
        ret.directories.append(exec_dir)
        shutil.copyfile(executable, exec_dir / executable.name)
        shutil.copymode(executable, exec_dir / executable.name)
        stdin: Path | int = subprocess.DEVNULL
        if conf[CONF_STDIN_FILENAME]:
            shutil.copyfile(input_file, exec_dir / conf[CONF_STDIN_FILENAME])
        else:
            stdin = exec_dir / "stdin.txt"
            shutil.copyfile(input_file, stdin)

        if conf[CONF_STDOUT_FILENAME]:
            stdout = exec_dir / conf[CONF_STDOUT_FILENAME]
            proc_stdout = exec_dir / "proc_stdout.txt"
        else:
            stdout = exec_dir / "stdout.txt"
            proc_stdout = exec_dir / "stdout.txt"

        stderr = exec_dir / "stderr.txt"
        cmd = _execute_command(config, lang, executable.name, [])
        _LOGGER.debug(
            "Executing %s in %s", " ".join(shlex.quote(x) for x in cmd), exec_dir
        )
        kwargs = (
            {
                "time_limit_s": config[CONF_TIME_LIMIT],
                "wall_clock_time_limit_s": config[CONF_TIME_LIMIT] * 2 + 5,
                "memory_limit_bytes": int(config[CONF_MEMORY_LIMIT] * 1024 * 1024),
            }
            if enforce_limits
            else {}
        )
        executor = Executor(
            cmd=cmd,
            cwd=exec_dir,
            stdin=stdin,
            stdout=proc_stdout,
            stderr=stderr,
            **kwargs,
        )
        executor.execute()
        executor.wait()
        stats = executor.stats()
        ret.cpu_time = stats.cpu_time
        ret.wall_clock_time = stats.wall_clock_time
        ret.memory_usage = stats.memory_usage
        msg = EvaluateMessage.SUCCESS
        if executor.wall_clock_limit_exceeded:
            msg = EvaluateMessage.WALL_CLOCK_LIMIT_EXCEEDED
            ret.text = "Wall clock limit exceeded"
        elif cast(int, executor.returncode) < 0:
            msg = EvaluateMessage.SIGNAL
            assert executor.returncode is not None
            ret.signal = (  # pylint: disable-next=invalid-unary-operand-type
                -executor.returncode
            )
            ret.signal_name = signal.strsignal(ret.signal)
            ret.text = f"Signal: {ret.signal_name}"
        elif cast(int, executor.returncode) > 0:
            msg = EvaluateMessage.RETURNCODE
            ret.returncode = executor.returncode
            ret.text = f"Bad Exit Code: {ret.returncode}"
        # todo TIME_LIMIT_EXCEEDED
        ret.type = msg
        if msg != EvaluateMessage.SUCCESS or correct_output_file is None:
            return ret

        if output_file is not None:
            shutil.copyfile(stdout, output_file)

        if CONF_CHECKER in config:
            checker_dir = Path(tempfile.mkdtemp("aoi-checker-"))
            ret.directories.append(checker_dir)
            shutil.copyfile(config[CONF_CHECKER], checker_dir / "checker")
            os.chmod(checker_dir / "checker", 0o755)
            shutil.copyfile(input_file, checker_dir / "input.txt")
            shutil.copyfile(correct_output_file, checker_dir / "correct_output.txt")
            shutil.copyfile(stdout, checker_dir / "user_output.txt")
            checker_stdout = checker_dir / "stdout.txt"
            checker_stderr = checker_dir / "stderr.txt"

            checker_executor = Executor(
                cmd=["./checker", "input.txt", "correct_output.txt", "user_output.txt"],
                cwd=checker_dir,
                stdout=checker_stdout,
                stderr=checker_stderr,
            )
            checker_executor.execute()
            checker_executor.wait()
            if checker_executor.returncode != 0:
                raise EvaluationError(
                    f"Checker failed with return code {checker_executor.returncode}"
                )
            checker_stats = checker_executor.stats()
            _LOGGER.debug("Checker stats: %s", checker_stats)
            if not checker_stdout.is_file():
                raise EvaluationError(f"Checker did not write file {checker_stdout}")
            if not checker_stderr.is_file():
                raise EvaluationError(f"Checker did not write file {checker_stderr}")
            score_txt = checker_stdout.read_text().splitlines()[0]
            try:
                score = float(score_txt)
            except ValueError:
                raise EvaluationError(f"Checker score is not a float: {score_txt}")
            text = checker_stderr.read_text().splitlines()[0]
            if text.startswith("translate:"):
                text = {
                    "translate:success": "Output is correct",
                    "translate:partial": "Output is partially correct",
                    "translate:wrong": "Output isn't correct",
                }.get(text, text)
            ret.score = score
            ret.text = text

        else:
            with stdout.open("rb") as fd1, correct_output_file.open("rb") as fd2:
                is_correct = _white_diff(fd1, fd2)
            ret.score = 1.0 if is_correct else 0.0
            ret.text = "Output is correct" if is_correct else "Output isn't correct"

        return ret
    elif task_type == TASK_TYPE_COMMUNICATION:
        n = conf[CONF_NUM_PROCESSES]
        manager_dir = Path(tempfile.mkdtemp(prefix="cms-aoi-manager-"))
        ret.directories.append(manager_dir)
        os.chmod(manager_dir, 0o755)
        shutil.copyfile(conf[CONF_MANAGER], manager_dir / "manager")
        os.chmod(manager_dir / "manager", 0o755)
        manager_stdin = manager_dir / "input.txt"
        shutil.copyfile(input_file, manager_stdin)
        shutil.copyfile(source_file, manager_dir / "submission.txt")

        fifo_u2ms = [manager_dir / f"u{i}_to_m" for i in range(n)]
        fifo_m2us = [manager_dir / f"m_to_u{i}" for i in range(n)]
        for fifo in fifo_m2us + fifo_u2ms:
            os.mkfifo(fifo)
            os.chmod(fifo, 0o666)

        manager_cmd = ["./manager"]
        for i in range(n):
            manager_cmd += [str(fifo_u2ms[i]), str(fifo_m2us[i])]
        manager_time_limit = n * (config[CONF_TIME_LIMIT] + 1.0)
        manager_stderr = manager_dir / "stderr.txt"
        manager_stdout = manager_dir / "stdout.txt"

        _LOGGER.debug(
            "Manager executing %s in %s",
            " ".join(shlex.quote(x) for x in manager_cmd),
            manager_dir,
        )
        manager_kwargs = (
            {
                "time_limit_s": manager_time_limit,
                "wall_clock_time_limit_s": manager_time_limit * 2 + 5,
                "memory_limit_bytes": int(4 * 1024 * 1024 * 1024),  # 4 GiB
            }
            if enforce_limits
            else {}
        )
        manager_executor = Executor(
            cmd=manager_cmd,
            cwd=manager_dir,
            stdin=manager_stdin,
            stdout=manager_stdout,
            stderr=manager_stderr,
            **manager_kwargs,
        )

        user_dirs = [Path(tempfile.mkdtemp(prefix="aoi-user-")) for _ in range(n)]
        ret.directories.extend(user_dirs)
        user_executors: list[Executor] = []
        user_kwargs = (
            {
                "time_limit_s": config[CONF_TIME_LIMIT],
                "wall_clock_time_limit_s": config[CONF_TIME_LIMIT] * 2 + 5,
                "memory_limit_bytes": int(config[CONF_MEMORY_LIMIT] * 1024 * 1024),
            }
            if enforce_limits
            else {}
        )
        for i in range(n):
            udir = user_dirs[i]
            shutil.copyfile(executable, udir / executable.name)
            shutil.copymode(executable, udir / executable.name)
            user_stdin: Path | int
            if conf[CONF_USER_IO] == "std_io":
                user_stdin = fifo_m2us[i]
                user_stdout = fifo_u2ms[i]
                args = []
            else:
                user_stdin = subprocess.DEVNULL
                user_stdout = udir / "stdout.txt"
                args = [str(fifo_m2us[i]), str(fifo_u2ms[i])]
            user_stderr = udir / "stderr.txt"
            user_cmd = _execute_command(config, lang, executable.name, args)
            _LOGGER.debug(
                "User %s executing %s in %s",
                i,
                " ".join(shlex.quote(x) for x in user_cmd),
                udir,
            )
            user_executor = Executor(
                cmd=user_cmd,
                cwd=udir,
                stdin=user_stdin,
                stdout=user_stdout,
                stderr=user_stderr,
                **user_kwargs,
            )
            user_executors.append(user_executor)

        manager_executor.execute()
        for uexec in user_executors:
            uexec.execute()

        manager_executor.wait()
        for uexec in user_executors:
            uexec.wait()

        manager_stats = manager_executor.stats()
        _LOGGER.debug("Manager stats: %s", manager_stats)
        if manager_executor.returncode != 0:
            raise EvaluationError(
                f"Manager failed with code {manager_executor.returncode}"
            )
        user_statss = [uexec.stats() for uexec in user_executors]
        ret.cpu_time = sum(u.cpu_time for u in user_statss)
        ret.wall_clock_time = sum(u.wall_clock_time for u in user_statss)
        ret.memory_usage = max(u.memory_usage for u in user_statss)
        for uexec in user_executors:
            msg = EvaluateMessage.SUCCESS
            if uexec.wall_clock_limit_exceeded:
                msg = EvaluateMessage.WALL_CLOCK_LIMIT_EXCEEDED
            elif cast(int, uexec.returncode) < 0:
                msg = EvaluateMessage.SIGNAL
                assert uexec.returncode is not None
                ret.signal = -uexec.returncode
                ret.signal_name = signal.strsignal(-uexec.returncode)
            elif cast(int, uexec.returncode) > 0:
                msg = EvaluateMessage.RETURNCODE
                ret.returncode = uexec.returncode
            ret.type = msg
            if msg != EvaluateMessage.SUCCESS:
                return ret

        score_txt = manager_stdout.read_text().splitlines()[0]
        try:
            score = float(score_txt)
        except ValueError:
            raise EvaluationError(f"Manager score is not a float: {score}")
        text = manager_stderr.read_text().splitlines()[0]
        if text.startswith("translate:"):
            text = {
                "translate:success": "Output is correct",
                "translate:partial": "Output is partially correct",
                "translate:wrong": "Output isn't correct",
            }.get(text, text)
        ret.score = score
        ret.text = text

        return ret
    else:
        raise ValueError(f"Unsupported task type {task_type}")


def evaluate_submission(
    thread_pool: concurrent.futures.ThreadPoolExecutor,
    config,
    source_file: Path,
    executable: Path,
    enforce_limits: bool = True,
):
    futs = {}
    for i, sub in enumerate(config[CONF_SUBTASKS]):
        for j, tc in enumerate(sub[CONF_TESTCASES]):
            corr_output = Path(tc[CONF_OUTPUT]) if CONF_OUTPUT in tc else None
            fut = thread_pool.submit(
                evaluate_testcase,
                config,
                source_file,
                executable,
                tc[CONF_INPUT],
                correct_output_file=corr_output,
                enforce_limits=enforce_limits,
            )
            futs[(i, j)] = fut
    _LOGGER.info("Evaluating submission against %s testcases...", len(futs))
    concurrent.futures.wait(futs.values())
    results: dict[Tuple[int, int], EvaluateResult] = {}
    for (i, j), fut in futs.items():
        results[(i, j)] = fut.result()

    dec_places: int = config[CONF_SCORE_OPTIONS][CONF_DECIMAL_PLACES]
    scoring_type: str = config[CONF_SCORE_OPTIONS][CONF_TYPE]

    for i, sub in enumerate(config[CONF_SUBTASKS]):
        tc_scores: list[float] = [
            cast(float, results[(i, j)].score) for j in range(len(sub[CONF_TESTCASES]))
        ]
        if scoring_type == SCORE_TYPE_GROUP_MIN:
            sub_score = min(tc_scores) * sub[CONF_POINTS]
            max_score = sub[CONF_POINTS]
        elif scoring_type == SCORE_TYPE_GROUP_MUL:
            sub_score = math.prod(tc_scores) * sub[CONF_POINTS]
            max_score = sub[CONF_POINTS]
        elif scoring_type == SCORE_TYPE_SUM:
            sub_score = sum(tc_scores) * sub[CONF_POINTS]
            max_score = sub[CONF_POINTS] * len(sub[CONF_TESTCASES])
        else:
            raise ValueError(f"Unsupported scoring type {scoring_type}")

        sub_score = round(sub_score, dec_places)
        color = (
            "\033[0;32m"
            if sub_score == max_score
            else ("\033[0;31m" if sub_score == 0 else "\033[0;33m")
        )
        print()
        print(
            f"{color}Subtask {i+1}: {sub_score:.{dec_places}f}P / {max_score:.{dec_places}f}P\033[0m"
        )

        header = ["#", "Result", "Details", "Time", "Memory", "Directory"]
        table = []
        for j in range(len(sub[CONF_TESTCASES])):
            r = results[(i, j)]
            result_s = "\033[0;32mCorrect\033[0m"
            assert r.score is not None
            if r.type != EvaluateMessage.SUCCESS or r.score <= 0.0:
                result_s = "\033[0;31mNot correct\033[0m"
            elif r.score < 1.0:
                result_s = "\033[0;33mPartially correct\033[0m"
            assert r.directories is not None
            assert r.memory_usage is not None
            assert r.cpu_time is not None
            table.append(
                [
                    f"{i+1}_{j+1}",
                    result_s,
                    r.text,
                    f"{r.cpu_time:.3f}s",
                    f"{r.memory_usage/1024/1024:.2f}MiB",
                    " ".join(map(str, r.directories)),
                ]
            )
        t = tabulate(table, headers=header, tablefmt="simple_outline")
        print(t)
