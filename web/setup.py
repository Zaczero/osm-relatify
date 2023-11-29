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
                    '-march=znver3',  # ryzen 5000 or newer
                    '-ffast-math',
                    '-fopenmp',
                    '-flto=auto',
                ],
                extra_link_args=[
                    '-fopenmp',
                    '-flto=auto',
                ],
            ),
        ],
        compiler_directives={
            # https://cython.readthedocs.io/en/latest/src/userguide/source_files_and_compilation.html#compiler-directives
            'language_level': 3,
        },
    ),
)
