# The test suite of libvterm, on its own.
#
# libvterm is already a judge here: `ptterm-panel` feeds the same bytes to it
# and to ptterm and compares the two screens. It also ships 43 test files and
# a runner that drives them against any program, which is the other direction:
# their suite judging ours.
#
# nixpkgs builds the library and installs no test, so this takes the same
# source and installs the tests alone. The same source on purpose: a recorded
# failure names a file and a line in it, and a different version moves the
# lines.
#
# `t/harness.c` is left behind. `ptterm/tests/vterm_harness.py` is the program
# that takes its place, and building the C one would need the library built
# with its internal headers.
#
# It is a build input of a test and reaches no closure that runs.
{
  lib,
  stdenv,
  libvterm-neovim,
}:
stdenv.mkDerivation {
  pname = "libvterm-tests";
  inherit (libvterm-neovim) version src;

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
}
