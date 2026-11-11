{ inputs, ... }:

{
  imports = [
    inputs.ojuny-template.inputs.ojuny-welcome.nixosModules.default
    inputs.ojuny-template.modules.nixos.system-configuration
    inputs.ojuny-template.modules.nixos.system-facter
    inputs.ojuny-template.modules.nixos.system-hardware-profile
    inputs.ojuny-template.modules.nixos.system-networking
    inputs.ojuny-template.modules.nixos.system-bluetooth
    inputs.ojuny-template.modules.nixos.system-graphics
    inputs.ojuny-template.modules.nixos.system-plymouth
    inputs.ojuny-template.modules.nixos.system-power
    inputs.ojuny-template.modules.nixos.system-lock
    inputs.ojuny-template.modules.nixos.system-accessibility
    inputs.ojuny-template.modules.nixos.system-nixsettings
    inputs.ojuny-template.modules.nixos.system-updates
    inputs.ojuny-template.modules.nixos.system-first-boot

    inputs.ojuny-template.modules.nixos.users-commonsettings
    inputs.ojuny-template.modules.nixos.users

    inputs.ojuny-template.modules.nixos.desktop-mango
    inputs.ojuny-template.modules.nixos.desktop-mangosettings
    inputs.ojuny-template.modules.nixos.desktop-mangomaster
    inputs.ojuny-template.modules.nixos.desktop-mangodwindle
    inputs.ojuny-template.modules.nixos.desktop-mangoworkspaces
    inputs.ojuny-template.modules.nixos.desktop-monocledeck
    inputs.ojuny-template.modules.nixos.desktop-scroller
    inputs.ojuny-template.modules.nixos.desktop-display
    inputs.ojuny-template.modules.nixos.desktop-style-theme
    inputs.ojuny-template.modules.nixos.desktop-style-typography
    inputs.ojuny-template.modules.nixos.desktop-style-compositor
    inputs.ojuny-template.modules.nixos.desktop-style-shell
    inputs.ojuny-template.modules.nixos.desktop-bar
    inputs.ojuny-template.modules.nixos.desktop-dock
    inputs.ojuny-template.modules.nixos.desktop-dashboard
    inputs.ojuny-template.modules.nixos.desktop-notifications
    inputs.ojuny-template.modules.nixos.desktop-screensaver
    inputs.ojuny-template.modules.nixos.desktop-nightlight
    inputs.ojuny-template.modules.nixos.desktop-audio
    inputs.ojuny-template.modules.nixos.desktop-clipboard
    inputs.ojuny-template.modules.nixos.desktop-menu
    inputs.ojuny-template.modules.nixos.desktop-plugins

    inputs.ojuny-template.modules.nixos.desktop-binds
    inputs.ojuny-template.modules.nixos.desktop-autostart
    inputs.ojuny-template.modules.nixos.desktop-input
    inputs.ojuny-template.modules.nixos.desktop-login
    inputs.ojuny-template.modules.nixos.desktop-controlcenter
    inputs.ojuny-template.modules.nixos.desktop-gestures
    inputs.ojuny-template.modules.nixos.desktop-launcher

    inputs.ojuny-template.modules.nixos.applications-applist
    inputs.ojuny-template.modules.nixos.desktop-dux-tools
    inputs.ojuny-template.modules.nixos.applications-screenshot
    inputs.ojuny-template.modules.nixos.applications-browser
    inputs.ojuny-template.modules.nixos.applications-git
    inputs.ojuny-template.modules.nixos.applications-kdeconnect
    inputs.ojuny-template.modules.nixos.applications-multimedia
    inputs.ojuny-template.modules.nixos.applications-office
    inputs.ojuny-template.modules.nixos.applications-obsidian
    inputs.ojuny-template.modules.nixos.applications-steam
    inputs.ojuny-template.modules.nixos.applications-terminal
    inputs.ojuny-template.modules.nixos.applications-vesktop
  ];

  home-manager.sharedModules = [
    inputs.ojuny-template.modules.homeManager.stylix-colors
    inputs.ojuny-template.modules.homeManager.users-user-editor
    inputs.ojuny-template.modules.homeManager.applications-browser
    inputs.ojuny-template.modules.homeManager.applications-obsidian
    inputs.ojuny-template.modules.homeManager.applications-vesktop
    inputs.ojuny-template.modules.homeManager.applications-terminal-ghostty
    inputs.ojuny-template.modules.homeManager.applications-terminal-btop
    inputs.ojuny-template.modules.homeManager.applications-terminal-fastfetch
    inputs.ojuny-template.modules.homeManager.desktop-screensaver
    inputs.ojuny-template.modules.homeManager.applications-webapps
    inputs.ojuny-template.modules.homeManager.dux-tools
  ];
}
