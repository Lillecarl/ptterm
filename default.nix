# The package this repository builds, and the tests that judge it. Nothing
# else belongs here: the dev shell and the collection that assembles this
# with its siblings live in pyterm.
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
  python,
  pytest,
  hypothesis,
  runCommand,
  rustPlatform,
  ncurses,
  kitty,
  libvterm-neovim,
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

    passthru = { inherit checks judges; };

    meta = {
      description = "Terminal emulator for prompt_toolkit";
      homepage = "https://github.com/prompt-toolkit/ptterm";
      license = lib.licenses.bsd3;
    };
  };

  pythonWithTests = python.withPackages (ps: [
    package
    pytest
    hypothesis
  ]);

  # Only the tests, not the whole repository. A copy of everything makes
  # the test runs rebuild on every unrelated edit.
  testSources = lib.fileset.toSource {
    root = ./.;
    fileset = ./tests;
  };

  # The judges that are written in Rust: WezTerm and Alacritty, each with a
  # screen model of its own. One program answers for both, so the python
  # side asks one process instead of starting two.
  judges = rustPlatform.buildRustPackage {
    pname = "ptterm-judges";
    version = "0.1.0";
    # Only the judges, not the whole repository: otherwise every change to
    # a test rebuilds every crate.
    src = builtins.path {
      path = ./tests/judges;
      name = "ptterm-judges-source";
    };
    cargoLock = {
      lockFile = ./tests/judges/Cargo.lock;
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

  # Two emulators to compare the screen of ptterm against. `PTTERM_KITTY` is
  # the one kitty carries as a python extension, and kitty is the terminal
  # that pymux runs inside. `PTTERM_LIBVTERM` is the one that Vim and Neovim
  # carry, which leans towards xterm. Where the two agree and ptterm differs,
  # ptterm is wrong; where they disagree, the difference is a choice.
  oracles = ''
    export PTTERM_KITTY=${kitty}/lib/kitty
    export PTTERM_LIBVTERM=${libvterm-neovim}/lib/libvterm.so
    export PTTERM_JUDGES=${judges}/bin/ptterm-judges
  '';

  checks = {
    tests = runCommand "ptterm-tests" {
      # ncurses for the check that the terminfo entry compiles.
      nativeBuildInputs = [
        pythonWithTests
        ncurses
      ];
    } ''
      cp -r ${testSources}/tests .
      chmod -R +w .
      export HOME="$TMPDIR"
      export LANG=C.UTF-8
      export PYTHONDONTWRITEBYTECODE=1
      ${oracles}

      # A comparison that cannot run proves nothing, so say so loudly
      # instead of skipping.
      python -c "import sys; sys.path.insert(0, sys.argv[1]); import kitty.fast_data_types" "$PTTERM_KITTY"
      python -c "import ctypes, os; ctypes.CDLL(os.environ['PTTERM_LIBVTERM'])"
      echo '{"data":"x","lines":1,"columns":1}' | "$PTTERM_JUDGES" > /dev/null

      python -m pytest tests -q -p no:cacheprovider
      touch "$out"
    '';

    # The hunt for deviations between ptterm and kitty. This is not a gate:
    # it finds them faster than they get fixed, and each one needs a
    # decision about whether to follow kitty or xterm.
    #
    # `PTTERM_FUZZ` says how many examples to try. It reaches the evaluation
    # through the environment, so it only works with impure evaluation,
    # which `nix-build` uses by default.
    fuzz =
      let
        value = builtins.getEnv "PTTERM_FUZZ";
        examples = if value == "" then "2000" else value;
      in
      runCommand "ptterm-fuzz" {
        nativeBuildInputs = [ pythonWithTests ];
        # Rerun whenever the count changes.
        inherit examples;
      } ''
        cp -r ${testSources}/tests .
        chmod -R +w .
        export HOME="$TMPDIR"
        export LANG=C.UTF-8
        export PYTHONDONTWRITEBYTECODE=1
        ${oracles}
        export PTTERM_FUZZ="$examples"

        python -m pytest tests/fuzz_against_kitty.py -q -p no:cacheprovider
        touch "$out"
      '';
  };
in
package
