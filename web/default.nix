{ pkgs ? import <nixpkgs> { }, ... }:

let
  shell = import ./shell.nix { isDevelopment = false; };

  python-venv = pkgs.buildEnv {
    name = "python-venv";
    paths = [
      (pkgs.runCommand "python-venv" { } ''
        set -e
        mkdir -p $out/bin $out/lib
        find "${./.venv/bin}" -type f -executable -exec cp {} $out/bin \;
        sed -i '1s|^#!.*/python|#!/usr/bin/env python|' $out/bin/*
        cp -r "${./.venv/lib/python3.12/site-packages}"/* $out/lib
      '')
    ];
    pathsToLink = [ "/bin" "/lib" ];
  };

  entrypoint = pkgs.writeShellScriptBin "entrypoint" ''
    exec python -m gunicorn main:app \
      --bind 0.0.0.0:8000 \
      --worker-class uvicorn.workers.UvicornWorker \
      --graceful-timeout 5 \
      --keep-alive 300 \
      --access-logfile - \
      --forwarded-allow-ips '*'
  '';
in
with pkgs; dockerTools.buildLayeredImage {
  name = "docker.monicz.dev/osm-relatify";
  tag = "latest";

  contents = shell.buildInputs ++ [
    dockerTools.usrBinEnv
    python-venv
  ];

  extraCommands = ''
    set -e
    mkdir app && cd app
    cp "${./.}"/*.py .
    cp -r "${./.}"/cython_lib .
    cp -r "${./.}"/models .
    cp -r "${./.}"/static .
    cp -r "${./.}"/templates .
    export PATH="${lib.makeBinPath shell.buildInputs}:$PATH"
    ${shell.shellHook}
  '';

  config = {
    WorkingDir = "/app";
    Env = [
      "PYTHONPATH=${python-venv}/lib"
      "PYTHONUNBUFFERED=1"
      "PYTHONDONTWRITEBYTECODE=1"
      "TZ=UTC"
    ];
    ExposedPorts = {
      "8000/tcp" = { };
    };
    Entrypoint = [ "${entrypoint}/bin/entrypoint" ];
  };
}
