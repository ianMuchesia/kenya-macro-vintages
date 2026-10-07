# Rules for coding agents in this repository

You may:
- edit anything outside core/ and tests/spec/
- add tests under tests/unit/
- write Dockerfiles, compose files, CI, Bicep, UI code and docs

You may not:
- edit core/ (the decision logic) or tests/spec/ (the specification)
- disable, skip, loosen or delete any test
- read .env, any secret, or anything under ~/.azure
- add a dependency without one line in the PR saying why
- call any paid API except through core/budget.py
- push to main, create tags, or deploy

Before proposing any change: run `make lint test` and include the output.
If the specification is unclear: stop and ask. Do not guess what correct means.
Data: never commit data; never use real personal data; synthetic only.