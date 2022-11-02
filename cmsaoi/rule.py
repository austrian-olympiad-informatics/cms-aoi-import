import contextvars
import hashlib
import logging
import shlex
import string
from pathlib import Path
from typing import Dict, List, Union

from cmsaoi.const import CONF_CPP_CONFIG, CONF_GCC_ARGS
from cmsaoi.core import core
from cmsaoi.ninja_syntax import Writer
from cmsaoi.util import stable_hash

_LOGGER = logging.getLogger(__name__)

base_directory = contextvars.ContextVar("base directory")
path_in_config = contextvars.ContextVar("Path in config")


def default_output(
    arg: str, *, prefix: str = "", suffix: str = "", use_path: bool = True
) -> Path:
    allowed = string.digits + string.ascii_letters + "-_."
    arg_filtered = "".join(c for c in arg.replace(" ", "_") if c in allowed)
    hash_arg = arg
    if use_path:
        hash_arg += "$$$".join(map(str, path_in_config.get()))
    fname = prefix + arg_filtered[:32] + stable_hash(hash_arg) + suffix
    return core.internal_dir / fname


def gen_seed(arg: str) -> int:
    h = hashlib.new("sha256")
    h.update(arg.encode())
    for p in path_in_config.get():
        h.update(b"$$$")
        h.update(str(p).encode())
    return int.from_bytes(h.digest()[:4], "big")


class NinjaRule:
    RULE_NAME = None

    def write_rule(self, writer: Writer) -> None:
        raise NotImplementedError

    @classmethod
    def write_build(cls, writer: Writer) -> None:
        raise NotImplementedError

    @property
    def output(self) -> Path:
        if hasattr(self, "_output"):
            return self._output
        raise NotImplementedError

    @property
    def extra_rules(self) -> List["NinjaRule"]:
        return []


registered_rules: Dict[str, NinjaRule] = {}


def register_rule(name: str):
    def decorator(klass):
        assert klass not in registered_rules
        registered_rules[name] = klass
        return klass

    return decorator


@register_rule("!latexcompile")
class LatexCompileNinja(NinjaRule):
    RULE_NAME = "latexcompile"

    def __init__(self, arg: str) -> None:
        self._tex_path = Path(arg)
        self._output = self._tex_path.with_suffix(".pdf").absolute()

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "cd $$(dirname $in); SOURCE_DATE_EPOCH=0 latexmk -latexoption=-interaction=nonstopmode -pdf $$(basename $in)"
        desc = "!latexcompile $in"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        outputs = [str(self.output)]
        inputs = [str(self._tex_path)]
        writer.build(outputs, self.RULE_NAME, inputs)


@register_rule("!cppcompile")
class CppCompileNinja(NinjaRule):
    RULE_NAME = "cppcompile"

    def __init__(self, arg: str) -> None:
        self.inputs = []
        self.extraflags = []
        for x in shlex.split(arg):
            p = Path(x)
            if p.suffix in (".h", ".cpp", ".c", ".cc"):
                self.inputs.append(p)
            else:
                self.extraflags.append(x)
        self._output = default_output(
            arg, prefix="cppcompile_", suffix=".exec", use_path=False
        )

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cppflags = core.config[CONF_CPP_CONFIG][CONF_GCC_ARGS]
        writer.variable("cppflags", cppflags)
        writer.variable("extracppflags", "")

        cmd = "g++ -MD -MF $out.d $cppflags $extracppflags $in -o $out"
        desc = "!cppcompile $extracppflags $in"
        writer.rule(cls.RULE_NAME, cmd, depfile="$out.d", description=desc)

    def write_build(self, writer: Writer) -> None:
        outputs = [str(self.output)]
        inputs = list(map(str, self.inputs))
        variables = {}
        if self.extraflags:
            variables["extracppflags"] = " ".join(self.extraflags)
        writer.build(outputs, self.RULE_NAME, inputs, variables=variables)


@register_rule("!cpprun")
class CppRunNinja(NinjaRule):
    RULE_NAME = "cpprun"

    def __init__(self, arg: str) -> None:
        args = shlex.split(arg)
        self._compile_rule = CppCompileNinja(args[0])
        self._output = default_output(arg, prefix="cpprun_")
        self._args = args[1:]
        self._seed = gen_seed(arg)

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "CMS_AOI_SEED=$aoiseed $in $args >$out"
        desc = "!cpprun $in $args"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        outputs = [str(self.output)]
        inputs = [str(self._compile_rule.output)]
        writer.build(
            outputs,
            self.RULE_NAME,
            inputs,
            variables={
                "args": self._args,
                "aoiseed": str(self._seed),
            },
        )

    @property
    def extra_rules(self) -> List["NinjaRule"]:
        return [self._compile_rule]


@register_rule("!shell")
class ShellNinja(NinjaRule):
    RULE_NAME = "shell"

    def __init__(self, arg: str) -> None:
        self._arg = shlex.split(arg)
        self._output = default_output(arg, prefix="shell_")
        self._inputs = [Path(x) for x in shlex.split(arg) if Path(x).is_file()]

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "$args >$out"
        desc = "!shell $args"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        outputs = [str(self.output)]
        inputs = list(map(str, self._inputs))
        writer.build(outputs, self.RULE_NAME, inputs, variables={"args": self._arg})


@register_rule("!internal_sample_solution")
class InternalSampleSolutionNinja(NinjaRule):
    RULE_NAME = "internal_sample_solution"

    def __init__(self, sample_sol: str, stdin_file: str) -> None:
        self._sample_sol = sample_sol
        self._stdin_file = stdin_file
        self._output = default_output(
            f"{sample_sol} {stdin_file}", prefix="samplesol_", use_path=False
        )

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "$samplesol <$in >$out"
        desc = "!samplesol $in"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        inputs = [self._stdin_file]
        outputs = [str(self.output)]
        writer.build(
            outputs,
            self.RULE_NAME,
            inputs,
            implicit=[self._sample_sol],
            variables={"samplesol": self._sample_sol},
        )


@register_rule("!internal_testcase_checker")
class InternalTestcaseCheckerNinja(NinjaRule):
    RULE_NAME = "internal_testcase_checker"

    def __init__(
        self, testcase_checker: str, stdin_file: str, subtask: int, friendly_name: str
    ) -> None:
        self._testcase_checker = testcase_checker
        self._stdin_file = stdin_file
        self._subtask = subtask
        key = f"{testcase_checker} {stdin_file} {subtask}"
        self._output = default_output(
            key, prefix="testcase_checker_", suffix=".empty", use_path=False
        )
        self._friendly_name = friendly_name

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "$testcasechecker $subtask <$in && touch $out"
        desc = "!testcase_checker $friendlyname"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        inputs = [self._stdin_file]
        outputs = [str(self.output)]
        writer.build(
            outputs,
            self.RULE_NAME,
            inputs,
            implicit=[self._testcase_checker],
            variables={
                "testcasechecker": self._testcase_checker,
                "subtask": str(self._subtask),
                "friendlyname": self._friendly_name,
            },
        )


@register_rule("!pyrun")
class PyRunNinja(NinjaRule):
    RULE_NAME = "pyrun"

    def __init__(self, arg: str) -> None:
        args = shlex.split(arg)
        self._py_file = Path(args[0])
        self._args = args[1:]
        self._output = default_output(arg, prefix="pyrun_", suffix=".txt")
        self._seed = gen_seed(arg)

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "CMS_AOI_SEED=$aoiseed python3 $in $args >$out"
        desc = "!pyrun $in $args"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        outputs = [str(self.output)]
        inputs = [str(self._py_file)]
        writer.build(
            outputs,
            self.RULE_NAME,
            inputs,
            variables={"args": " ".join(self._args), "aoiseed": str(self._seed)},
        )


@register_rule("!raw")
class RawNinja(NinjaRule):
    def __init__(self, arg: str) -> None:
        self._output = default_output(arg, use_path=False, prefix="raw_", suffix=".txt")
        self._arg = arg

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        pass

    def write_build(self, writer: Writer) -> None:
        if self._output.is_file() and self._output.read_text() == self._arg:
            return
        self._output.write_text(self._arg)


@register_rule("!pyinline")
class PyInlineNinja(NinjaRule):
    RULE_NAME = "pyinline"

    def __init__(self, arg: str) -> None:
        self._raw_rule = RawNinja(arg)
        self._run_rule = PyRunNinja(str(self._raw_rule.output))
        self._output = self._run_rule.output

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        pass

    def write_build(self, writer: Writer) -> None:
        pass

    @property
    def extra_rules(self) -> List["NinjaRule"]:
        return [self._raw_rule, self._run_rule]


@register_rule("!zip")
class ZipNinja(NinjaRule):
    RULE_NAME = "zip"

    def __init__(self, rarg: str) -> None:
        self._input_files = []
        self._prog_args = []
        for arg in shlex.split(rarg):
            if "*" in arg:
                assert "=" not in arg
                for p in Path.cwd().glob(arg):
                    self._prog_args.append(f"{p.name}={p}")
                    self._input_files.append(p)
                continue

            if "=" in arg:
                zipname, pathname = arg.split("=")
            else:
                zipname = Path(arg).name
                pathname = arg
            path = Path(pathname)
            self._prog_args.append(f"{zipname}={path}")
            self._input_files.append(path)
        self._output = default_output(
            rarg, prefix="zip_", suffix=".zip", use_path=False
        )
        self._arg = rarg

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "_cmsAOIzip $out $members"
        desc = "!zip $arg"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        outputs = [str(self.output)]
        inputs = list(map(str, self._input_files))
        writer.build(
            outputs,
            self.RULE_NAME,
            inputs,
            variables={
                "members": " ".join(shlex.quote(x) for x in self._prog_args),
                "arg": self._arg,
            },
        )


@register_rule("!mdcompile")
class MDCompileNinja(NinjaRule):
    RULE_NAME = "mdcompile"

    def __init__(self, arg: str) -> None:
        self._arg = arg
        self._output = default_output(
            arg, prefix="mdcompile_", suffix=".html", use_path=False
        )

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "pandoc --katex --embed-resources --highlight-style=pygments -V lang=de --html-q-tags --resource-path=$$(dirname $in) $in -o $out"
        desc = "!mdcompile $in"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        outputs = [str(self.output)]
        inputs = [self._arg]
        writer.build(outputs, self.RULE_NAME, inputs)


@register_rule("!gunzip")
class GunzipNinja(NinjaRule):
    RULE_NAME = "gunzip"

    def __init__(self, arg: str) -> None:
        self._arg = arg
        self._output = default_output(
            arg, prefix="gunzip_", suffix=".txt", use_path=False
        )

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "gzip -d <$in >$out"
        desc = "!gunzip $in"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        outputs = [str(self.output)]
        inputs = [self._arg]
        writer.build(outputs, self.RULE_NAME, inputs)


@register_rule("!xzunzip")
class XZUnzipNinja(NinjaRule):
    RULE_NAME = "xzunzip"

    def __init__(self, arg: str) -> None:
        self._arg = arg
        self._output = default_output(
            arg, prefix="xzunzip_", suffix=".txt", use_path=False
        )

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "xz -d <$in >$out"
        desc = "!xzunzip $in"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        outputs = [str(self.output)]
        inputs = [self._arg]
        writer.build(outputs, self.RULE_NAME, inputs)


@register_rule("!internal_copy")
class InternalCopyNinja(NinjaRule):
    RULE_NAME = "internal_copy"

    def __init__(self, src: Union[str, Path], dst: Union[str, Path]) -> None:
        self._src = str(Path(src).absolute())
        self._dst = str(Path(dst).absolute())
        self._output = Path(self._dst)

    @classmethod
    def write_rule(cls, writer: Writer) -> None:
        cmd = "cp $in $out"
        desc = "!copy $in $out"
        writer.rule(cls.RULE_NAME, cmd, description=desc)

    def write_build(self, writer: Writer) -> None:
        outputs = [self._dst]
        inputs = [self._src]
        writer.build(outputs, self.RULE_NAME, inputs)
