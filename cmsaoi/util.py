import hashlib
import re
import shutil
from pathlib import Path
from typing import Dict, Optional, Set, Union


def stable_hash(s: Union[str, bytes]):
    sha = hashlib.md5()
    if isinstance(s, str):
        s = s.encode()
    sha.update(s)
    return sha.hexdigest()[:8]


def _is_copy_necessary(src: Path, dst: Path):
    if not src.is_file():
        raise ValueError(f"File {src} does not exist and cannot be copied.")
    if not dst.is_file():
        return True
    return src.stat().st_mtime >= dst.stat().st_mtime


def write_if_changed(content: str, dst: Path):
    if dst.is_file() and dst.read_text() == content:
        return
    dst.write_text(content)


def copy_if_necessary(src: Path, dst: Path):
    if not _is_copy_necessary(src, dst):
        return
    dst.parent.mkdir(exist_ok=True)
    shutil.copy2(src, dst)


def copytree(src: Path, dst: Path, ignore: Optional[Set[Path]] = None):
    ignore = ignore or set()
    dst.mkdir(exist_ok=True)
    for src_path in src.iterdir():
        dst_path = dst / src_path.name
        if src_path in ignore:
            continue
        if src_path.is_dir():
            copytree(src_path, dst_path, ignore=ignore)
        else:
            copy_if_necessary(src_path, dst_path)
    shutil.copystat(src, dst)
    return dst


expand_vars_prog = re.compile(r"\$(\w+|\{[^}]*\})", re.ASCII)


def expand_vars(s: str, env: Dict[str, str]) -> str:
    i = 0
    while True:
        m = expand_vars_prog.search(s, i)
        if not m:
            break
        i, j = m.span(0)
        name = m.group(1)
        if name.startswith("{") and name.endswith("}"):
            name = name[1:-1]

        try:
            value = env[name]
        except KeyError:
            i = j
        else:
            tail = s[j:]
            s = s[:i] + value
            i = len(s)
            s += tail
    return s
