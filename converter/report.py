"""Renders ``batch.Result`` / ``batch.Summary`` as either output format.

Two renderers, pure over ``Result`` / ``Summary`` plus an output stream:

* The **text** renderer reproduces today's prose lines (``note``/``FAILED``)
  through the ``tqdm.write`` classmethod, so the bar's cursor handling keeps
  working without this module needing the bar instance itself.
* The **JSON** renderer builds the record dicts of ``docs/specs/spec-json-output.md``'s
  *record contract* and writes them as JSON Lines.

Kept out of ``batch.py`` (whose job is running conversions, not formatting
them) and out of ``cli.py`` (already large): two output formats over the same
``Result`` belong together in one module. ``batch`` never imports this module
-- that would be a cycle -- so ``cli`` is the only caller that wires a
renderer into ``batch.run_batch``.
"""

import json
import sys
from typing import BinaryIO, TextIO

from tqdm import tqdm

from converter.batch import Outcome, Result, Summary, Task

#: The record contract's schema version (docs/specs/spec-json-output.md). Additive
#: changes -- a new key or record type -- keep this; removing, renaming a key,
#: or changing a value's meaning would raise it.
SCHEMA = 1


def render_text(result: Result) -> None:
    """Print one result exactly as ``batch._report`` does today.

    A ``FAILED`` result goes to stderr and stops there -- its notes, if any,
    are not printed. Every other outcome prints its notes, in order, to
    stdout. Uses the ``tqdm.write`` classmethod directly rather than a bound
    instance method, so it keeps the progress bar's cursor handling without
    needing the bar itself, and works the same whether or not a bar exists.
    """
    name = result.task.src.name
    if result.outcome is Outcome.FAILED:
        tqdm.write(f"FAILED  {name}: {result.error}", file=sys.stderr)
        return
    for note in result.notes:
        tqdm.write(f"note    {name}: {note}")


def file_record(result: Result) -> dict[str, object]:
    """Build the ``file`` record for one result.

    Key order matches *The record contract*: ``type`` and ``schema`` lead,
    then ``source``/``output`` (absolute via ``Path.absolute()``, never
    ``resolve()`` -- the consumer needs the path independent of the
    converter's working directory, not rewritten through a symlink or a
    Windows ``subst``/junction). ``attempt`` is ``null`` unless the outcome is
    ``converted``; ``error`` is ``null`` unless it is ``failed``; ``notes`` is
    always an array, ``[]`` when there is nothing to report.
    """
    converted = result.outcome is Outcome.CONVERTED
    failed = result.outcome is Outcome.FAILED
    return {
        "type": "file",
        "schema": SCHEMA,
        "source": str(result.task.src.absolute()),
        "output": str(result.task.dst.absolute()),
        "outcome": result.outcome.value,
        "attempt": result.attempt if converted else None,
        "notes": list(result.notes),
        "error": result.error if failed else None,
    }


def planned_record(task: Task) -> dict[str, object]:
    """Build the ``planned`` record for one task a ``--dry-run`` would convert."""
    return {
        "type": "planned",
        "schema": SCHEMA,
        "source": str(task.src.absolute()),
        "output": str(task.dst.absolute()),
    }


def summary_record(
    summary: Summary, *, planned: int, exit_code: int, dry_run: bool
) -> dict[str, object]:
    """Build the one ``summary`` record that ends a run's JSON stream.

    ``planned`` is computed by the caller from the ``planned`` records it
    emitted, not read off *summary* -- ``batch.Summary`` gaining a ``planned``
    field would change ``describe()`` and the text-mode output.
    """
    return {
        "type": "summary",
        "schema": SCHEMA,
        "converted": summary.converted,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "unsupported": summary.unsupported,
        "total": summary.total,
        "planned": planned,
        "exit_code": exit_code,
        "dry_run": dry_run,
    }


def write_json(record: dict[str, object], stream: BinaryIO, *, text_stream: TextIO) -> None:
    """Write one record as a JSON Lines entry: ASCII bytes, ``\\n``, flushed.

    *text_stream* (the text layer over the same file descriptor in
    production, ``sys.stdout``) is flushed first, so nothing queued there
    earlier is reordered relative to this write. The bytes then bypass that
    text layer entirely and go straight to *stream* (``sys.stdout.buffer``),
    because on Windows a piped stdout's text layer turns ``\\n`` into
    ``\\r\\n`` -- measured, Python 3.13. ``ensure_ascii=True`` keeps every
    line valid under any code page: a non-ASCII name becomes a ``\\uXXXX``
    escape, and a POSIX name that reached Python as lone surrogates escapes
    the same way, so ``.encode("ascii")`` never raises.
    """
    text_stream.flush()
    stream.write(json.dumps(record, ensure_ascii=True).encode("ascii") + b"\n")
    stream.flush()
