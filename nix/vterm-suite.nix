# The test suite of libvterm, and libvterm's own program that answers it.
#
# libvterm is already a judge here: `ptterm-panel` feeds the same bytes to it
# and to ptterm and compares the two screens. It also ships 43 test files and
# a runner that drives them against any program, which is the other direction:
# their suite judging ours.
#
# nixpkgs builds the library and installs no test, so this takes the same
# source and builds what a test needs. The same source on purpose: a recorded
# failure names a file and a line in it, and a different version moves the
# lines.
#
# Two things come out of it.
#
# `tests` is the test files and the runner. `checks.ptterm-vterm` drives them
# against `ptterm/tests/vterm_harness.py`, which answers out of ptterm's own
# screen. That is the direct plug-in: ptterm stands where libvterm stands.
#
# `harness` is `t/harness.c`, built. It is libvterm answering for itself, and
# it is what `checks.pymux-vterm` needs: there pymux sits in the middle, and
# the assertions are answered by a real libvterm reading what pymux emitted.
# Nothing of ours decides anything in that check, which is the point of it.
#
# Both are build inputs of a test and reach no closure that runs.
{
  lib,
  stdenv,
  libvterm-neovim,
}:
let
  inherit (libvterm-neovim) version src;
in
{
  tests = stdenv.mkDerivation {
    pname = "libvterm-tests";
    inherit version src;

    dontConfigure = true;
    dontBuild = true;

    installPhase = ''
      runHook preInstall

      mkdir -p $out/share/libvterm-tests
      cp t/run-test.pl t/*.test $out/share/libvterm-tests/

      runHook postInstall
    '';

    meta = {
      description = "The test files of libvterm, and the runner that drives them";
      homepage = "https://www.leonerd.org.uk/code/libvterm/";
      license = lib.licenses.mit;
      platforms = lib.platforms.unix;
    };
  };

  # The Makefile builds this with libtool against the library it just built.
  # There is no library to build here, because nixpkgs built one, so the two
  # compile lines are all that is left. `-I src` is what the file asks for:
  # it says "we pull in some internal bits too" and includes
  # `src/vterm_internal.h`.
  harness = stdenv.mkDerivation {
    pname = "libvterm-harness";
    inherit version src;

    buildInputs = [ libvterm-neovim ];

    dontConfigure = true;

    buildPhase = ''
      runHook preBuild

      $CC -Wall -std=c99 -Iinclude -Isrc -o harness t/harness.c -lvterm

      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall

      install -Dm755 harness $out/bin/libvterm-harness

      runHook postInstall
    '';

    meta = {
      description = "The program that libvterm's own test suite drives";
      homepage = "https://www.leonerd.org.uk/code/libvterm/";
      license = lib.licenses.mit;
      mainProgram = "libvterm-harness";
      platforms = lib.platforms.unix;
    };
  };
}
