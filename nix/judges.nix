# The other terminal emulators that ptterm is judged against.
#
# Each one is a program that takes a screen description on stdin and gives
# back the cells it drew, so the python side asks one interface of all of
# them. `tests/panel.py` is the other half.
#
# None of these reaches the closure of the package. They are build inputs of
# a test and nothing else.
{
  lib,
  stdenv,
  rustPlatform,
  fetchurl,
  writeShellScriptBin,
  nodejs,
  libghostty-vt,
  judgeSources,
}:
rec {
  # The judges that are written in Rust: WezTerm and Alacritty, each with a
  # screen model of its own. One program answers for both, so the python
  # side asks one process instead of starting two.
  rust = rustPlatform.buildRustPackage {
    pname = "ptterm-judges";
    version = "0.1.0";
    # Only the judges, not the whole repository: otherwise every change to
    # a test rebuilds every crate.
    src = judgeSources.rust;
    cargoLock = {
      lockFile = judgeSources.rustLock;
      outputHashes = {
        "wezterm-term-0.1.0" = "sha256-Fe2rH9HegaUixPXHyHv4B8c0RI34GPbeX8mTzHCQwQ4=";
        "finl_unicode-1.3.0" = "sha256-38S6XH4hldbkb6NP+s7lXa/NR49PI0w3KYqd+jPHND0=";
      };
    };
    doCheck = false;

    # wezterm-term reads a file of termwiz by a path relative to its own
    # directory, which the vendored copy does not have: every crate lands
    # beside the others and the name carries a version. The name without
    # the version brings the path back.
    preBuild = ''
      ln -sfn "$NIX_BUILD_TOP/cargo-vendor-dir/termwiz-0.24.0" \
              "$NIX_BUILD_TOP/cargo-vendor-dir/termwiz"
    '';
  };

  # The judge that reads Ghostty. libghostty-vt is the terminal of Ghostty
  # as a library with a C API, and this is C and not a binding because the
  # library hands out sized structs and tagged unions: the compiler knows
  # their layout, and a hand written binding only thinks it does.
  ghostty = stdenv.mkDerivation {
    pname = "ptterm-ghostty-judge";
    version = "0.1.0";
    src = judgeSources.c;
    buildInputs = [ libghostty-vt ];
    buildPhase = ''
      $CC -O2 -I${libghostty-vt.dev}/include -o ghostty-judge ghostty_judge.c \
        -L${libghostty-vt}/lib -lghostty-vt
    '';
    installPhase = ''
      install -Dm755 ghostty-judge $out/bin/ghostty-judge
    '';
  };

  # The judge that reads xterm.js, the terminal that VS Code draws in.
  # `@xterm/headless` is that emulator with no drawing attached, and it
  # depends on nothing, so one tarball is the whole of it. node is a build
  # input of the tests and reaches no closure that runs.
  xtermHeadless = fetchurl {
    url = "https://registry.npmjs.org/@xterm/headless/-/headless-6.0.0.tgz";
    hash = "sha256-B+SXCxZ05+9svVfIwXdG6q3NQap99bM2lf1knm7E14o=";
  };

  xtermLibrary = stdenv.mkDerivation {
    pname = "ptterm-xterm-judge";
    version = "6.0.0";
    src = judgeSources.js;
    dontBuild = true;
    installPhase = ''
      mkdir -p $out/lib
      tar xzf ${xtermHeadless} -C $out/lib --strip-components=1
      cp xterm_judge.js $out/lib/
    '';
  };

  xterm = writeShellScriptBin "xterm-judge" ''
    exec ${nodejs}/bin/node ${xtermLibrary}/lib/xterm_judge.js \
      ${xtermLibrary}/lib/lib-headless/xterm-headless.js "$@"
  '';
}
