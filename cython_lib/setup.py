from pathlib import Path

import Cython.Compiler.Options as Options
from Cython.Build import cythonize
from setuptools import Extension, setup

Options.docstrings = False
Options.annotate = True

paths = (
    Path('geoutils.py'),
    Path('route.py'),
)

setup(
    ext_modules=cythonize(
        [
            Extension(
                path.with_suffix('').as_posix().replace('/', '.'),
                [str(path)],
                extra_compile_args=[
                    '-march=native',
                    '-mtune=native',
                    '-ffast-math',
                    # https://stackoverflow.com/a/23501290
                    '--param=max-vartrack-size=0',
                ],
            )
            for path in paths
        ],
        compiler_directives={
            # https://cython.readthedocs.io/en/latest/src/userguide/source_files_and_compilation.html#compiler-directives
            'language_level': 3,
        },
    ),
)
