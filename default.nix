# The package this repository builds. The suites that judge it live in
# `nix/checks.nix`, the emulators they compare against in `nix/judges.nix`, and
# the conformance suite in `nix/esctest2.nix`. Each declares its own inputs, so
# nothing that only a test needs is named here.
#
# The last two reach `passthru`, because a tool is not a suite and pymux runs
# the same conformance suite in a pane. Neither reaches the closure of the
# package: `passthru` names a derivation and does not depend on it.
#
# Nothing else belongs in this repository: the dev shell and the collection
# that assembles this with its siblings live in pyterm.
#
# prompt-toolkit and pyte arrive as arguments, so nixpkgs supplies them when
# this repository is built on its own, and pyterm supplies the sibling
# checkouts when it builds the collection.
{
  lib,
  buildPythonPackage,
  setuptools,
  prompt-toolkit,
  pyte,
  wcwidth,
  callPackage,
}:
let
  package = buildPythonPackage {
    pname = "ptterm";
    version = "0.1";
    src = lib.cleanSource ./.;
    pyproject = true;

    # Only ruff configuration lives in pyproject.toml, so the build backend
    # has to be named here rather than read from it.
    build-system = [ setuptools ];
    dependencies = [
      prompt-toolkit
      pyte
      wcwidth
    ];

    # The suites run as `checks.tests` and `checks.fuzz`, against the
    # installed package.
    doCheck = false;
    pythonImportsCheck = [ "ptterm" ];

    passthru = { inherit checks judges esctest2 vtermSuite; };

    meta = {
      description = "Terminal emulator for prompt_toolkit";
      homepage = "https://github.com/prompt-toolkit/ptterm";
      license = lib.licenses.bsd3;
    };
  };

  # Only the tests, not the whole repository. A copy of everything makes
  # the test runs rebuild on every unrelated edit.
  #
  # These are built here and not under `nix`, because `./.` there is the
  # `nix` directory and these need the root of the repository.
  testSources = lib.fileset.toSource {
    root = ./.;
    fileset = ./tests;
  };

  # Each judge is built from its own directory alone. Otherwise every change
  # to a test rebuilds every crate.
  judgeSources = {
    rust = builtins.path {
      path = ./tests/judges;
      name = "ptterm-judges-source";
    };
    rustLock = ./tests/judges/Cargo.lock;
    c = builtins.path {
      path = ./tests/judges-c;
      name = "ptterm-ghostty-judge-source";
    };
    js = builtins.path {
      path = ./tests/judges-js;
      name = "ptterm-xterm-judge-source";
    };
  };

  # The other emulators that the panel compares ptterm against. They are
  # build inputs of a test and reach no closure that runs.
  judges = callPackage ./nix/judges.nix { inherit judgeSources; };

  # The conformance suite of xterm, which judges a terminal from the inside.
  # pymux runs the same one in a pane, and takes it from here.
  esctest2 = callPackage ./nix/esctest2.nix { };

  # The test files of libvterm, and libvterm's own program that answers
  # them. `ptterm-vterm` uses the first with a harness of ours in place of
  # the second. pymux takes both from here and puts itself in the middle.
  vtermSuite = callPackage ./nix/vterm-suite.nix { };

  checks = callPackage ./nix/checks.nix {
    inherit
      package
      testSources
      judges
      esctest2
      vtermSuite
      ;
  };
in
package
