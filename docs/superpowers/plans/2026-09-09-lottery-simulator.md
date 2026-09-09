# Lottery Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, modular Python lottery simulator with Rule 1, exact probability analysis, finite-draw expectations, single-run traces, and multi-trial statistics.

**Architecture:** A rule protocol owns pity-state probability and transitions; the engine owns random sampling and streaming aggregation; the analyzer calls the same rule functions for exact results. A thin `argparse` CLI selects registered rules and formats structured results as text or JSON.

**Tech Stack:** Python 3.11+ standard library (`argparse`, `dataclasses`, `json`, `math`, `random`, `secrets`, `statistics`, `unittest`); no third-party dependencies.

**Spec:** `docs/superpowers/specs/2026-09-09-lottery-simulator-design.md`

## Global Constraints

- Rule 1 is 0.8% for pulls 1–64, rises by 5 percentage points on each pull 65–79, and is 100% on pull 80.
- A six-star resets pity; the next pull is pull 1.
- The engine must not contain Rule 1 probability constants.
- An explicitly supplied seed must reproduce results; an omitted seed must be generated and returned.
- `trials=1` returns draw records; `trials>1` retains aggregates only.
- `initial_pity` for Rule 1 is an integer from 0 through 79.
- Core functions return data and never print; only the CLI formats output.
- Keep the implementation dependency-free and avoid unrequested UI, persistence, concurrency, CSV, and configurable probability expressions.

## File Map

- `.gitignore`: Ignore Python bytecode and local virtual environments.
- `lottery_simulator/__init__.py`: Export the supported public Python API.
- `lottery_simulator/__main__.py`: Run the CLI with `python -m lottery_simulator`.
- `lottery_simulator/rules/base.py`: Define immutable pity state and the rule protocol.
- `lottery_simulator/rules/rule_1.py`: Implement Rule 1 and its state validation.
- `lottery_simulator/analysis.py`: Compute exact waiting-time and finite-draw metrics.
- `lottery_simulator/engine.py`: Sample draws and aggregate repeated trials.
- `lottery_simulator/cli.py`: Parse commands, register rules, and render text or JSON.
- `tests/test_rule_1.py`: Verify Rule 1 probabilities and state transitions.
- `tests/test_analysis.py`: Verify exact theory and finite-draw dynamic programming.
- `tests/test_engine.py`: Verify simulation, aggregation, validation, and reproducibility.
- `tests/test_cli.py`: Verify commands, formats, traces, and invalid arguments.
- `README.md`: Document the approved entry points and result semantics.

---

### Task 1: Rule protocol and Rule 1

**Files:**
- Create: `.gitignore`
- Create: `lottery_simulator/__init__.py`
- Create: `lottery_simulator/rules/__init__.py`
- Create: `lottery_simulator/rules/base.py`
- Create: `lottery_simulator/rules/rule_1.py`
- Create: `tests/__init__.py`
- Create: `tests/test_rule_1.py`

**Interfaces:**
- Consumes: None.
- Produces: `DrawState(misses_since_six_star: int = 0)`, `LotteryRule` protocol, and `Rule1` with `name`, `max_pity`, `probability(state)`, and `advance(state, is_six_star)`.

- [ ] **Step 1: Add the failing boundary and transition tests**

```python
# tests/test_rule_1.py
import unittest

from lottery_simulator.rules.base import DrawState
from lottery_simulator.rules.base import DrawState
from lottery_simulator.rules.rule_1 import Rule1


class Rule1Test(unittest.TestCase):
    def setUp(self):
        self.rule = Rule1()

    def test_probability_boundaries(self):
        expected = {0: 0.008, 63: 0.008, 64: 0.058, 78: 0.758, 79: 1.0}
        for misses, probability in expected.items():
            with self.subTest(misses=misses):
                self.assertAlmostEqual(
                    self.rule.probability(DrawState(misses)), probability
                )

    def test_six_star_resets_state(self):
        self.assertEqual(
            self.rule.advance(DrawState(64), True), DrawState(0)
        )

    def test_miss_advances_state(self):
        self.assertEqual(
            self.rule.advance(DrawState(63), False), DrawState(64)
        )

    def test_invalid_states_are_rejected(self):
        for misses in (-1, 80):
            with self.subTest(misses=misses):
                with self.assertRaises(ValueError):
                    self.rule.probability(DrawState(misses))

    def test_missing_guaranteed_pull_is_rejected(self):
        with self.assertRaises(ValueError):
            self.rule.advance(DrawState(79), False)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the missing package failure**

Run: `python -m unittest tests.test_rule_1 -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'lottery_simulator'`.

- [ ] **Step 3: Implement the minimal rule boundary**

```python
# lottery_simulator/rules/base.py
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DrawState:
    misses_since_six_star: int = 0


class LotteryRule(Protocol):
    name: str
    max_pity: int

    def probability(self, state: DrawState) -> float: ...

    def advance(self, state: DrawState, is_six_star: bool) -> DrawState: ...
```

```python
# lottery_simulator/rules/rule_1.py
from lottery_simulator.rules.base import DrawState


class Rule1:
    name = "rule1"
    max_pity = 80

    def _validate(self, state: DrawState) -> None:
        misses = state.misses_since_six_star
        if isinstance(misses, bool) or not isinstance(misses, int):
            raise TypeError("misses_since_six_star must be an integer")
        if not 0 <= misses < self.max_pity:
            raise ValueError("misses_since_six_star must be between 0 and 79")

    def probability(self, state: DrawState) -> float:
        self._validate(state)
        pull = state.misses_since_six_star + 1
        if pull == self.max_pity:
            return 1.0
        if pull >= 65:
            return 0.008 + 0.05 * (pull - 64)
        return 0.008

    def advance(self, state: DrawState, is_six_star: bool) -> DrawState:
        self._validate(state)
        if is_six_star:
            return DrawState(0)
        if state.misses_since_six_star == self.max_pity - 1:
            raise ValueError("the guaranteed pull cannot miss")
        return DrawState(state.misses_since_six_star + 1)
```

Create empty `lottery_simulator/rules/__init__.py` and `tests/__init__.py`. Export `DrawState`, `LotteryRule`, and `Rule1` from `lottery_simulator/__init__.py`. Add this ignore file:

```gitignore
__pycache__/
*.py[cod]
.venv/
```

- [ ] **Step 4: Run the focused tests**

Run: `python -m unittest tests.test_rule_1 -v`

Expected: 5 tests run and all report `ok`.

- [ ] **Step 5: Perform the required causal boundary check**

Temporarily change `if pull >= 65:` to `if pull > 65:`, run `python -m unittest tests.test_rule_1.Rule1Test.test_probability_boundaries -v`, and confirm it FAILS for `misses=64`. Restore `>=`, rerun the same command, and confirm it PASSES.

- [ ] **Step 6: Commit the rule module**

```bash
git add .gitignore lottery_simulator tests/test_rule_1.py tests/__init__.py
git commit -m "feat: add modular six-star pity rule"
```

---

### Task 2: Exact probability analysis

**Files:**
- Create: `lottery_simulator/analysis.py`
- Create: `tests/test_analysis.py`
- Modify: `lottery_simulator/__init__.py`

**Interfaces:**
- Consumes: `LotteryRule.probability(DrawState)` and `LotteryRule.advance(...)` from Task 1.
- Produces: `DistributionStats`, `waiting_time_distribution(rule, initial_pity=0)`, `distribution_stats(rule, initial_pity=0)`, and `expected_six_stars(rule, draws, initial_pity=0)`.

- [ ] **Step 1: Add failing exact-analysis tests**

```python
# tests/test_analysis.py
import unittest

from lottery_simulator.analysis import (
    distribution_stats,
    expected_six_stars,
    waiting_time_distribution,
)
from lottery_simulator.rules.rule_1 import Rule1


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.rule = Rule1()

    def test_distribution_is_complete(self):
        probabilities = waiting_time_distribution(self.rule)
        self.assertEqual(len(probabilities), 80)
        self.assertAlmostEqual(sum(probabilities), 1.0, places=12)
        self.assertAlmostEqual(probabilities[-1], 0.00007302369959649657)

    def test_rule_1_reference_statistics(self):
        stats = distribution_stats(self.rule)
        self.assertAlmostEqual(stats.mean, 53.32595362219928)
        self.assertAlmostEqual(stats.standard_deviation, 22.631871302420425)
        self.assertEqual(stats.median, 67)
        self.assertEqual(stats.mode, 68)
        self.assertEqual(stats.quantiles, {0.90: 72, 0.95: 73, 0.99: 75})
        self.assertAlmostEqual(stats.long_run_rate, 0.018752594788735404)

    def test_one_draw_expectation_is_its_probability(self):
        self.assertAlmostEqual(expected_six_stars(self.rule, 1), 0.008)
        self.assertAlmostEqual(
            expected_six_stars(self.rule, 1, initial_pity=64), 0.058
        )

    def test_eighty_draw_expectation_accounts_for_reset(self):
        value = expected_six_stars(self.rule, 80)
        self.assertGreater(value, 1.0)
        self.assertLess(value, 1.2)

    def test_invalid_analysis_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            expected_six_stars(self.rule, 0)
        with self.assertRaises(ValueError):
            waiting_time_distribution(self.rule, initial_pity=80)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `python -m unittest tests.test_analysis -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'lottery_simulator.analysis'`.

- [ ] **Step 3: Implement exact waiting-time statistics**

```python
# lottery_simulator/analysis.py
from dataclasses import dataclass
from math import sqrt

from lottery_simulator.rules.base import DrawState, LotteryRule


@dataclass(frozen=True, slots=True)
class DistributionStats:
    probabilities: tuple[float, ...]
    mean: float
    variance: float
    standard_deviation: float
    median: int
    mode: int
    quantiles: dict[float, int]
    long_run_rate: float


def _state(initial_pity: int, rule: LotteryRule) -> DrawState:
    state = DrawState(initial_pity)
    rule.probability(state)  # Reuse the rule's authoritative validation.
    return state


def waiting_time_distribution(
    rule: LotteryRule, initial_pity: int = 0
) -> tuple[float, ...]:
    state = _state(initial_pity, rule)
    survival = 1.0
    probabilities: list[float] = []
    for _ in range(rule.max_pity - initial_pity):
        probability = rule.probability(state)
        if not 0.0 <= probability <= 1.0:
            raise ValueError("rule returned a probability outside [0, 1]")
        probabilities.append(survival * probability)
        survival *= 1.0 - probability
        if probability == 1.0:
            break
        state = rule.advance(state, False)
    if abs(sum(probabilities) - 1.0) > 1e-12:
        raise ValueError("rule does not produce a complete waiting-time distribution")
    return tuple(probabilities)


def _quantile(probabilities: tuple[float, ...], level: float) -> int:
    cumulative = 0.0
    for pull, probability in enumerate(probabilities, start=1):
        cumulative += probability
        if cumulative >= level:
            return pull
    raise ValueError("incomplete probability distribution")


def distribution_stats(
    rule: LotteryRule, initial_pity: int = 0
) -> DistributionStats:
    probabilities = waiting_time_distribution(rule, initial_pity)
    mean = sum(pull * p for pull, p in enumerate(probabilities, start=1))
    second = sum(pull * pull * p for pull, p in enumerate(probabilities, start=1))
    variance = second - mean * mean
    return DistributionStats(
        probabilities=probabilities,
        mean=mean,
        variance=variance,
        standard_deviation=sqrt(variance),
        median=_quantile(probabilities, 0.5),
        mode=max(range(1, len(probabilities) + 1), key=lambda n: probabilities[n - 1]),
        quantiles={level: _quantile(probabilities, level) for level in (0.90, 0.95, 0.99)},
        long_run_rate=1.0 / mean if initial_pity == 0 else float("nan"),
    )
```

- [ ] **Step 4: Implement finite-draw expectation with state dynamic programming**

Add this to `lottery_simulator/analysis.py`:

```python
def expected_six_stars(
    rule: LotteryRule, draws: int, initial_pity: int = 0
) -> float:
    if isinstance(draws, bool) or not isinstance(draws, int) or draws <= 0:
        raise ValueError("draws must be a positive integer")
    initial = _state(initial_pity, rule)
    states = {initial: 1.0}
    expected = 0.0
    for _ in range(draws):
        next_states: dict[DrawState, float] = {}
        for state, mass in states.items():
            probability = rule.probability(state)
            success_mass = mass * probability
            expected += success_mass
            success_state = rule.advance(state, True)
            next_states[success_state] = next_states.get(success_state, 0.0) + success_mass
            if probability < 1.0:
                miss_state = rule.advance(state, False)
                next_states[miss_state] = next_states.get(miss_state, 0.0) + mass * (1.0 - probability)
        states = next_states
    return expected
```

Export the four public analysis names from `lottery_simulator/__init__.py`.

- [ ] **Step 5: Run the focused and complete tests**

Run: `python -m unittest tests.test_analysis -v`

Expected: 5 tests run and all report `ok`.

Run: `python -m unittest discover -v`

Expected: 10 tests run and all report `ok`.

- [ ] **Step 6: Commit exact analysis**

```bash
git add lottery_simulator/analysis.py lottery_simulator/__init__.py tests/test_analysis.py
git commit -m "feat: add exact lottery probability analysis"
```

---

### Task 3: Reproducible simulation engine

**Files:**
- Create: `lottery_simulator/engine.py`
- Create: `tests/test_engine.py`
- Modify: `lottery_simulator/__init__.py`

**Interfaces:**
- Consumes: `LotteryRule`, `DrawState`, and `distribution_stats`.
- Produces: `DrawRecord`, `SimulationResult`, and `simulate(rule, draws, trials=1, seed=None, initial_pity=0)`.

- [ ] **Step 1: Add failing engine tests**

```python
# tests/test_engine.py
import unittest

from lottery_simulator.engine import simulate
from lottery_simulator.rules.rule_1 import Rule1


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.rule = Rule1()

    def test_fixed_seed_is_reproducible(self):
        first = simulate(self.rule, draws=100, trials=1, seed=42)
        second = simulate(self.rule, draws=100, trials=1, seed=42)
        self.assertEqual(first, second)

    def test_single_trial_keeps_trace(self):
        result = simulate(self.rule, draws=3, trials=1, seed=42)
        self.assertEqual(len(result.records), 3)
        self.assertEqual(result.records[0].pity_position, 1)
        self.assertEqual(sum(result.count_distribution.values()), 1)

    def test_multiple_trials_only_keep_aggregates(self):
        result = simulate(self.rule, draws=100, trials=50, seed=42)
        self.assertEqual(result.records, ())
        self.assertEqual(sum(result.count_distribution.values()), 50)
        self.assertEqual(result.theoretical_expected_count > 0, True)

    def test_initial_pity_is_applied(self):
        result = simulate(self.rule, draws=1, trials=1, seed=1, initial_pity=79)
        self.assertTrue(result.records[0].is_six_star)
        self.assertEqual(result.records[0].probability, 1.0)
        self.assertEqual(result.records[0].state_after.misses_since_six_star, 0)

    def test_omitted_seed_is_returned(self):
        result = simulate(self.rule, draws=1)
        self.assertIsInstance(result.seed, int)

    def test_invalid_inputs_are_rejected(self):
        for draws, trials in ((0, 1), (1, 0), (True, 1)):
            with self.subTest(draws=draws, trials=trials):
                with self.assertRaises(ValueError):
                    simulate(self.rule, draws=draws, trials=trials)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `python -m unittest tests.test_engine -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'lottery_simulator.engine'`.

- [ ] **Step 3: Define structured result types and validation**

```python
# lottery_simulator/engine.py
from dataclasses import dataclass
import random
import secrets

from lottery_simulator.analysis import expected_six_stars
from lottery_simulator.rules.base import DrawState, LotteryRule


@dataclass(frozen=True, slots=True)
class DrawRecord:
    draw_index: int
    pity_position: int
    probability: float
    is_six_star: bool
    state_after: DrawState


@dataclass(frozen=True, slots=True)
class SimulationResult:
    rule_name: str
    draws: int
    trials: int
    seed: int
    initial_pity: int
    count_distribution: dict[int, int]
    mean_six_stars: float
    at_least_one_rate: float
    observed_mean_interval: float | None
    theoretical_expected_count: float
    records: tuple[DrawRecord, ...]


def _positive_integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
```

- [ ] **Step 4: Implement streaming simulation**

Add this to `lottery_simulator/engine.py`:

```python
def simulate(
    rule: LotteryRule,
    draws: int,
    trials: int = 1,
    seed: int | None = None,
    initial_pity: int = 0,
) -> SimulationResult:
    _positive_integer(draws, "draws")
    _positive_integer(trials, "trials")
    initial_state = DrawState(initial_pity)
    rule.probability(initial_state)
    actual_seed = secrets.randbits(64) if seed is None else seed
    if isinstance(actual_seed, bool) or not isinstance(actual_seed, int):
        raise ValueError("seed must be an integer")
    rng = random.Random(actual_seed)
    count_distribution: dict[int, int] = {}
    records: list[DrawRecord] = []
    total_six_stars = 0
    interval_sum = 0
    completed_intervals = 0

    for _trial in range(trials):
        state = initial_state
        six_stars = 0
        for draw_index in range(1, draws + 1):
            probability = rule.probability(state)
            if not 0.0 <= probability <= 1.0:
                raise ValueError("rule returned a probability outside [0, 1]")
            pity_position = state.misses_since_six_star + 1
            is_six_star = rng.random() < probability
            state_after = rule.advance(state, is_six_star)
            if is_six_star:
                six_stars += 1
                interval_sum += pity_position
                completed_intervals += 1
            if trials == 1:
                records.append(
                    DrawRecord(
                        draw_index, pity_position, probability, is_six_star, state_after
                    )
                )
            state = state_after
        total_six_stars += six_stars
        count_distribution[six_stars] = count_distribution.get(six_stars, 0) + 1

    return SimulationResult(
        rule_name=rule.name,
        draws=draws,
        trials=trials,
        seed=actual_seed,
        initial_pity=initial_pity,
        count_distribution=count_distribution,
        mean_six_stars=total_six_stars / trials,
        at_least_one_rate=(trials - count_distribution.get(0, 0)) / trials,
        observed_mean_interval=(
            interval_sum / completed_intervals if completed_intervals else None
        ),
        theoretical_expected_count=expected_six_stars(rule, draws, initial_pity),
        records=tuple(records),
    )
```

Export `DrawRecord`, `SimulationResult`, and `simulate` from `lottery_simulator/__init__.py`.

- [ ] **Step 5: Run the focused and complete tests**

Run: `python -m unittest tests.test_engine -v`

Expected: 6 tests run and all report `ok`.

Run: `python -m unittest discover -v`

Expected: 16 tests run and all report `ok`.

- [ ] **Step 6: Commit the engine**

```bash
git add lottery_simulator/engine.py lottery_simulator/__init__.py tests/test_engine.py
git commit -m "feat: add reproducible lottery simulation engine"
```

---

### Task 4: Command-line interface and output formats

**Files:**
- Create: `lottery_simulator/cli.py`
- Create: `lottery_simulator/__main__.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Rule1`, `distribution_stats`, and `simulate`.
- Produces: `main(argv=None, stdout=None) -> int`, `python -m lottery_simulator analyze`, and `python -m lottery_simulator simulate`.

- [ ] **Step 1: Add failing CLI behavior tests**

```python
# tests/test_cli.py
from io import StringIO
import json
import unittest

from lottery_simulator.cli import main


class CliTest(unittest.TestCase):
    def run_cli(self, *arguments):
        output = StringIO()
        code = main(list(arguments), stdout=output)
        return code, output.getvalue()

    def test_analyze_json_contains_reference_mean(self):
        code, output = self.run_cli("analyze", "--format", "json")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertAlmostEqual(payload["mean"], 53.32595362219928)
        self.assertEqual(payload["hard_pity"], 80)
        self.assertEqual(len(payload["probability_table"]), 80)
        self.assertEqual(payload["probability_table"][64]["conditional_probability"], 0.058)

    def test_simulate_json_contains_reproduction_parameters(self):
        code, output = self.run_cli(
            "simulate", "--draws", "10", "--trials", "2", "--seed", "42",
            "--initial-pity", "60", "--format", "json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["rule"], "rule1")
        self.assertEqual(payload["seed"], 42)
        self.assertEqual(payload["initial_pity"], 60)
        self.assertNotIn("records", payload)
        self.assertIn("mean_count_error", payload)
        self.assertEqual(sum(payload["count_distribution"].values()), 2)

    def test_trace_prints_each_draw(self):
        code, output = self.run_cli(
            "simulate", "--draws", "2", "--trials", "1", "--seed", "42", "--trace"
        )
        self.assertEqual(code, 0)
        self.assertIn("抽次", output)
        self.assertIn("保底位置", output)

    def test_trace_rejects_multiple_trials(self):
        with self.assertRaises(SystemExit):
            self.run_cli("simulate", "--draws", "2", "--trials", "2", "--trace")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `python -m unittest tests.test_cli -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'lottery_simulator.cli'`.

- [ ] **Step 3: Build the parser and rule registry**

Implement in `lottery_simulator/cli.py`:

```python
import argparse
from dataclasses import asdict
import json
import sys
from typing import TextIO

from lottery_simulator.analysis import distribution_stats
from lottery_simulator.engine import SimulationResult, simulate
from lottery_simulator.rules.rule_1 import Rule1


RULES = {"rule1": Rule1}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lottery_simulator")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze")
    analyze.add_argument("--rule", choices=RULES, default="rule1")
    analyze.add_argument("--format", choices=("text", "json"), default="text")
    simulation = commands.add_parser("simulate")
    simulation.add_argument("--rule", choices=RULES, default="rule1")
    simulation.add_argument("--draws", type=int, required=True)
    simulation.add_argument("--trials", type=int, default=1)
    simulation.add_argument("--seed", type=int)
    simulation.add_argument("--initial-pity", type=int, default=0)
    simulation.add_argument("--trace", action="store_true")
    simulation.add_argument("--format", choices=("text", "json"), default="text")
    return parser
```

- [ ] **Step 4: Add JSON-safe structured rendering and text summaries**

Add focused helpers in `lottery_simulator/cli.py`:

```python
def _analysis_payload(rule):
    stats = distribution_stats(rule)
    cumulative = 0.0
    table = []
    for pull, first_six_star_probability in enumerate(stats.probabilities, start=1):
        cumulative += first_six_star_probability
        table.append({
            "pull": pull,
            "conditional_probability": rule.probability(DrawState(pull - 1)),
            "first_six_star_probability": first_six_star_probability,
            "cumulative_probability": cumulative,
        })
    return {
        "rule": rule.name,
        "hard_pity": rule.max_pity,
        "probability_table": table,
        "mean": stats.mean,
        "variance": stats.variance,
        "standard_deviation": stats.standard_deviation,
        "median": stats.median,
        "mode": stats.mode,
        "quantiles": {str(level): pull for level, pull in stats.quantiles.items()},
        "long_run_rate": stats.long_run_rate,
    }


def _simulation_payload(result: SimulationResult, rule, include_records: bool):
    theoretical_mean_interval = distribution_stats(rule).mean
    mean_count_error = result.mean_six_stars - result.theoretical_expected_count
    payload = {
        "rule": result.rule_name,
        "draws": result.draws,
        "trials": result.trials,
        "seed": result.seed,
        "initial_pity": result.initial_pity,
        "count_distribution": result.count_distribution,
        "mean_six_stars": result.mean_six_stars,
        "at_least_one_rate": result.at_least_one_rate,
        "observed_mean_interval": result.observed_mean_interval,
        "theoretical_mean_interval": theoretical_mean_interval,
        "theoretical_expected_count": result.theoretical_expected_count,
        "mean_count_error": mean_count_error,
        "mean_count_relative_error": (
            mean_count_error / result.theoretical_expected_count
        ),
    }
    if include_records:
        payload["records"] = [asdict(record) for record in result.records]
    return payload


def _write_text_analysis(payload, output: TextIO) -> None:
    print(f"规则：{payload['rule']}", file=output)
    print(f"六星平均间隔：{payload['mean']:.5f} 抽", file=output)
    print(f"长期综合六星率：{payload['long_run_rate']:.5%}", file=output)
    print(f"标准差：{payload['standard_deviation']:.5f} 抽", file=output)
    print(f"中位数：第 {payload['median']} 抽", file=output)
    print(f"众数：第 {payload['mode']} 抽", file=output)
    print("抽次  条件六星概率  首次出六星概率  累计概率", file=output)
    for row in payload["probability_table"]:
        print(
            f"{row['pull']}  {row['conditional_probability']:.4%}  "
            f"{row['first_six_star_probability']:.6%}  "
            f"{row['cumulative_probability']:.6%}",
            file=output,
        )


def _write_text_simulation(payload, output: TextIO, trace: bool) -> None:
    print(f"规则：{payload['rule']}", file=output)
    print(f"每轮抽数：{payload['draws']}", file=output)
    print(f"实验轮数：{payload['trials']}", file=output)
    print(f"随机种子：{payload['seed']}", file=output)
    print(f"初始保底：{payload['initial_pity']}", file=output)
    print(f"平均六星数：{payload['mean_six_stars']:.6f}", file=output)
    print(f"至少一个六星：{payload['at_least_one_rate']:.4%}", file=output)
    print(f"理论六星期望：{payload['theoretical_expected_count']:.6f}", file=output)
    print(f"期望误差：{payload['mean_count_error']:+.6f}", file=output)
    print(f"期望相对误差：{payload['mean_count_relative_error']:+.4%}", file=output)
    print("六星数量分布：", file=output)
    for count, frequency in sorted(payload["count_distribution"].items()):
        print(f"  {count} 个：{frequency / payload['trials']:.4%}", file=output)
    observed = payload["observed_mean_interval"]
    if observed is not None:
        print(f"已完成周期平均间隔：{observed:.5f} 抽", file=output)
    print(
        f"完整周期理论平均间隔：{payload['theoretical_mean_interval']:.5f} 抽",
        file=output,
    )
    if trace:
        print("抽次  保底位置  六星概率  结果  抽后保底", file=output)
        for record in payload["records"]:
            result = "六星" if record["is_six_star"] else "未出"
            after = record["state_after"]["misses_since_six_star"]
            print(
                f"{record['draw_index']}  {record['pity_position']}  "
                f"{record['probability']:.1%}  {result}  {after}",
                file=output,
            )
```

- [ ] **Step 5: Wire command dispatch and module execution**

Complete `lottery_simulator/cli.py`:

```python
def main(argv=None, stdout=None) -> int:
    output = sys.stdout if stdout is None else stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    rule = RULES[args.rule]()
    if args.command == "analyze":
        payload = _analysis_payload(rule)
        if args.format == "json":
            json.dump(payload, output, ensure_ascii=False, indent=2)
            print(file=output)
        else:
            _write_text_analysis(payload, output)
        return 0
    if args.trace and args.trials != 1:
        parser.error("--trace requires --trials 1")
    try:
        result = simulate(
            rule, args.draws, args.trials, args.seed, args.initial_pity
        )
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    payload = _simulation_payload(result, rule, include_records=args.trace)
    if args.format == "json":
        json.dump(payload, output, ensure_ascii=False, indent=2)
        print(file=output)
    else:
        _write_text_simulation(payload, output, args.trace)
    return 0
```

```python
# lottery_simulator/__main__.py
from lottery_simulator.cli import main

raise SystemExit(main())
```

- [ ] **Step 6: Run CLI tests and smoke commands**

Run: `python -m unittest tests.test_cli -v`

Expected: 4 tests run and all report `ok`.

Run: `python -m lottery_simulator analyze --format json`

Expected: exit 0 and JSON with `"mean": 53.32595362219928`, an 80-row `probability_table`, and `"hard_pity": 80`.

Run: `python -m lottery_simulator simulate --draws 3 --trials 1 --seed 42 --initial-pity 78 --trace`

Expected: exit 0, a three-row trace, the first row at pity position 79, and reproducibility fields in the header.

- [ ] **Step 7: Commit the CLI**

```bash
git add lottery_simulator/cli.py lottery_simulator/__main__.py tests/test_cli.py
git commit -m "feat: add lottery simulator command line interface"
```

---

### Task 5: Documentation and end-to-end verification

**Files:**
- Create: `README.md`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: All public commands and result semantics from Tasks 1–4.
- Produces: User-facing setup, command examples, parameter reference, and a subprocess smoke check for the real module entry point.

- [ ] **Step 1: Add an end-to-end module invocation test**

Add to `tests/test_cli.py`:

```python
import subprocess
import sys


    def test_real_module_entry_point_returns_json(self):
        completed = subprocess.run(
            [
                sys.executable, "-m", "lottery_simulator", "simulate",
                "--draws", "1", "--trials", "1", "--seed", "7",
                "--format", "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["seed"], 7)
        self.assertEqual(payload["draws"], 1)
```

- [ ] **Step 2: Run the end-to-end test**

Run: `python -m unittest tests.test_cli.CliTest.test_real_module_entry_point_returns_json -v`

Expected: PASS. This test is added after the entry point exists, so its role is a retained deployment-path check rather than the initial red test.

- [ ] **Step 3: Write concise usage documentation**

Create `README.md` with these exact sections and executable examples:

```markdown
# 抽奖模拟器

一个无第三方依赖的 Python 3.11+ 六星动态保底模拟器。

## 精确分析

`python -m lottery_simulator analyze`

## 批量模拟

`python -m lottery_simulator simulate --draws 100 --trials 100000 --seed 42`

## 单轮跟踪

`python -m lottery_simulator simulate --draws 30 --trials 1 --initial-pity 60 --seed 123 --trace`

## 参数

- `--rule`：规则模块，默认 `rule1`。
- `--draws`：每轮抽数，必填正整数。
- `--trials`：实验轮数，默认 1。
- `--seed`：整数随机种子；省略时程序生成并显示实际种子。
- `--initial-pity`：开始前连续未出六星次数，规则 1 接受 0–79。
- `--trace`：显示逐抽详情，仅可用于一轮实验。
- `--format`：`text` 或 `json`。

## 结果含义

`analyze` 是由概率公式计算的精确理论结果。`simulate` 是伪随机实验；指定相同参数和种子可复现。长期综合六星率为平均完整保底周期的倒数；有限抽数内的理论六星数量由状态动态规划计算。

批量模拟中的“期望误差”比较模拟平均六星数和相同有限抽数下的精确期望，可以用于检查抽样收敛，但单次小样本偏差不能证明实现错误。“已完成周期平均间隔”忽略模拟结束时尚未完成的周期，短模拟会有截尾偏差，不能单独用于验证规则。

## 测试

`python -m unittest discover -v`
```

- [ ] **Step 4: Run the full suite and inspect actual load path**

Run: `python -m unittest discover -v`

Expected: 21 tests run and all report `ok`.

Run: `python -c "import lottery_simulator; print(lottery_simulator.__file__)"`

Expected: the printed path starts with `/home/qykj/202607/test/lottery_simulator/lottery_simulator/`, proving the new source tree is what Python loads.

- [ ] **Step 5: Run behavior-level acceptance checks**

Run: `python -m lottery_simulator analyze`

Expected: text reports mean `53.32595`, long-run rate about `1.87526%`, median 67, and mode 68.

Run: `python -m lottery_simulator simulate --draws 30 --trials 1 --initial-pity 60 --seed 123 --trace`

Expected: 30 trace rows; each success resets the next pity position to 1.

Run: `python -m lottery_simulator simulate --draws 100 --trials 10000 --seed 42 --format json`

Expected: valid JSON, no `records` key, count-distribution values sum to 10,000, and reported seed equals 42.

- [ ] **Step 6: Commit documentation and final verification evidence**

```bash
git add README.md tests/test_cli.py
git commit -m "docs: add lottery simulator usage and smoke test"
git status --short
```

Expected: commit succeeds and `git status --short` prints nothing.
