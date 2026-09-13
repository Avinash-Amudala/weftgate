"""The self-test is itself a regression check; it must pass and be quiet on success."""

from weftgate import selftest


def test_selftest_passes(capsys):
    assert selftest.run(verbose=False) == 0
    out = capsys.readouterr().out
    assert "selftest ok" in out and "FAIL" not in out
