{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    gnumake
    gnused
    python311
    pipenv
    esbuild
  ];

  shellHook = with pkgs; ''
    export LD_LIBRARY_PATH="${stdenv.cc.cc.lib}/lib:$LD_LIBRARY_PATH"
    export PIPENV_VENV_IN_PROJECT=1
    export PIPENV_VERBOSITY=-1
    [ -v DOCKER ] && [ ! -f .venv/bin/activate ] && pipenv sync
    [ ! -v DOCKER ] && [ ! -f .venv/bin/activate ] && pipenv sync --dev
    [ ! -v DOCKER ] && exec pipenv shell --fancy
  '';
}
