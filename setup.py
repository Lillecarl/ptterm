#!/usr/bin/env python
import os

from setuptools import find_packages, setup

with open(os.path.join(os.path.dirname(__file__), "README.rst")) as f:
    long_description = f.read()

requirements = [
    "prompt_toolkit>=3.0.52,<3.1.0",
    "pyte>=0.5.1",
    # The pty layer. It used to be `ptterm.process` and
    # `ptterm.backends`, and it left so that a second widget could use
    # it without taking prompt_toolkit on. Lillecarl/pymux#85.
    "ptyhost",
]


setup(
    name="ptterm",
    author="Jonathan Slenders",
    version="0.1",
    license="LICENSE",
    url="https://github.com/jonathanslenders/ptterm",
    description="Terminal emulator for prompt_toolkit.",
    long_description=long_description,
    packages=find_packages("."),
    install_requires=requirements,
    # pyte needs 3.10, so ptterm has needed 3.10 for a while. Nothing
    # said so.
    python_requires=">=3.10",
)
