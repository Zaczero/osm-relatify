{ pkgsnix ? import ./pkgs.nix
, pkgs ? pkgsnix.pkgs
, unstable ? pkgsnix.unstable
, isDocker ? false
}:

with pkgs; let
  commonBuildInputs = [
    stdenv.cc.cc.lib
    python311
  ];

  devBuildInputs = [
    gnumake
    pipenv
    esbuild
    unstable.ruff
  ];

  commonShellHook = ''
  '';

  devShellHook = ''
    export LD_LIBRARY_PATH="${lib.makeLibraryPath commonBuildInputs}"
    export PIPENV_VENV_IN_PROJECT=1
    export PIPENV_VERBOSITY=-1
    export PYTHONPATH="$(pwd)"
    [ ! -e .venv/bin/python ] && [ -h .venv/bin/python ] && rm -r .venv
    [ ! -f .venv/bin/activate ] && pipenv sync --dev
    case $- in *i*) exec pipenv shell --fancy;; esac
  '';

  dockerShellHook = ''
    make bundle
    make version
  '';
in
pkgs.mkShell {
  buildInputs = commonBuildInputs ++ (if isDocker then [ ] else devBuildInputs);
  shellHook = commonShellHook + (if isDocker then dockerShellHook else devShellHook);
}
