import pytest

from cleansweep.agents.budgets import Budget, BudgetExhausted, RunBudget, parse_budget


def test_parse_budget():
    assert parse_budget("llm=150,minutes=60,tests=80") == {
        "llm_calls": 150,
        "minutes": 60.0,
        "test_runs": 80,
    }
    for bad in ("llm", "cost=3", "llm=lots", "tests=0"):
        with pytest.raises(ValueError):
            parse_budget(bad)


def test_an_agent_budget_stops_at_its_limit():
    budget = Budget(steps=2, llm_calls=0)
    budget.charge_step()
    budget.charge_step()
    with pytest.raises(BudgetExhausted, match="step budget"):
        budget.charge_step()
    assert budget.summary()["steps"] == 2


def test_the_run_budget_counts_llm_calls():
    run = RunBudget(llm_calls=1)
    run.take_llm_call()
    with pytest.raises(BudgetExhausted):
        run.take_llm_call()
    assert not run.out_of_time() and run.out_of_tests(5) is False
    assert RunBudget(test_runs=3).out_of_tests(3)
