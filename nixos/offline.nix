{
  inputs,
  lib,
  ...
}:

let
  template = inputs.ojuny-template;
  lock = builtins.fromJSON (builtins.readFile (template.outPath + "/flake.lock"));

  lockedInputs = builtins.filter (node: node ? locked && node.locked ? narHash) (
    builtins.attrValues lock.nodes
  );

  fetchLocked =
    locked:
    if locked ? dir then
      builtins.path {
        path = "${
          builtins.fetchTree (
            removeAttrs locked [
              "dir"
              "narHash"
            ]
          )
        }/${locked.dir}";
        name = "source";
      }
    else
      builtins.fetchTree locked;

  flakeInputs = [ template.outPath ] ++ map (node: fetchLocked node.locked) lockedInputs;
in
{
  nix.settings.substituters = lib.mkForce [ ];
  nix.settings.extra-substituters = lib.mkForce [ ];
  nix.settings.trusted-substituters = lib.mkForce [ ];
  nix.settings.flake-registry = lib.mkForce "";

  environment.etc."ojuny/offline".text = "";

  environment.etc."ojuny/flake-inputs".text = lib.concatMapStrings (path: path + "\n") flakeInputs;

  isoImage.storeContents = lib.mkAfter flakeInputs;

  isoImage.compressImage = false;
  isoImage.squashfsCompression = "zstd -Xcompression-level 19";
}
