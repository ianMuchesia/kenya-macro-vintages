import pytest

from core.budget import Budget, BudgetExceeded

PRICES = {
    "paid-model": {"input_per_m": 1.00, "output_per_m": 2.00},
    "free-model": {"input_per_m": 0.0, "output_per_m": 0.0},
}


def test_unknown_model_is_blocked():
    budget = Budget(
        usd_limit=1.00,
        token_limit=10_000,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    with pytest.raises(BudgetExceeded) as err:
        budget.precheck(model="no-such-model", input_tokens=10, max_output_tokens=10)
    assert err.value.reason == "unknown_model"


def test_charge_without_precheck_is_an_error():
    budget = Budget(
        usd_limit=1.00,
        token_limit=10_000,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    with pytest.raises(RuntimeError):
        budget.charge(model="paid-model", input_tokens=10, output_tokens=10)


def test_charged_with_diff_prechecked_model():
    budget = Budget(
        usd_limit=1.00,
        token_limit=10_000,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    budget.precheck(model="free-model", input_tokens=10, max_output_tokens=10)
    with pytest.raises(RuntimeError):
        budget.charge(model="paid-model", input_tokens=10, output_tokens=10)


def test_missing_or_zero_max_output_tokens_is_refused():
    budget = Budget(
        usd_limit=1.00,
        token_limit=10_000,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    with pytest.raises(ValueError):
        budget.precheck(model="paid-model", input_tokens=10, max_output_tokens=None)
    with pytest.raises(ValueError):
        budget.precheck(model="paid-model", input_tokens=10, max_output_tokens=0)


def test_token_limit_blocks():
    budget = Budget(
        usd_limit=1.00,
        token_limit=100,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    with pytest.raises(BudgetExceeded) as err:
        budget.precheck(model="paid-model", input_tokens=60, max_output_tokens=60)
    assert err.value.reason == "token_limit"


def test_usd_limit_of_one_cent_blocks():
    budget = Budget(
        usd_limit=0.01,
        token_limit=100_000,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    with pytest.raises(BudgetExceeded) as err:
        budget.precheck(model="paid-model", input_tokens=5_000, max_output_tokens=5_000)
    assert err.value.reason == "usd_limit"


def test_second_call_is_blocked():
    budget = Budget(
        usd_limit=1.00,
        token_limit=100,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    budget.precheck(model="paid-model", input_tokens=30, max_output_tokens=30)
    budget.charge(model="paid-model", input_tokens=30, output_tokens=30)
    with pytest.raises(BudgetExceeded) as err:
        budget.precheck(model="paid-model", input_tokens=30, max_output_tokens=30)
    assert err.value.reason == "token_limit"


def test_exactly_at_the_limit_is_blocked():
    budget = Budget(
        usd_limit=1.00,
        token_limit=100,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    with pytest.raises(BudgetExceeded) as err:
        budget.precheck(model="paid-model", input_tokens=50, max_output_tokens=50)
    assert err.value.reason == "token_limit"


def test_blocked_call_writes_ledger_row():
    budget = Budget(
        usd_limit=1.00,
        token_limit=100,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    with pytest.raises(BudgetExceeded):
        budget.precheck(model="paid-model", input_tokens=60, max_output_tokens=60)
    row = budget.ledger[-1]
    assert row["status"] == "blocked"
    assert row["reason"] == "token_limit"


def test_allowed_call_records_cost():
    budget = Budget(
        usd_limit=1.00,
        token_limit=10_000,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    budget.precheck(model="paid-model", input_tokens=1_000, max_output_tokens=1_000)
    budget.charge(model="paid-model", input_tokens=1_000, output_tokens=1_000)
    row = budget.ledger[-1]
    assert row["status"] == "allowed"
    assert row["usd"] == pytest.approx(0.003)


def test_free_model_still_hits_token_limit():
    budget = Budget(
        usd_limit=1.00,
        token_limit=100,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    with pytest.raises(BudgetExceeded) as err:
        budget.precheck(model="free-model", input_tokens=60, max_output_tokens=60)
    assert err.value.reason == "token_limit"


def test_allowed_row_has_kes_and_timestamp():
    budget = Budget(
        usd_limit=1.00,
        token_limit=10_000,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )

    budget.precheck(model="paid-model", input_tokens=1_000, max_output_tokens=1_000)
    budget.charge(model="paid-model", input_tokens=1_000, output_tokens=1_000)
    row = budget.ledger[-1]

    assert row["kes"] == pytest.approx(row["usd"] * 130.0)

    assert row["kes_rate"] == 130.0

    assert row["kes_rate_date"] == "2026-09-29"
    assert row["timestamp"]


def test_blocked_and_allowed_rows_have_same_columns():
    budget = Budget(
        usd_limit=1.00,
        token_limit=100,
        run_id="test-1",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )
    budget.precheck(model="paid-model", input_tokens=30, max_output_tokens=30)
    budget.charge(model="paid-model", input_tokens=30, output_tokens=30)
    with pytest.raises(BudgetExceeded):
        budget.precheck(model="paid-model", input_tokens=30, max_output_tokens=30)
    allowed_row = budget.ledger[0]
    blocked_row = budget.ledger[1]
    assert set(blocked_row) == set(allowed_row)
    assert blocked_row["timestamp"]
    assert blocked_row["usd"] == 0.0
    assert blocked_row["kes"] == 0.0
