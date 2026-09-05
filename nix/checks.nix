# The suites that judge ptterm.
#
# It declares its own inputs, so `default.nix` holds the package and does not
# carry the six emulators, the X server and the node tarball that only a test
# needs.
#
# `package`, `testSources`, `judges` and `esctest2` come from `default.nix`:
# the first because a suite runs against the installed package, the second
# because it knows where the repository root is and this file does not, and
# the last two because a tool is not a suite and pymux takes them from there
# as well.
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
  esctest2,
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
  # `PTTERM_TESTS=tests/test_left_right_margins.py nix build --file . checks.ptterm-unit`.
  # It reaches the evaluation through the environment, so it works with
  # impure evaluation, which a build from a file uses.
  selection =
    let
      value = builtins.getEnv "PTTERM_TESTS";
    in
    if value == "" then "tests" else value;

  # Which conformance tests run. It is a regular expression that the suite
  # matches against "Class.method", for instance
  # `PTTERM_ESCTEST_INCLUDE=BSTests nix build --file . checks.ptterm-esctest`.
  esctestInclude =
    let
      value = builtins.getEnv "PTTERM_ESCTEST_INCLUDE";
    in
    if value == "" then ".*" else value;

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
  '';
  runPytest = "python -m pytest $selection -q -p no:cacheprovider";

  # The unit group runs what needs no oracle, so nothing in it should skip.
  # A test that does need one and says so with `importorskip` or a `skipif`
  # would land here, find nothing, skip, and pass in silence. That is the one
  # way the split can go quietly wrong, so it is the one thing to watch.
  #
  # The report stays beside the log, as the machine readable half of it.
  runUnitPytest = ''
    ${runPytest} --junitxml="$out/report.xml"
    status=$?
    skipped="$(sed -n 's/.*[[:space:]]skipped="\([0-9]*\)".*/\1/p' \
      "$out/report.xml" | head -1)"
    if [ "$status" = 0 ] && [ "''${skipped:-0}" != "0" ]; then
      echo "ptterm-unit skipped $skipped tests, and nothing here should skip."
      echo "A test that needs an oracle belongs in another group, and it"
      echo "gets there by importing that oracle. tests/conftest.py says how."
      exit 1
    fi
    exit "$status"
  '';
in
{
  # The tests that need nothing but python. About forty of the sixty
  # files, so this is the one to run while working, and it pays for
  # none of the six emulators.
  #
  # ncurses is here for the one test that compiles the terminfo entry.
  unit = suite {
    name = "ptterm-unit";
    inputs = [
      pythonWithTests
      ncurses
    ];
    env = { inherit selection; };
    setup = prepare + ''
      export PTTERM_GROUP=unit
    '';
  } runUnitPytest;

  # The tests that read a screen back from another emulator. These are
  # what the six judges are built for.
  panel = suite {
    name = "ptterm-panel";
    inputs = [ pythonWithTests ];
    env = { inherit selection; };
    setup = prepare + oracles + everyJudgeAnswers + ''
      export PTTERM_GROUP=panel
    '';
  } runPytest;

  # The colour specs, read back with the real Xlib. `ptterm/xcms.py` is
  # a port of the colour management of Xlib, and only the original says
  # whether the port is right.
  xcms = suite {
    name = "ptterm-xcms";
    inputs = [
      pythonWithTests
      xorg-server
    ];
    env = { inherit selection; };
    setup = prepare + display + ''
      python -c "import sys; sys.path.insert(0, 'tests'); import xlib_oracle; assert xlib_oracle.xlib_color('rgb:f/f/f') == (255, 255, 255)"
      export PTTERM_GROUP=xcms
    '';
  } runPytest;

  # The conformance suite of xterm, run against ptterm on a pty of its own.
  #
  # Every other suite here reads the screen from the outside. This one runs a
  # program inside ptterm, which writes sequences and reads the reports that
  # come back, so it judges what a real program sees.
  #
  # It is not a pass or fail of its own: each failure names a real difference
  # from xterm. The run is judged against the list in
  # `tests/esctest-failures.txt`, and a difference either way is what fails
  # the check.
  esctest = suite {
    name = "ptterm-esctest";
    inputs = [
      pythonWithTests
      esctest2
    ];
    env = { inherit esctestInclude; };
    setup = prepare + ''
      export PTTERM_ESCTEST=${esctest2}/share/esctest2
      export PTTERM_ESCTEST_INCLUDE="$esctestInclude"
      export PTTERM_ESCTEST_OUT="$out"
    '';
  } "python tests/drive_with_esctest.py";

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
