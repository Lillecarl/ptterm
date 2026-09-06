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
  anyio,
  hypothesis,
  callPackage,
  kitty,
  libvterm-neovim,
  ncurses,
  libx11,
  perl,
  xorg-server,
  xterm,
  vttest,
  makeFontsConf,
  dejavu_fonts,
  package,
  testSources,
  judges,
  esctest2,
  vtermSuite,
  alacrittySuite,
}:
let
  inherit (callPackage ./suite.nix { }) suite;

  # The check below is called `vttest` too, and a reader should not have to
  # work out which of the two a name means.
  vttestProgram = vttest;


  # anyio carries the pytest plugin that runs a coroutine test. Without
  # it pytest fails one with "async def functions are not natively
  # supported", so no async test in this repository runs at all.
  pythonWithTests = python.withPackages (ps: [
    package
    pytest
    anyio
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
    export PTTERM_XTERMJS=${judges.xtermjs}/bin/xtermjs-judge
    export PTTERM_XTERM=${xterm}/bin/xterm
  '';

  # xterm draws with the fonts that fontconfig finds, and a build sandbox
  # has no `/etc/fonts` at all. Without this it dies at startup.
  fontsConf = makeFontsConf { fontDirectories = [ dejavu_fonts ]; };

  # A display server of its own, with nothing on it.
  #
  # `-displayfd` makes the server say which display it took, once it is
  # ready to answer. Sleeping for a while instead is a race.
  #
  # The screen is large enough for an xterm of eighty columns and more.
  # A window that does not fit the screen is a window that xterm will
  # not take, and the judge would read the wrong size back.
  xvfb = ''
    Xvfb -displayfd 3 -screen 0 1280x1024x24 3> display.txt \
      > xvfb.log 2>&1 &
    trap 'kill %1' EXIT
    while [ ! -s display.txt ]; do sleep 0.1; done
    export DISPLAY=":$(cat display.txt)"
  '';

  # The judge for a colour spec: the real Xlib. `ptterm/xcms.py` is a
  # port of the colour management of Xlib, and only a comparison against
  # the original says whether the port is right.
  #
  # Xcms needs a display, because it reads the screen description from
  # the root window. A bare Xvfb carries none, so Xlib uses its built-in
  # description, which is the one xterm uses on such a screen too.
  display = ''
    export PTTERM_LIBX11=${libx11}/lib/libX11.so
  '' + xvfb;

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

  # Which of libvterm's test files run. It is a regular expression that the
  # driver matches against the name of a file, for instance
  # `PTTERM_VTERM_INCLUDE=movecursor nix build --file . checks.ptterm-vterm`.
  vtermInclude =
    let
      value = builtins.getEnv "PTTERM_VTERM_INCLUDE";
    in
    if value == "" then ".*" else value;

  # Which item of vttest's main menu the walker enters. It is a regular
  # expression matched against "N title", for instance
  # `PTTERM_VTTEST_INCLUDE='^4 ' nix build --file . checks.ptterm-vttest.run`.
  # `PTTERM_VTTEST_ARGS` passes options to vttest itself; `-u` is the one
  # that keeps the terminal in UTF-8.
  vttestInclude =
    let
      value = builtins.getEnv "PTTERM_VTTEST_INCLUDE";
    in
    if value == "" then ".*" else value;
  vttestArgs = builtins.getEnv "PTTERM_VTTEST_ARGS";

  # Whether vttest also draws on the terminal this runs in. That is what
  # makes the walker a proxy, so a picture can be taken of vttest in a
  # real emulator with pymux in the chain and without it. The walker's
  # own words go to stderr then, because its stdout is vttest's screen.
  vttestThrough = builtins.getEnv "PTTERM_VTTEST_THROUGH";

  # Which recordings the instruction count measures, and how far a count may
  # move before the check fails. Both are for narrowing a hunt, for instance
  # `PTTERM_INSTRUCTIONS_INCLUDE=vim nix build --file . checks.ptterm-instructions`.
  # A narrowed run makes no claim about the recordings it did not choose.
  instructionsInclude = builtins.getEnv "PTTERM_INSTRUCTIONS_INCLUDE";
  instructionsTolerance = builtins.getEnv "PTTERM_INSTRUCTIONS_TOLERANCE";

  prepare = ''
    cp -r ${testSources}/tests .
    cp ${testSources}/pyproject.toml .
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
    echo '{"data":"x","lines":1,"columns":1}' | "$PTTERM_XTERMJS" > /dev/null
    python -c "import sys; sys.path.insert(0, 'tests'); import xterm_oracle; assert xterm_oracle.xterm_cells('x', 1, 1)[0][0].char == 'x'"
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
    inputs = [
      pythonWithTests
      # xterm itself is the seventh judge, and it is a program and not
      # a library: it needs a display to draw on and a font to draw
      # with. `tests/xterm_oracle.py` says how it is asked.
      xorg-server
      xterm
    ];
    env = { inherit selection; };
    setup = prepare + oracles + xvfb + ''
      export FONTCONFIG_FILE=${fontsConf}
    '' + everyJudgeAnswers + ''
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

  # The test suite of libvterm, run against ptterm through libvterm's own
  # runner. Nothing in libvterm changes: `run-test.pl` takes the program to
  # drive, and `tests/vterm_harness.py` is that program.
  #
  # esctest2 judges ptterm from inside a pty, as a program that writes
  # sequences and reads reports. This judges the screen from the outside, one
  # assertion at a time, in the words of an emulator that somebody else wrote.
  #
  # It is not a pass or fail of its own: each failure names a real difference
  # from libvterm. The run is judged against `tests/vterm-failures.txt`, and a
  # difference either way is what fails the check.
  vterm = suite {
    name = "ptterm-vterm";
    inputs = [
      pythonWithTests
      perl
    ];
    env = { inherit vtermInclude; };
    setup = prepare + ''
      export PTTERM_VTERM=${vtermSuite.tests}/share/libvterm-tests
      export PTTERM_VTERM_INCLUDE="$vtermInclude"
      export PTTERM_VTERM_OUT="$out"
    '';
  } "python tests/drive_with_vterm.py";

  # The other conformance program of Thomas Dickey, walked against ptterm.
  #
  # It is not a gate, and it cannot be one yet. esctest2 reads the screen
  # back and judges it. vttest draws a screen and asks a person whether what
  # they see is right, so what this leaves behind is a text file of every
  # screen it drew, with the menu path that reached it. A person reads that.
  # Lillecarl/pymux#46 says why the recorded list comes first.
  #
  # What the verdict here does judge is the walk: a run that drew nothing,
  # or an exclusion in `NOT_OURS` that names no menu item.
  vttest = suite {
    name = "ptterm-vttest";
    inputs = [
      pythonWithTests
      vttestProgram
    ];
    env = { inherit vttestInclude vttestArgs vttestThrough; };
    setup = prepare + ''
      export PTTERM_VTTEST=${vttestProgram}/bin/vttest
      export PTTERM_VTTEST_INCLUDE="$vttestInclude"
      export PTTERM_VTTEST_ARGS="$vttestArgs"
      export PTTERM_VTTEST_THROUGH="$vttestThrough"
      export PTTERM_VTTEST_OUT="$out"
    '';
    # In the proxy mode, stdout is what a terminal would have been given,
    # so it is kept as a file rather than mixed into the log. Two things
    # follow. The bytes can be counted, which is how a proxy that writes
    # to the wrong stream is caught: both streams reach the same log, so
    # the log alone cannot tell them apart. And the walker's own words go
    # to stderr, where they still reach the log.
  } ''
    if [ -n "$vttestThrough" ]; then
      python tests/drive_with_vttest.py > "$out/through.bin"
    else
      python tests/drive_with_vttest.py
    fi
  '';

  # What it costs to parse a recording, in bytecode instructions.
  #
  # Nothing else here measures cost. A change that makes the parser ten times
  # slower passes every other check, and nobody notices until pymux feels
  # wrong under a hand.
  #
  # The unit is not a second. A second belongs to the machine that counted it,
  # and this sandbox runs beside other jobs. An instruction count is the same
  # on every machine and under any load, so a budget file can hold it the way
  # the conformance lists hold a failure.
  #
  # `PYTHONHASHSEED` is pinned because the order of a set decides a branch,
  # and a branch decides a count.
  instructions = suite {
    name = "ptterm-instructions";
    inputs = [ pythonWithTests ];
    env = { inherit instructionsInclude instructionsTolerance; };
    setup = prepare + ''
      export PTTERM_INSTRUCTIONS=${alacrittySuite}/share/alacritty-ref
      export PTTERM_INSTRUCTIONS_INCLUDE="$instructionsInclude"
      export PTTERM_INSTRUCTIONS_TOLERANCE="$instructionsTolerance"
      export PTTERM_INSTRUCTIONS_OUT="$out"
      export PYTHONHASHSEED=0
    '';
  } "python tests/measure_instructions.py";

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
