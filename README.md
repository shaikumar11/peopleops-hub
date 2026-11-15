# PeopleOps Hub
Employee Success (leave) and Finance (expense) request app with approval rules, ledger summary and API telemetry.

**Rules:** leave up to 2 days and expenses up to 1000 are auto approved; larger ones wait for an approver. No self approval, no double decisions, and leave is capped at a 20 day balance (checked again at approval).

**Stack:** Python, FastAPI, SQLite, vanilla JS dashboard, pytest with a 90% coverage gate in GitHub Actions.

**Telemetry:** `/metrics` reports count, average and p95 latency per route.

## Run
    pip install -r requirements.txt
    uvicorn app.main:app --reload     # open http://127.0.0.1:8000
    pytest --cov=app                  # run tests

Deploy on Render: build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
