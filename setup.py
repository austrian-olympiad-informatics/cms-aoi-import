#!/usr/bin/env python3
"""aioesphomeapi setup script."""
import os

from setuptools import find_packages, setup

here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(here, "README.md"), encoding="utf-8") as readme_file:
    long_description = readme_file.read()

VERSION = "1.0.0"
PROJECT_NAME = "cmsaoi"

with open(os.path.join(here, "requirements.txt")) as requirements_txt:
    REQUIRES = requirements_txt.read().splitlines()

setup(
    name=PROJECT_NAME,
    version=VERSION,
    packages=find_packages(exclude=["tests", "tests.*"]),
    include_package_data=True,
    zip_safe=False,
    install_requires=REQUIRES,
    python_requires=">=3.7",
    entry_points={
        "console_scripts": [
            "cmsAOI=cmsaoi.__main__:main",
            "_cmsAOIzip=cmsaoi.zipprog:main",
        ]
    }
)
