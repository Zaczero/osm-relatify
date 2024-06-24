import Cython.Compiler.Options as Options
from Cython.Build import cythonize
from setuptools import Extension, setup

Options.docstrings = False
Options.annotate = True

setup(
    ext_modules=cythonize(
        [
            Extension(
                '*',
                ['cython_lib/*.py'],
                extra_compile_args=[
                    '-march=x86-64-v3',
                    '-mtune=generic',
                    '-ffast-math',
                ],
            ),
        ],
        compiler_directives={
            # https://cython.readthedocs.io/en/latest/src/userguide/source_files_and_compilation.html#compiler-directives
            'language_level': 3,
        },
    ),
)
