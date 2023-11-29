{
  # check latest hashes at https://status.nixos.org/
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/e922e146779e250fae512da343cfb798c758509d.tar.gz") { };
  unstable = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/010c7296f3b19a58b206fdf7d68d75a5b0a09e9e.tar.gz") { };
}
