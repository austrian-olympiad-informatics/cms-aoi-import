import sys
import zipfile
from pathlib import Path


def add_source(zf: zipfile.ZipFile, zipname: str, path: str):
    p = Path(path)
    if p.is_dir():
        for c in p.iterdir():
            czn = Path(zipname) / c.name
            add_source(zf, str(czn), str(c))
        return
    zf.writestr(zipname, p.read_bytes())


def main():
    target = sys.argv[1]
    sources = sys.argv[2:]

    with zipfile.ZipFile(target, "w") as zipf:
        for s in sources:
            zipname, path = s.split("=")
            add_source(zipf, zipname, path)


if __name__ == "__main__":
    main()
