{
  lib,
  stdenvNoCC,
  calamares-nixos-extensions,
  templatePath,
  prepareRepo ? null,
  regenerateHardware ? null,
  mkpasswd ? null,
  offline ? false,
}:

stdenvNoCC.mkDerivation {
  pname = "ojuny-calamares-extensions";
  version = "0.1.0";

  src = ./.;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/etc $out/lib $out/share
    cp -r ${calamares-nixos-extensions}/etc/calamares $out/etc/calamares
    cp -r ${calamares-nixos-extensions}/lib/calamares $out/lib/calamares
    cp -r ${calamares-nixos-extensions}/share/calamares $out/share/calamares

    chmod -R u+w $out

    cp config/settings.conf $out/etc/calamares/settings.conf
    cp config/modules/ojuny.conf $out/etc/calamares/modules/ojuny.conf
    cp config/modules/template.conf $out/etc/calamares/modules/template.conf
    cp config/modules/origin.conf $out/etc/calamares/modules/origin.conf
    cp config/modules/users.conf $out/etc/calamares/modules/users.conf
    cp config/modules/welcome.conf $out/etc/calamares/modules/welcome.conf
    ${lib.optionalString offline ''
      sed -i '/^    - internet$/d' $out/etc/calamares/modules/welcome.conf
    ''}
    cp config/modules/partition.conf $out/etc/calamares/modules/partition.conf
    cp -r branding/ojuny $out/share/calamares/branding/ojuny
    mkdir -p $out/lib/calamares/modules/ojuny
    cp modules/ojuny/* $out/lib/calamares/modules/ojuny/

    substituteInPlace $out/etc/calamares/settings.conf \
      --replace-fail '@out@' "$out"
    substituteInPlace $out/etc/calamares/modules/ojuny.conf \
      --replace-fail '@templatePath@' "${templatePath}" \
      --replace-fail '@prepareRepo@' "${
        if prepareRepo == null then "" else lib.getExe' prepareRepo "prepare-repo"
      }" \
      --replace-fail '@regenerateHardware@' "${
        if regenerateHardware == null then "" else lib.getExe' regenerateHardware "regenerate-hardware"
      }" \
      --replace-fail '@mkpasswd@' "${if mkpasswd == null then "" else lib.getExe mkpasswd}"

    runHook postInstall
  '';

  meta = {
    description = "Ojuny Calamares configuration and branding";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
  };
}
