{
  description = "Ojuny installer - Calamares live ISO and unattended installer ISO";

  inputs = {
    nixpkgs.follows = "ojuny-template/nixpkgs";

    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };

    ojuny-template = {
      url = "github:ojuny-project/ojuny-template";
    };

    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Local working copy of the cache daemon for the discovery ISO variant.
    # Switch to github:SDG-Den/nix-cache-discovery before publishing.
    nix-cache-discovery = {
      url = "github:SDG-Den/nix-cache-discovery";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    settings.url = "path:./unattended/default";
  };

  outputs =
    inputs@{
      self,
      flake-parts,
      nixpkgs,
      ...
    }:
    let
      system = "x86_64-linux";
      lib = nixpkgs.lib;

      settings = (import ./unattended/default-settings.nix) // (inputs.settings.settings or { });

      iso = nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs; };
        modules = [ ./nixos/iso.nix ];
      };

      discoveryIso = nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs; };
        modules = [ ./nixos/discovery-iso.nix ];
      };

      unattended = lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs settings; };
        modules = [ ./nixos/unattended.nix ];
      };

      fullTarget = lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs; };
        modules = [
          ./nixos/full-system.nix
          ./nixos/full-hardware.nix
          ./nixos/target-bootloader.nix
        ];
      };

      fullTargetLatest = lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs; };
        modules = [
          ./nixos/full-system.nix
          ./nixos/full-hardware.nix
          ./nixos/target-bootloader.nix
          ({ lib, pkgs, ... }: {
            boot.kernelPackages = lib.mkForce pkgs.linuxPackages_latest;
          })
        ];
      };

      fullIso = lib.nixosSystem {
        inherit system;
        specialArgs = {
          inherit inputs;
          target = fullTarget;
          targetLatest = fullTargetLatest;
        };
        modules = [ ./nixos/full-iso.nix ];
      };

      fullUnattended = lib.nixosSystem {
        inherit system;
        specialArgs = {
          inherit inputs settings;
          target = fullTarget;
          targetLatest = fullTargetLatest;
        };
        modules = [ ./nixos/full-unattended.nix ];
      };
    in
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [ system ];

      perSystem =
        { pkgs, system, ... }:
        let
          ojuny-calamares-extensions = pkgs.callPackage ./packages/ojuny-calamares-extensions {
            templatePath = inputs.ojuny-template.outPath;
            prepareRepo = (inputs.ojuny-template.packages.${system} or { }).prepare-repo or null;
            regenerateHardware = (inputs.ojuny-template.packages.${system} or { }).regenerate-hardware or null;
            mkpasswd = pkgs.mkpasswd;
          };

          calamares = pkgs.calamares.overrideAttrs (previous: {
            patches =
              lib.filter (patch: !(lib.hasInfix "dont-allow-manual-luks" (toString patch))) (
                previous.patches or [ ]
              )
              ++ [ ./packages/calamares-compact-locale.patch ];
          });

          calamares-ojuny = pkgs.callPackage ./packages/calamares-ojuny.nix {
            inherit calamares;
            extensions = ojuny-calamares-extensions;
          };
        in
        {
          formatter = pkgs.nixfmt;

          packages = {
            inherit ojuny-calamares-extensions calamares-ojuny;

            ojuny-iso = iso.config.system.build.isoImage;
            ojuny-iso-discovery = discoveryIso.config.system.build.isoImage;
            unattended-iso = unattended.config.system.build.isoImage;
            ojuny-iso-offline = fullIso.config.system.build.isoImage;
            unattended-iso-offline = fullUnattended.config.system.build.isoImage;
          };

          devShells.default = pkgs.mkShell {
            packages = with pkgs; [
              cpio
              deadnix
              file
              git
              gzip
              jq
              mkpasswd
              nix
              nixd
              nixfmt
              OVMF
              python3
              python3Packages.pyyaml
              qemu
              shellcheck
              shfmt
              squashfsTools
              statix
              xorriso
              xz
              yq-go
              zstd
            ];
          };

          checks = {
            format = pkgs.runCommand "check-format" { nativeBuildInputs = [ pkgs.nixfmt ]; } ''
              cd ${./.}
              nixfmt --check flake.nix $(find packages nixos unattended -name '*.nix')
              touch $out
            '';

            extensions =
              pkgs.runCommand "check-ojuny-calamares-extensions" { nativeBuildInputs = [ pkgs.yq-go ]; }
                ''
                  yq -e '.branding == "ojuny"' ${ojuny-calamares-extensions}/etc/calamares/settings.conf
                  yq -e '.componentName == "ojuny"' ${ojuny-calamares-extensions}/share/calamares/branding/ojuny/branding.desc
                  yq -e '.slideshow == "show.qml"' ${ojuny-calamares-extensions}/share/calamares/branding/ojuny/branding.desc
                  test -f ${ojuny-calamares-extensions}/share/calamares/branding/ojuny/show.qml
                  test -f ${ojuny-calamares-extensions}/share/calamares/branding/ojuny/ojuny-logo.png
                  test -f ${ojuny-calamares-extensions}/share/calamares/branding/ojuny/ojuny-brand-large.png
                  test -f ${ojuny-calamares-extensions}/share/calamares/branding/ojuny/stylesheet.qss
                  grep -q 'notesqml@template' ${ojuny-calamares-extensions}/etc/calamares/settings.conf
                  grep -q 'notesqml@origin' ${ojuny-calamares-extensions}/etc/calamares/settings.conf
                  test -f ${ojuny-calamares-extensions}/share/calamares/branding/ojuny/template.qml
                  test -f ${ojuny-calamares-extensions}/share/calamares/branding/ojuny/origin.qml
                  yq -e '.requirements.requiredStorage == 30' ${ojuny-calamares-extensions}/etc/calamares/modules/welcome.conf
                  yq -e '.requirements.required | contains(["storage"]) | not' ${ojuny-calamares-extensions}/etc/calamares/modules/welcome.conf
                  yq -e '.mkpasswd | length > 0' ${ojuny-calamares-extensions}/etc/calamares/modules/ojuny.conf
                  prepare_repo_path="$(yq -r '.prepareRepo' ${ojuny-calamares-extensions}/etc/calamares/modules/ojuny.conf)"
                  if [ -n "$prepare_repo_path" ]; then
                    case "$prepare_repo_path" in
                      */bin/prepare-repo) ;;
                      *) echo "prepareRepo is not an executable path: $prepare_repo_path"; exit 1 ;;
                    esac
                  fi
                  regenerate_path="$(yq -r '.regenerateHardware' ${ojuny-calamares-extensions}/etc/calamares/modules/ojuny.conf)"
                  if [ -n "$regenerate_path" ]; then
                    case "$regenerate_path" in
                      */bin/regenerate-hardware) ;;
                      *) echo "regenerateHardware is not an executable path: $regenerate_path"; exit 1 ;;
                    esac
                  fi
                  yq -e '.name == "ojuny" and .interface == "python"' ${ojuny-calamares-extensions}/lib/calamares/modules/ojuny/module.desc
                  test -f ${ojuny-calamares-extensions}/etc/calamares/modules/ojuny.conf
                  touch $out
                '';

            module = pkgs.runCommand "check-ojuny-calamares-module" { nativeBuildInputs = [ pkgs.python3 ]; } ''
              python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' \
                ${./packages/ojuny-calamares-extensions/modules/ojuny/main.py}
              touch $out
            '';

            unattended =
              pkgs.runCommand "check-ojuny-unattended"
                {
                  nativeBuildInputs = [
                    pkgs.python3
                    pkgs.shellcheck
                  ];
                }
                ''
                  python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' \
                    ${./nixos/unattended-install.py}
                  shellcheck -S warning ${./scripts/make-unattended-iso.sh}
                  touch $out
                '';

            offline-iso-size =
              pkgs.runCommand "check-offline-iso-size"
                {
                  nativeBuildInputs = [ pkgs.coreutils ];
                }
                ''
                  size=$(stat -c %s ${fullIso.config.system.build.isoImage}/iso/*.iso)
                  echo "offline attended ISO: $size bytes"
                  test "$size" -le 8000000000 || { echo "offline attended ISO exceeds 8 GB"; exit 1; }
                  test "$size" -le 7400000000 || echo "warning: offline attended ISO exceeds 7.4 GB"
                  touch $out
                '';

            offline-unattended-iso-size =
              pkgs.runCommand "check-offline-unattended-iso-size"
                {
                  nativeBuildInputs = [ pkgs.coreutils ];
                }
                ''
                  size=$(stat -c %s ${fullUnattended.config.system.build.isoImage}/iso/*.iso)
                  echo "offline unattended ISO: $size bytes"
                  test "$size" -le 8000000000 || { echo "offline unattended ISO exceeds 8 GB"; exit 1; }
                  test "$size" -le 7400000000 || echo "warning: offline unattended ISO exceeds 7.4 GB"
                  touch $out
                '';
          };
        };

      flake.nixosConfigurations.ojuny-iso = iso;
      flake.nixosConfigurations.ojuny-iso-discovery = discoveryIso;
      flake.nixosConfigurations.ojuny-unattended = unattended;
      flake.nixosConfigurations.ojuny-iso-offline = fullIso;
      flake.nixosConfigurations.ojuny-unattended-offline = fullUnattended;
    };
}
