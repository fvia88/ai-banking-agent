import contextlib
import io
import json
from pathlib import Path

from subscriptions.cli import main

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "transactions.json"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def test_text_report_lists_fixture_subscriptions():
    code, out, _ = run([str(FIXTURE)])
    assert code == 0
    assert "StreamBox" in out and "CloudMusic" in out
    assert "Metro" not in out


def test_json_report_is_valid_and_uses_money_strings():
    code, out, _ = run([str(FIXTURE), "--json"])
    data = json.loads(out)
    assert code == 0
    assert [c["subscription_id"] for c in data["candidates"]] == ["sub_cloudmusic", "sub_streambox"]
    assert data["candidates"][1]["estimated_amount"] == "39.00"


def test_missing_file_returns_error_code():
    code, _, err = run(["does_not_exist.json"])
    assert code == 2
    assert "File not found" in err
