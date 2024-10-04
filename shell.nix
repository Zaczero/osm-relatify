{}:

let
  # Update packages with `nixpkgs-update` command
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/eeeb90a1dd3c9bea3afdbc76fd34d0fb2a727c7a.tar.gz") { };

  pythonLibs = with pkgs; [
    stdenv.cc.cc.lib
    zlib.out
  ];
  python' = with pkgs; (symlinkJoin {
    name = "python";
    paths = [ python312 ];
    buildInputs = [ makeWrapper ];
    postBuild = ''
      wrapProgram "$out/bin/python3.12" --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath pythonLibs}"
    '';
  });

  packages' = with pkgs; [
    python'
    uv
    ruff
    biome
    gcc14
    esbuild

    # Scripts
    # -- Cython
    (writeShellScriptBin "cython-build" "cd cython_lib && python setup.py build_ext --inplace")
    (writeShellScriptBin "cython-clean" "rm -rf cython_lib/build/ cython_lib/*{.c,.html,.so}")
    # -- Misc
    (writeShellScriptBin "run" ''
      python -m gunicorn main:app \
        --worker-class uvicorn.workers.UvicornWorker \
        --graceful-timeout 5 \
        --keep-alive 300 \
        --access-logfile -
    '')
    (writeShellScriptBin "make-bundle" ''
      # menu.js
      HASH=$(esbuild static/js/menu.js --bundle --minify | sha256sum | head -c8 ; echo "") && \
      esbuild static/js/menu.js --bundle --minify --sourcemap --charset=utf8 --outfile=static/js/menu.$HASH.js && \
      find templates -type f -exec sed -r 's|src="/static/js/menu\..*?js" type="module"|src="/static/js/menu.'$HASH'.js"|g' -i {} \;

      # style.css
      HASH=$(esbuild static/css/style.css --bundle --minify | sha256sum | head -c8 ; echo "") && \
      esbuild static/css/style.css --bundle --minify --sourcemap --charset=utf8 --outfile=static/css/style.$HASH.css && \
      find templates -type f -exec sed -r 's|href="/static/css/style\..*?css"|href="/static/css/style.'$HASH'.css"|g' -i {} \;
    '')
    (writeShellScriptBin "nixpkgs-update" ''
      set -e
      hash=$(
        curl --silent --location \
        https://prometheus.nixos.org/api/v1/query \
        -d "query=channel_revision{channel=\"nixpkgs-unstable\"}" | \
        grep --only-matching --extended-regexp "[0-9a-f]{40}")
      sed -i -E "s|/nixpkgs/archive/[0-9a-f]{40}\.tar\.gz|/nixpkgs/archive/$hash.tar.gz|" shell.nix
      echo "Nixpkgs updated to $hash"
    '')
  ];

  shell' = ''
    export PYTHONNOUSERSITE=1
    export TZ=UTC

    current_python=$(readlink -e .venv/bin/python || echo "")
    current_python=''${current_python%/bin/*}
    [ "$current_python" != "${python'}" ] && rm -rf .venv/

    echo "Installing Python dependencies"
    export UV_COMPILE_BYTECODE=1
    export UV_PYTHON="${python'}/bin/python"
    uv sync --frozen

    echo "Activating Python virtual environment"
    source .venv/bin/activate

    # Development environment variables
    export TEST_ENV=1

    if [ -f .env ]; then
      echo "Loading .env file"
      set -o allexport
      source .env set
      set +o allexport
    else
      echo "Skipped loading .env file (not found)"
    fi
  '';
in
pkgs.mkShellNoCC {
  buildInputs = packages';
  shellHook = shell';
}
