from pathlib import Path


class CoreInfo:
    def __init__(self):
        # Will be set later in main()
        self.task_dir: Path = Path.cwd()
        self.config = {}

    @property
    def internal_dir(self) -> Path:
        return self.task_dir / ".aoi-temp"

    @property
    def internal_build_dir(self):
        return self.internal_dir / "build"

    @property
    def result_dir(self):
        return self.internal_dir / "result"


# Object to store some global data
core = CoreInfo()


class CMSAOIError(Exception):
    """CMSAOIError is for exceptions that should halt execution without generating a stacktrace (managed errors)."""

    pass
