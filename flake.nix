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

    nom-cache-discovery.follows = "ojuny-template/nom-cache-discovery";

    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    impermanence = {
      url = "github:nix-community/impermanence";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Local working copy of the cache daemon for the discovery ISO variant.
    # nix-cache-discovery is consumed from ojuny-project.
    nix-cache-discovery = {
      url = "github:ojuny-project/nix-cache-discovery";
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

      discoveryUnattended = lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs settings; };
        modules = [ ./nixos/discovery-unattended.nix ];
      };

      persistent = lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs; };
        modules = [ ./nixos/persistent.nix ];
      };

      fullTarget = lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs; };
        modules = [ inputs.ojuny-template.modules.nixos.host-imports ];
      };

      fullTargetLatest = lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs; };
        modules = [
          inputs.ojuny-template.modules.nixos.host-imports
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
            bootorder = (inputs.ojuny-template.packages.${system} or { }).ojuny-bootorder or null;
            mkpasswd = pkgs.mkpasswd;
          };

          pkgsWithKpmcore = pkgs.extend (
            final: prev: {
              kdePackages = prev.kdePackages.overrideScope (
                kfinal: kprev: {
                  kpmcore = kprev.kpmcore.overrideAttrs (old: {
                    patches = (old.patches or [ ]) ++ [ ./packages/kpmcore-luks2-sector-size.patch ];
                  });
                }
              );
            }
          );

          calamares = pkgsWithKpmcore.calamares.overrideAttrs (previous: {
            patches =
              lib.filter (patch: !(lib.hasInfix "dont-allow-manual-luks" (toString patch))) (
                previous.patches or [ ]
              )
              ++ [
                ./packages/calamares-compact-locale.patch
                ./packages/calamares-partition-note.patch
                ./packages/calamares-ojuny-esp.patch
              ];
          });

          calamares-ojuny = pkgs.callPackage ./packages/calamares-ojuny.nix {
            inherit calamares;
            extensions = ojuny-calamares-extensions;
          };

          install-report = pkgs.python3Packages.buildPythonApplication {
            pname = "ojuny-install-report";
            version = "0.1.0";
            pyproject = true;
            src = ./packages/install-report;
            build-system = [ pkgs.python3Packages.setuptools ];
            preCheck = ''
              export PYTHONPATH="$PWD/src"
            '';
            checkPhase = ''
              python -m unittest discover -s tests -v
            '';
          };
        in
        {
          formatter = pkgs.nixfmt;

          packages = {
            inherit ojuny-calamares-extensions calamares-ojuny install-report;

            ojuny-iso = iso.config.system.build.isoImage;
            ojuny-iso-discovery = discoveryIso.config.system.build.isoImage;
            unattended-iso = unattended.config.system.build.isoImage;
            unattended-iso-discovery = discoveryUnattended.config.system.build.isoImage;
            ojuny-iso-offline = fullIso.config.system.build.isoImage;
            unattended-iso-offline = fullUnattended.config.system.build.isoImage;
            ojuny-image-persistent = persistent.config.system.build.diskoImagesScript;
          };

          apps.make-unattended-iso = {
            type = "app";
            program = "${
              pkgs.writeShellApplication {
                name = "make-unattended-iso";
                runtimeInputs = [
                  pkgs.coreutils
                  pkgs.git
                  pkgs.mkpasswd
                  pkgs.nix
                  pkgs.python3
                ];
                text = ''
                  export OJUNY_INSTALLER_SOURCE="${self}"
                  ${builtins.readFile ./scripts/make-unattended-iso.sh}
                '';
              }
            }/bin/make-unattended-iso";
          };

          apps.make-persistent-image = {
            type = "app";
            program = "${
              pkgs.writeShellApplication {
                name = "make-persistent-image";
                runtimeInputs = [
                  pkgs.coreutils
                  pkgs.nix
                  pkgs.qemu
                ];
                text = ''
                  export OJUNY_DISKO_IMAGE_SCRIPT="${persistent.config.system.build.diskoImagesScript}"
                  ${builtins.readFile ./scripts/make-persistent-image.sh}
                '';
              }
            }/bin/make-persistent-image";
          };

          apps.ci = {
            type = "app";
            program = "${
              pkgs.writeShellApplication {
                name = "ci";
                runtimeInputs = [ pkgs.nix ];
                text = ''
                  exec nix flake check "$@"
                '';
              }
            }/bin/ci";
          };

          apps.install-report = {
            type = "app";
            program = "${install-report}/bin/install-report";
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
            inherit install-report;

            collect-install-report =
              pkgs.runCommand "check-collect-install-report"
                {
                  nativeBuildInputs = [ pkgs.python3 ];
                }
                ''
                  cd ${./.}
                  python3 -m unittest scripts.tests.test_collect_install_report -v
                  touch $out
                '';

            ojuny-progress =
              pkgs.runCommand "check-ojuny-progress"
                {
                  nativeBuildInputs = [ pkgs.python3 ];
                }
                ''
                  cd ${./.}
                  python3 -m unittest discover -s packages/ojuny-calamares-extensions/tests -v
                  touch $out
                '';

            flake-structure =
              pkgs.runCommand "check-flake-structure"
                {
                  nativeBuildInputs = [ pkgs.python3 ];
                }
                ''
                  cd ${./.}
                  cmp packages/ojuny-calamares-extensions/modules/ojuny/flake_structure.py nixos/flake_structure.py
                  python3 tests/check-fixed-paths.py
                  touch $out
                '';

            debug = pkgs.runCommand "check-debug-iso" { } ''
              grep -q './debug.nix' ${./nixos/iso.nix}
              grep -q './debug.nix' ${./nixos/discovery-iso.nix}
              grep -q './debug.nix' ${./nixos/full-iso.nix}
              touch $out
            '';

            default = pkgs.runCommand "check-default" { } ''
              echo ${self.checks.${system}.format} >/dev/null
              echo ${self.checks.${system}.extensions} >/dev/null
              echo ${self.checks.${system}.module} >/dev/null
              echo ${self.checks.${system}.unattended} >/dev/null
              echo ${self.checks.${system}.offline-install-closure} >/dev/null
              echo ${self.checks.${system}.install-report} >/dev/null
              echo ${self.checks.${system}.ojuny-progress} >/dev/null
              echo ${self.checks.${system}.flake-structure} >/dev/null
              echo ${self.checks.${system}.debug} >/dev/null
              touch $out
            '';

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
                  test -f ${./packages/calamares-partition-note.patch}
                  test -f ${./packages/calamares-ojuny-esp.patch}
                  grep -q 'rootFirstSector' ${./packages/calamares-ojuny-esp.patch}
                  grep -q 'KPM_PARTITION_FLAG_ESP' ${./packages/calamares-ojuny-esp.patch}
                  grep -q 'src/modules/partition/core/PartitionActions.cpp' ${./packages/calamares-ojuny-esp.patch}
                  grep -q 'espParent' ${./packages/calamares-ojuny-esp.patch}
                  grep -q 'createSwapPartition' ${./packages/calamares-ojuny-esp.patch}
                  grep -q 'm_alongsideSwapChoiceComboBox' ${./packages/calamares-ojuny-esp.patch}
                  test -f ${./packages/kpmcore-luks2-sector-size.patch}
                  grep -q 'BLKSSZGET' ${./packages/kpmcore-luks2-sector-size.patch}
                  yq -e '.requirements.requiredStorage == 30' ${ojuny-calamares-extensions}/etc/calamares/modules/welcome.conf
                  yq -e '.requirements.required | contains(["storage"]) | not' ${ojuny-calamares-extensions}/etc/calamares/modules/welcome.conf
                  yq -e '.efi.recommendedSize == "4GiB"' ${ojuny-calamares-extensions}/etc/calamares/modules/partition.conf
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
                  bootorder_path="$(yq -r '.bootorder' ${ojuny-calamares-extensions}/etc/calamares/modules/ojuny.conf)"
                  if [ -n "$bootorder_path" ]; then
                    case "$bootorder_path" in
                      */bin/ojuny-bootorder) ;;
                      *) echo "bootorder is not an executable path: $bootorder_path"; exit 1 ;;
                    esac
                  fi
                  yq -e '.name == "ojuny" and .interface == "python"' ${ojuny-calamares-extensions}/lib/calamares/modules/ojuny/module.desc
                  test -f ${ojuny-calamares-extensions}/etc/calamares/modules/ojuny.conf
                  touch $out
                '';

            module = pkgs.runCommand "check-ojuny-calamares-module" { nativeBuildInputs = [ pkgs.python3 ]; } ''
              python3 -c 'import ast, sys; [ast.parse(open(path).read()) for path in sys.argv[1:]]' \
                ${./packages/ojuny-calamares-extensions/modules/ojuny/main.py} \
                ${./packages/ojuny-calamares-extensions/modules/ojuny/install_progress.py}
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
                  shellcheck -S warning \
                    ${./scripts/make-unattended-iso.sh} \
                    ${./scripts/check-offline-install-closure.sh} \
                    ${./scripts/check-offline-install-vm.sh}
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

            offline-install-closure =
              pkgs.runCommand "check-offline-install-closure"
                {
                  nativeBuildInputs = [
                    pkgs.git
                    pkgs.nix
                    pkgs.python3
                  ];
                  TEMPLATE = "${inputs.ojuny-template}";
                  PREPARE_REPO = "${inputs.ojuny-template.packages.${system}.prepare-repo}";
                  FLAKE_INPUTS = fullIso.config.environment.etc."ojuny/flake-inputs".text;
                  FLAKE_INPUT_PATHS = fullIso.config.environment.etc."ojuny/flake-input-paths".text;
                  EVAL_CLOSURE = "${pkgs.closureInfo {
                    rootPaths = [
                      fullTarget.pkgs.stdenv
                      fullTarget.pkgs.base16-schemes
                    ];
                  }}";
                }
                ''
                  export HOME=$TMPDIR
                  bash ${./scripts/check-offline-install-closure.sh}
                  touch $out
                '';
          };
        };

      flake = {
        hydraJobs = self.checks;
      };

      flake.nixosConfigurations.ojuny-iso = iso;
      flake.nixosConfigurations.ojuny-iso-discovery = discoveryIso;
      flake.nixosConfigurations.ojuny-unattended = unattended;
      flake.nixosConfigurations.ojuny-unattended-discovery = discoveryUnattended;
      flake.nixosConfigurations.ojuny-iso-offline = fullIso;
      flake.nixosConfigurations.ojuny-image-persistent = persistent;
      flake.nixosConfigurations.ojuny-unattended-offline = fullUnattended;
    };
}
