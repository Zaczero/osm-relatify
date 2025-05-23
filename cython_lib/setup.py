import os
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

extra_args: list[str] = [
    '-pipe',
    '-g',
    '-Ofast',
    # docs: https://gcc.gnu.org/onlinedocs/gcc-14.1.0/gcc.pdf
    '-march=' + os.getenv('CYTHON_MARCH', 'native'),
    '-mtune=' + os.getenv('CYTHON_MTUNE', 'native'),
    '-fno-semantic-interposition',
    '-fipa-pta',
    '-fvisibility=hidden',
    '-flto=auto',
    '-fno-plt',
    *os.getenv('CYTHON_FLAGS', '').split(),
]

setup(
    ext_modules=cythonize(
        [
            Extension(
                path.with_suffix('').as_posix().replace('/', '.'),
                [str(path)],
                extra_compile_args=extra_args,
                extra_link_args=extra_args,
                define_macros=[
                    ('CYTHON_PROFILE', '1'),
                ],
            )
            for path in paths
        ],
        compiler_directives={
            # https://cython.readthedocs.io/en/latest/src/userguide/source_files_and_compilation.html#compiler-directives
            'profile': True,
            'language_level': 3,
        },
    ),
)
