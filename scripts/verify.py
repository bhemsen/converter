"""Run every machine check this project has, as one non-interactive command.

The loopkit workflow contract needs a single Verify command, and the stack has
three separate checks.  Rather than chain them in a shell -- which would differ
between PowerShell and sh, and which the CI matrix would then have to duplicate
-- they are driven from here.

Every tool is invoked as ``sys.executable -m <tool>`` rather than by bare name,
so the checks always run against the interpreter that started this script.  A
bare ``ruff`` would resolve through PATH and can easily be a different install
than the virtual environment being tested.

All checks run even after one fails, so a single invocation reports everything
that is wrong instead of only the first thing.
"""

import subprocess
import sys

#: Label -> the module invocation that performs the check.
CHECKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lint", ("ruff", "check", ".")),
    ("format", ("ruff", "format", "--check", ".")),
    ("test", ("pytest",)),
)


def run(label: str, args: tuple[str, ...]) -> bool:
    """Run one check, streaming its output, and report whether it passed."""
    # Flushed explicitly: the child writes straight to the console while this
    # process buffers, so without it the headers all arrive after the output
    # they are supposed to introduce.
    print(f"=== {label}: {' '.join(args)}", flush=True)
    completed = subprocess.run(  # noqa: S603 - argv list, shell=False, no interpolation
        [sys.executable, "-m", *args],
        stdin=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def main() -> int:
    """Return 0 only when every check passed."""
    failed = [label for label, args in CHECKS if not run(label, args)]
    if failed:
        print(f"\nFAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"\nOK: {', '.join(label for label, _ in CHECKS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
