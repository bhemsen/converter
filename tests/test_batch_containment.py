"""One broken output directory must not abort the rest of the batch (issue #86).

``ensure_directory`` (``converter/paths.py``) raises an uncaught ``OSError``
when a derived output path exceeds Windows' ``MAX_PATH`` -- proven end-to-end
in issue #73. These tests exercise the containment in ``run_batch`` itself
without depending on an actual Windows path-length failure, so the suite stays
green on Linux CI too: ``ensure_directory`` is monkeypatched to fail for one
task's directory exactly the way a too-long path would, and the test asserts
the rest of the tree is unaffected. ``tests/test_batch.py`` belongs to a
different, in-flight issue (#76), so this containment test lives in its own
file rather than there.
"""

from pathlib import Path

import pytest

from converter import batch
from converter.batch import Outcome, Task, run_batch, summarise
from converter.ffmpegtool import CommandResult, Tools
from converter.profiles import Attempt, Profile, StreamRule, flags

TOOLS = Tools(ffmpeg="ffmpeg", ffprobe="ffprobe")


def _no_verification_profile() -> Profile:
    """A profile whose cheap attempt is exhaustive, so success needs no probe.

    Mirrors ``exhaustive_profile`` in ``tests/test_batch.py``: keeping this
    file's fixtures self-contained (rather than importing across test modules
    owned by different issues) avoids coupling to code someone else is
    actively changing.
    """
    return Profile(
        label="STUB",
        name="stub",
        description="test double, not a shipped format",
        target_suffix=".out",
        container_options=(),
        cheap_attempt=Attempt(label="copy-all", options=flags("-c copy")),
        explicit_streams=False,
        partial_mapping=False,
        rules={"video": StreamRule(frozenset({"h264"}), flags("-c:v copy"))},
    )


def make_task(tmp_path: Path, name: str, out_dir: str = "out") -> Task:
    src = tmp_path / f"{name}.src"
    src.write_bytes(b"data")
    return Task(src, tmp_path / out_dir / f"{name}.out")


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """A cheap attempt that always succeeds and writes the output file."""

    def run(argv, **_kwargs):
        argv = list(argv)
        Path(argv[-1]).write_bytes(b"converted")
        return CommandResult(tuple(argv), 0, "", "")

    monkeypatch.setattr(batch.ffmpegtool, "run", run)


def _fail_only_for(monkeypatch, bad_dir: Path, message: str) -> None:
    """Make ``ensure_directory`` fail exactly like a too-long path would, but
    only for *bad_dir* -- every other directory is created for real, so the
    test proves containment rather than merely that a stub was called."""
    real_ensure_directory = batch.ensure_directory

    def flaky(path: Path) -> None:
        if path == bad_dir:
            raise OSError(206, message)
        real_ensure_directory(path)

    monkeypatch.setattr(batch, "ensure_directory", flaky)


class TestOneBadOutputDirectoryDoesNotAbortTheBatch:
    def test_other_files_still_convert_and_the_bad_one_is_a_named_failure(
        self, tmp_path, monkeypatch, fake_ffmpeg
    ):
        bad_dir = tmp_path / "out" / "bad"
        _fail_only_for(monkeypatch, bad_dir, "path is too long (stubbed)")
        profile = _no_verification_profile()
        good_a = make_task(tmp_path, "alpha")
        good_b = make_task(tmp_path, "bravo")
        bad = Task(tmp_path / "gamma.src", bad_dir / "gamma.out")
        bad.src.write_bytes(b"data")

        results = run_batch(profile, [good_a, good_b, bad], TOOLS, jobs=1, progress=False)
        summary = summarise(results)

        assert summary.converted == 2
        assert summary.failed == 1
        assert summary.exit_code == 1
        assert good_a.dst.read_bytes() == b"converted"
        assert good_b.dst.read_bytes() == b"converted"
        bad_result = next(r for r in results if r.task == bad)
        assert bad_result.outcome is Outcome.FAILED
        assert "too long" in bad_result.error

    def test_no_partial_output_is_left_for_the_failing_source(
        self, tmp_path, monkeypatch, fake_ffmpeg
    ):
        bad_dir = tmp_path / "out" / "bad"
        _fail_only_for(monkeypatch, bad_dir, "path is too long (stubbed)")
        profile = _no_verification_profile()
        bad = Task(tmp_path / "gamma.src", bad_dir / "gamma.out")
        bad.src.write_bytes(b"data")

        run_batch(profile, [bad], TOOLS, jobs=1, progress=False)

        assert not bad.dst.exists()
        assert not bad_dir.exists()  # never even created: ensure_directory failed first

    def test_a_rerun_is_idempotent_for_the_files_that_did_convert(
        self, tmp_path, monkeypatch, fake_ffmpeg
    ):
        bad_dir = tmp_path / "out" / "bad"
        _fail_only_for(monkeypatch, bad_dir, "path is too long (stubbed)")
        profile = _no_verification_profile()
        good = make_task(tmp_path, "alpha")
        bad = Task(tmp_path / "gamma.src", bad_dir / "gamma.out")
        bad.src.write_bytes(b"data")
        run_batch(profile, [good, bad], TOOLS, jobs=1, progress=False)

        second = summarise(run_batch(profile, [good, bad], TOOLS, jobs=1, progress=False))

        assert second.converted == 0
        assert second.skipped == 1  # good.dst already exists, and overwrite defaults to False
        assert second.failed == 1
        assert second.exit_code == 1

    def test_a_genuine_programming_error_still_aborts_instead_of_being_counted(
        self, tmp_path, monkeypatch, fake_ffmpeg
    ):
        """The containment must be narrow: only the path-length OSError is
        caught. A bug unrelated to one file's directory (here simulated as a
        TypeError from ensure_directory) must still surface as a crash rather
        than being filed away as a FAILED conversion."""
        profile = _no_verification_profile()
        task = make_task(tmp_path, "alpha")

        def broken(_path: Path) -> None:
            raise TypeError("not an OSError -- a real bug")

        monkeypatch.setattr(batch, "ensure_directory", broken)

        with pytest.raises(TypeError, match="not an OSError"):
            run_batch(profile, [task], TOOLS, jobs=1, progress=False)
