from core.budget import Budget, BudgetExceeded

PRICES = {
    "paid-model": {"input_per_m": 1.00, "output_per_m": 2.00},
}


def fake_model():
    return {"input_tokens": 1000, "output_tokens": 1500}


def main():
    budget = Budget(
        usd_limit=0.01,
        token_limit=1_000_000,
        run_id="killswitch-demo",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )

    try:
        for call in range(1, 21):
            budget.precheck(
                model="paid-model", input_tokens=1000, max_output_tokens=2000
            )
            usage = fake_model()
            budget.charge(
                model="paid-model",
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
            )
            print(f"call {call}: allowed, total spent ${budget.usd_spent:.4f}")
    except BudgetExceeded as err:
        print(f"call {call}: BLOCKED, reason = {err.reason}")

    print()
    print("ledger:")
    for row in budget.ledger:
        print(row)


if __name__ == "__main__":
    main()
