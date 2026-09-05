# The reference tests of Alacritty.
#
# Alacritty is already a judge here: `ptterm-panel` feeds the same bytes to it
# and to ptterm and compares the two screens. It also ships 45 reference
# tests, each a recording and the grid that recording should make, which is
# the other direction: their suite judging ours.
#
# A reference test is four files. `alacritty.recording` is the raw bytes a
# real program wrote, `size.json` is the screen it wrote them to,
# `config.json` says how much history the terminal kept, and `grid.json` is
# Alacritty's own serialization of the grid that came out.
#
# `tests/judges/src/bin/alacritty-ref.rs` reads three of those and takes the
# fourth from a pymux pane: `checks.pymux-alacritty` puts the recording on the
# screen of a pane and hands what pymux emitted to a real `Term`. So
# Alacritty's own assertion holds if we emit what the program drew.
#
# **The version is pinned to the crate the judge builds.** `grid.json` is
# serde's layout for `Grid<Cell>`, and the judge deserializes it with
# `alacritty_terminal` from crates.io. `tests/judges/Cargo.lock` names 0.26.0,
# and `v0.17.0` is the tag whose `alacritty_terminal/Cargo.toml` carries that
# version. A different one moves a field and fails all 45 the same way.
#
# It comes from GitHub and not from crates.io, because the published crate
# does not ship `tests/`.
{
  lib,
  stdenv,
  fetchFromGitHub,
}:
let
  version = "0.17.0";
in
stdenv.mkDerivation {
  pname = "alacritty-ref-tests";
  inherit version;

  src = fetchFromGitHub {
    owner = "alacritty";
    repo = "alacritty";
    rev = "v${version}";
    hash = "sha256-iZtCH2DrSs6o3AG2koI2TyC3116aMlawHFkCd0TYhas=";
  };

  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/alacritty-ref
    cp -r alacritty_terminal/tests/ref/* $out/share/alacritty-ref/

    runHook postInstall
  '';

  meta = {
    description = "The reference tests of Alacritty: a recording and the grid it makes";
    homepage = "https://github.com/alacritty/alacritty";
    license = lib.licenses.asl20;
    platforms = lib.platforms.unix;
  };
}
