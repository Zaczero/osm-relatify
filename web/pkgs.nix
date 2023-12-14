{
  # check latest hashes at https://status.nixos.org/
  pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/a46b965ea7d1b9587a46f91adfdbac29e56c9b87.tar.gz") { };
  unstable = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/e97b3e4186bcadf0ef1b6be22b8558eab1cdeb5d.tar.gz") { };
}
