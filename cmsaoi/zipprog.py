import sys
import zipfile
from pathlib import Path


def main():
    target = sys.argv[1]
    sources = sys.argv[2:]

    with zipfile.ZipFile(target, "w") as zipf:
        for s in sources:
            zipname, path = s.split("=")
            zipf.writestr(zipname, Path(path).read_bytes())


if __name__ == "__main__":
    main()
