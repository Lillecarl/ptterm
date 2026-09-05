# The suites that judge ptterm.
#
# It declares its own inputs, so `default.nix` holds the package and does not
# carry the six emulators, the X server and the node tarball that only a test
# needs.
#
# `package`, `testSources` and `judges` come from `default.nix`: the first
# because a suite runs against the installed package, the second because it
# knows where the repository root is and this file does not, and the third
# because a judge is a tool and not a suite.
#
# `nix/suite.nix` says why a check is two derivations.
{
  python,
  pytest,
  hypothesis,
  callPackage,
  kitty,
  libvterm-neovim,
  ncurses,
  libx11,
  xorg-server,
  package,
  testSources,
  judges,
}:
let
  inherit (callPackage ./suite.nix { }) suite;

  pythonWithTests = python.withPackages (ps: [
    package
    pytest
    hypothesis
  ]);

  # The emulators to compare the screen of ptterm against. `PTTERM_KITTY` is
  # the one kitty carries as a python extension, and kitty is the terminal
  # that pymux runs inside. `PTTERM_LIBVTERM` is the one that Vim and Neovim
  # carry, which leans towards xterm. Where the two agree and ptterm differs,
  # ptterm is wrong; where they disagree, the difference is a choice.
  oracles = ''
    export PTTERM_KITTY=${kitty}/lib/kitty
    export PTTERM_LIBVTERM=${libvterm-neovim}/lib/libvterm.so
    export PTTERM_JUDGES=${judges.rust}/bin/ptterm-judges
    export PTTERM_GHOSTTY=${judges.ghostty}/bin/ghostty-judge
    export PTTERM_XTERM=${judges.xterm}/bin/xterm-judge
  '';

  # The judge for a colour spec: the real Xlib. `ptterm/xcms.py` is a
  # port of the colour management of Xlib, and only a comparison against
  # the original says whether the port is right.
  #
  # Xcms needs a display, because it reads the screen description from
  # the root window. A bare Xvfb carries none, so Xlib uses its built-in
  # description, which is the one xterm uses on such a screen too.
  #
  # `-displayfd` makes the server say which display it took, once it is
  # ready to answer. Sleeping for a while instead is a race.
  display = ''
    export PTTERM_LIBX11=${libx11}/lib/libX11.so
    Xvfb -displayfd 3 -screen 0 640x480x24 3> display.txt \
      > xvfb.log 2>&1 &
    trap 'kill %1' EXIT
    while [ ! -s display.txt ]; do sleep 0.1; done
    export DISPLAY=":$(cat display.txt)"
  '';

  # What pytest runs, for instance
  # `PTTERM_TESTS=tests/test_left_right_margins.py nix build --file . checks.ptterm`.
  # It reaches the evaluation through the environment, so it works with
  # impure evaluation, which a build from a file uses.
  selection =
    let
      value = builtins.getEnv "PTTERM_TESTS";
    in
    if value == "" then "tests" else value;

  prepare = ''
    cp -r ${testSources}/tests .
    chmod -R +w .
    export HOME="$TMPDIR"
    export LANG=C.UTF-8
    export PYTHONDONTWRITEBYTECODE=1
  '';

  # A comparison that cannot run proves nothing, so say so loudly instead of
  # skipping. This is setup and not part of the suite: an oracle that will
  # not load is a broken input, and it should fail the build rather than be
  # recorded as a suite that failed.
  everyJudgeAnswers = ''
    python -c "import sys; sys.path.insert(0, sys.argv[1]); import kitty.fast_data_types" "$PTTERM_KITTY"
    python -c "import ctypes, os; ctypes.CDLL(os.environ['PTTERM_LIBVTERM'])"
    echo '{"data":"x","lines":1,"columns":1}' | "$PTTERM_JUDGES" > /dev/null
    echo '{"data":"x","lines":1,"columns":1}' | "$PTTERM_GHOSTTY" > /dev/null
    echo '{"data":"x","lines":1,"columns":1}' | "$PTTERM_XTERM" > /dev/null
    python -c "import sys; sys.path.insert(0, 'tests'); import xlib_oracle; assert xlib_oracle.xlib_color('rgb:f/f/f') == (255, 255, 255)"
  '';
in
{
  tests = suite {
    name = "ptterm-tests";
    # ncurses for the check that the terminfo entry compiles, and
    # xorg-server for the Xvfb that the Xlib colour judge asks.
    inputs = [
      pythonWithTests
      ncurses
      xorg-server
    ];
    env = { inherit selection; };
    setup = prepare + oracles + display + everyJudgeAnswers;
  } "python -m pytest $selection -q -p no:cacheprovider";

  # The hunt for deviations between ptterm and kitty. This is not a gate:
  # it finds them faster than they get fixed, and each one needs a
  # decision about whether to follow kitty or xterm.
  #
  # `PTTERM_FUZZ` says how many examples to try. It reaches the evaluation
  # through the environment, so it only works with impure evaluation,
  # which a build from a file uses.
  fuzz =
    let
      value = builtins.getEnv "PTTERM_FUZZ";
      examples = if value == "" then "2000" else value;
    in
    suite {
      name = "ptterm-fuzz";
      inputs = [ pythonWithTests ];
      # Rerun whenever the count changes.
      env = { inherit examples; };
      setup = prepare + oracles + ''
        export PTTERM_FUZZ="$examples"
      '';
    } "python -m pytest tests/fuzz_against_kitty.py -q -p no:cacheprovider";
}
