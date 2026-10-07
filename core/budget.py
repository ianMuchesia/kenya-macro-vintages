from datetime import UTC, datetime


class BudgetExceeded(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class Budget:
    def __init__(self, usd_limit, token_limit, run_id, prices, kes_rate, kes_rate_date):
        self.usd_limit = usd_limit
        self.token_limit = token_limit
        self.run_id = run_id
        self.prices = prices
        self.kes_rate = kes_rate
        self.kes_rate_date = kes_rate_date

        self.tokens_spent = 0
        self.usd_spent = 0.0
        self.ledger = []
        self.prechecked_model = None

    def precheck(self, model, input_tokens, max_output_tokens):
        if not max_output_tokens:
            raise ValueError("max_output_tokens must be set and greater than 0")

        if model not in self.prices:
            self.block(model, "unknown_model", input_tokens, max_output_tokens)

        worst_case_tokens = input_tokens + max_output_tokens
        if self.tokens_spent + worst_case_tokens >= self.token_limit:
            self.block(model, "token_limit", input_tokens, max_output_tokens)

        price = self.prices[model]
        worst_case_usd = (
            input_tokens * price["input_per_m"] / 1_000_000
            + max_output_tokens * price["output_per_m"] / 1_000_000
        )
        if self.usd_spent + worst_case_usd >= self.usd_limit:
            self.block(model, "usd_limit", input_tokens, max_output_tokens)

        self.prechecked_model = model

    def charge(self, model, input_tokens, output_tokens):
        if self.prechecked_model is None:
            raise RuntimeError("charge() called without a passed precheck()")
        if self.prechecked_model != model:
            raise RuntimeError("charge() model does not match the prechecked model")

        price = self.prices[model]
        usd = (
            input_tokens * price["input_per_m"] / 1_000_000
            + output_tokens * price["output_per_m"] / 1_000_000
        )

        self.tokens_spent += input_tokens + output_tokens
        self.usd_spent += usd

        self.write_row(model, "allowed", None, input_tokens, output_tokens, usd)

        self.prechecked_model = None

    def write_row(self, model, status, reason, input_tokens, output_tokens, usd):
        self.ledger.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": self.run_id,
                "model": model,
                "status": status,
                "reason": reason,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "usd": usd,
                "kes": usd * self.kes_rate,
                "kes_rate": self.kes_rate,
                "kes_rate_date": self.kes_rate_date,
            }
        )

    def block(self, model, reason, input_tokens, output_tokens):
        self.write_row(model, "blocked", reason, input_tokens, output_tokens, 0.0)
        raise BudgetExceeded(reason)
