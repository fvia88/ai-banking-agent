import pytest
from agent import cli


def answers(monkeypatch, messages):
    iterator = iter(messages)
    monkeypatch.setattr("builtins.input", lambda prompt: next(iterator))


def test_interactive_three_turn_memory(monkeypatch, capsys):
    answers(monkeypatch, ["Transfer to Alice", "500", "Alice Chen", "quit"])
    actual = cli.process_turn
    turns = []
    def observe(chat, catalog):
        turn = actual(chat, catalog)
        turns.append(turn)
        return turn
    monkeypatch.setattr(cli, "process_turn", observe)
    cli.main(["--interactive"])
    assert [turn.state.awaiting for turn in turns] == ["amount", "recipient", None]
    assert not turns[0].result.proposals and not turns[1].result.proposals
    assert turns[2].result.proposals[0].arguments == {
        "source_account_id": "account_001", "recipient_id": "recipient_alice",
        "amount": "500.00", "currency": "CNY",
    }
    assert "Memory demo ended." in capsys.readouterr().out


@pytest.mark.parametrize("exception", [EOFError, KeyboardInterrupt])
def test_interactive_exit_without_traceback(monkeypatch, capsys, exception):
    def interrupted(prompt):
        raise exception()
    monkeypatch.setattr("builtins.input", interrupted)
    cli.main(["--interactive"])
    output = capsys.readouterr().out
    assert "Memory demo ended." in output and "Traceback" not in output


def test_blank_and_long_input_do_not_erase_pending_state(monkeypatch, capsys):
    answers(monkeypatch, ["", "Transfer to Alice", "x" * 4001, "500", "Alice Chen", "quit"])
    cli.main(["--interactive"])
    output = capsys.readouterr().out
    assert "Pending details were retained" in output
    assert '"recipient_id": "recipient_alice"' in output
    assert '"amount": "500.00"' in output


def test_interrupt_during_processing_exits_cleanly(monkeypatch, capsys):
    answers(monkeypatch, ["Transfer to Alice"])
    def interrupted(chat, catalog):
        raise KeyboardInterrupt()
    monkeypatch.setattr(cli, "process_turn", interrupted)
    cli.main(["--interactive"])
    assert "Memory demo ended." in capsys.readouterr().out


@pytest.mark.parametrize("extra", [["balance"], ["--clarify", "500"], ["--resolve-read"]])
def test_incompatible_interactive_options_are_rejected(extra):
    with pytest.raises(SystemExit) as error:
        cli.main(["--interactive", *extra])
    assert error.value.code == 2


def test_existing_single_message_read_still_works(capsys):
    cli.main(["What is my balance?", "--resolve-read"])
    assert "Verified balance: CNY 5000.00." in capsys.readouterr().out


def test_default_single_message_still_proposes_balance(capsys):
    cli.main([])
    assert '"tool": "get_balance"' in capsys.readouterr().out
