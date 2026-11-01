{
  inputs,
  lib,
  ...
}:

let
  template = inputs.ojuny-template;
  templateFlake = builtins.getFlake (builtins.unsafeDiscardStringContext (toString template.outPath));

  flakeInputs = [
    template.outPath
  ]
  ++ map (node: node.input.outPath) (
    builtins.genericClosure {
      startSet = [
        {
          key = templateFlake.outPath;
          input = templateFlake;
        }
      ];
      operator =
        node:
        map (input: {
          key = input.outPath;
          inherit input;
        }) (builtins.attrValues (node.input.inputs or { }));
    }
  );
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
