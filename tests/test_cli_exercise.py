"""`sentinel exercise generate` reads its epoch as `sentinel screen` reads
its start: an ISO-8601 time without a timezone is UTC, never a crash."""

from sentinel import cli


def generate(out, epoch: str) -> dict[str, str]:
    assert cli.main(["exercise", "generate", "--out", str(out), "--epoch", epoch]) == 0
    return {path.name: path.read_text() for path in sorted(out.iterdir())}


def test_an_epoch_without_a_timezone_is_read_as_utc(tmp_path, capsys):
    naive = generate(tmp_path / "naive", "2026-09-24T12:00:00")
    explicit = generate(tmp_path / "utc", "2026-09-24T12:00:00+00:00")
    assert naive and naive == explicit
    assert f"wrote {len(naive)} exercise CDMs to {tmp_path / 'naive'}" in capsys.readouterr().out

