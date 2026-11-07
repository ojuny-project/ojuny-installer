{
  pkgs,
  template,
}:

let
  mkSession =
    name:
    pkgs.testers.nixosTest {
      name = "acceptance-session-${name}";
      nodes.machine =
        { ... }:
        {
          imports = [ template.modules.nixos.host-imports ];
          virtualisation.graphics = true;
          virtualisation.qemu.options = [ "-device" "virtio-vga-gl" ];
          environment.systemPackages = [ pkgs.tesseract ];
        };
      enableOCR = true;
      testScript = ''
        machine.wait_for_unit("display-manager.service")
        machine.wait_for_text("Ojuny")
        machine.screenshot("session")
      '';
    };
in
{
  session = mkSession "default";
  stability = map (index: mkSession (toString index)) (builtins.range 1 5);
}
