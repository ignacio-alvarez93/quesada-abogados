"""FCP-10B-02: Budgets and estimated accounting with evidence.

Executions, receipts and tariffs are synthetic explicit Host values in a
fictitious currency setting; nothing is priced by default, charged, sent to a
provider or written to any ledger. Reservations are the real FCP-10A-01
`AdvisoryReservation` and usage limits the real contract `QuotaLimit`.
Nothing here is skipped.
"""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import decimal
import json
import socket
import subprocess
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_resource_quota_budget as bg
from scripts.ai import fabric_resource_quota_contract as qc
from scripts.ai import fabric_scheduler_contract as sc
from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_pipeline as rp

MODULE_PATH = Path(bg.__file__)
TEST_PATH = Path(__file__).resolve()
AS_OF = "2026-10-31T12:00:00Z"
INCURRED = "2026-10-31T11:00:00Z"
RECORDED = "2026-10-31T11:05:00Z"
TARIFF_FROM = "2026-01-01T00:00:00Z"
DAY = qc.QuotaWindow(qc.WINDOW_ROLLING, 86400)
IN, OUT, TOTAL, SECS = qc.UNIT_INPUT_TOKENS, qc.UNIT_OUTPUT_TOKENS, qc.UNIT_TOTAL_TOKENS, qc.UNIT_WALL_CLOCK_SECONDS
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "reservation_held",
             "quota_authority", "purchase_allowed", "remote_api_allowed", "charge_made", "provider_api_called",
             "ledger_written")


def _module_code() -> str:
    """The module without its docstring and comments."""
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


def usage_limit(limit_id="tok", maximum=10_000, unit=TOTAL, scope=qc.SCOPE_GLOBAL, window=DAY, **kw):
    return qc.QuotaLimit(limit_id=limit_id, scope=scope, unit=unit, maximum=maximum, window=window, **kw)


def cost_limit(limit_id="money", maximum=D("10.00"), scope=qc.SCOPE_GLOBAL, window=DAY, **kw):
    return bg.CostLimit(limit_id=limit_id, scope=scope, maximum=maximum, window=window, **kw)


def policy(limits=None, currency="EUR", granularity=D("0.01"), **kw):
    limits = limits if limits is not None else (usage_limit(), cost_limit())
    return bg.BudgetPolicy(policy_id="pol", currency=currency, granularity=granularity, limits=limits, **kw)


def execution(eid="e1", provider="alpha", incurred=INCURRED, resource=None):
    return bg.BudgetExecution(execution_id=eid, provider_id=provider, incurred_at_utc=incurred, resource_id=resource)


def qty(unit, low, high=None):
    return bg.UsageQuantity(unit=unit, minimum=low, maximum=low if high is None else high)


def receipt(rid, eid, *quantities, basis=bg.BASIS_OBSERVED, reliability=qc.RELIABILITY_CALLER_OBSERVED,
            recorded=RECORDED):
    return bg.UsageReceipt(receipt_id=rid, execution_id=eid, basis=basis, reliability=reliability,
                           recorded_at_utc=recorded, quantities=tuple(quantities))


def tokens(rid="r1", eid="e1", inp=1000, out=500, **kw):
    return receipt(rid, eid, qty(IN, inp), qty(OUT, out), qty(TOTAL, inp + out), **kw)


def tariff(tid, unit, rate, per=1_000_000, provider="alpha", currency="EUR", start=TARIFF_FROM, until=None):
    return bg.Tariff(tariff_id=tid, provider_id=provider, unit=unit, rate=rate, per_quantity=per, currency=currency,
                     effective_from_utc=start, effective_until_utc=until)


TARIFFS = (tariff("t-in", IN, D("3")), tariff("t-out", OUT, D("15")))


def reservation(*amounts, provider="alpha", resource=None):
    return qc.AdvisoryReservation(reservation_id="next", provider_id=provider, amounts=tuple(amounts),
                                  resource_id=resource)


def request(**kw):
    fields = dict(request_id="req", as_of_utc=AS_OF, policy=policy(), executions=(execution(),),
                  receipts=(tokens(),), tariffs=TARIFFS)
    fields.update(kw)
    return bg.BudgetRequest(**fields)


def evaluate(**kw):
    return bg.evaluate_budget(request(**kw))


class BudgetTestBase(unittest.TestCase):
    def assertRefused(self, result, *codes):
        self.assertEqual(result.verdict, bg.REFUSE)
        for code in codes:
            self.assertIn(code, result.request_reasons)
        self.assertEqual((result.accounts, result.request_id, result.currency), ((), None, None))

    def account(self, result, limit_id):
        found = result.account(limit_id)
        self.assertIsNotNone(found, limit_id)
        return found


class AccountingTests(BudgetTestBase):
    def test_observed_tokens_and_cost_are_accounted_exactly_and_ready(self):
        result = evaluate()
        self.assertEqual(result.verdict, bg.READY)
        tok, money = self.account(result, "tok"), self.account(result, "money")
        self.assertEqual((tok.observed, tok.accounted, tok.remaining, tok.uncertainty), (1500, 1500, 8500, 0))
        # 1000 * 3/1M + 500 * 15/1M = 0.0105 exactly, rounded UP to 0.02.
        self.assertEqual((money.observed, money.accounted, money.remaining), (D("0.02"), D("0.02"), D("9.98")))
        self.assertEqual(result.evidence_ids, ("r1",))
        self.assertEqual(tok.execution_ids, ("e1",))
        self.assertFalse(result.over_budget)

    def test_estimates_round_low_down_and_high_up_and_report_uncertainty(self):
        est = receipt("r1", "e1", qty(IN, 1000, 2000), qty(OUT, 100, 300), qty(TOTAL, 1100, 2300),
                      basis=bg.BASIS_ESTIMATED)
        money = self.account(evaluate(receipts=(est,)), "money")
        # low 0.003 + 0.0015 = 0.0045 -> 0.00 ; high 0.006 + 0.0045 = 0.0105 -> 0.02
        self.assertEqual((money.observed, money.estimated_low, money.estimated_high), (D("0.00"), D("0.00"),
                                                                                       D("0.02")))
        self.assertEqual((money.accounted, money.uncertainty), (D("0.02"), D("0.02")))
        tok = self.account(evaluate(receipts=(est,)), "tok")
        self.assertEqual((tok.estimated_low, tok.estimated_high, tok.uncertainty, tok.accounted),
                         (1100, 2300, 1200, 2300))

    def test_non_terminating_division_is_bounded_in_the_conservative_direction(self):
        tariffs = (tariff("t-sec", SECS, D("1"), per=3),)
        lim = (cost_limit(),)
        obs = receipt("r1", "e1", qty(SECS, 1))
        est = receipt("r2", "e2", qty(SECS, 1, 2), basis=bg.BASIS_ESTIMATED)
        result = evaluate(policy=policy(limits=lim), executions=(execution(), execution("e2")), receipts=(obs, est),
                          tariffs=tariffs)
        money = self.account(result, "money")
        # 1/3 -> 0.34 (up); estimate 1/3..2/3 -> 0.33 (down) .. 0.67 (up)
        self.assertEqual((money.observed, money.estimated_low, money.estimated_high), (D("0.34"), D("0.33"),
                                                                                       D("0.67")))
        self.assertEqual(money.accounted, D("1.01"))
        self.assertEqual(result.verdict, bg.READY)

    def test_granularity_is_the_rounding_quantum_of_every_money_amount(self):
        for granularity, expected in ((D("1"), D("1")), (D("0.0001"), D("0.0105")), (D("0.001"), D("0.011"))):
            lim = (cost_limit(maximum=D("10")),)
            money = self.account(evaluate(policy=policy(limits=lim, granularity=granularity)), "money")
            self.assertEqual(money.observed, expected)
            self.assertEqual(money.observed.as_tuple().exponent, granularity.as_tuple().exponent)
            self.assertEqual(money.maximum.as_tuple().exponent, granularity.as_tuple().exponent)

    def test_thread_decimal_context_is_neither_used_nor_changed(self):
        baseline = bg.canonical_json(evaluate())
        with decimal.localcontext() as ctx:
            ctx.prec, ctx.rounding = 2, decimal.ROUND_DOWN
            ctx.traps[decimal.Inexact] = True
            ctx.traps[decimal.Rounded] = True
            self.assertEqual(bg.canonical_json(evaluate()), baseline)
            self.assertEqual((ctx.prec, ctx.rounding), (2, decimal.ROUND_DOWN))

    def test_large_totals_stay_exact_beyond_default_decimal_precision(self):
        lim = (cost_limit(maximum=D("1000000000000.00")),)
        execs = tuple(execution(f"e{i}") for i in range(100))
        receipts = tuple(receipt(f"r{i}", f"e{i}", qty(TOTAL, 1_000_000_000)) for i in range(100))
        tariffs = (tariff("t-total", TOTAL, D("999999999999.99999999"), per=1),)
        money = self.account(evaluate(policy=policy(limits=lim, granularity=D("0.00000001")), executions=execs,
                                      receipts=receipts, tariffs=tariffs), "money")
        # 31 significant digits: the default 28-digit context would round.
        self.assertEqual(money.accounted, D("99999999999999999999000.00000000"))
        self.assertEqual(len(money.accounted.as_tuple().digits), 31)
        self.assertTrue(money.over_budget)


class MoneyValidationTests(BudgetTestBase):
    def test_float_int_subclass_and_non_finite_rates_are_refused(self):
        class Sub(D):
            pass
        for rate in (0.000003, 3, "3", D("NaN"), D("Infinity"), D("-1"), D("-0"), Sub("3"), D(0.1), None, True):
            result = evaluate(tariffs=(tariff("t-in", IN, rate), tariff("t-out", OUT, D("15"))))
            self.assertRefused(result, bg.TARIFF_RATE_INVALID)

    def test_zero_rate_is_an_explicit_free_tariff_not_a_missing_one(self):
        receipts = (receipt("r1", "e1", qty(IN, 1000), qty(OUT, 500), qty(SECS, 30)),)
        missing = evaluate(receipts=receipts)
        self.assertIn(bg.TARIFF_MISSING, self.account(missing, "money").reasons)
        free = evaluate(receipts=receipts, tariffs=TARIFFS + (tariff("t-sec", SECS, D("0")),),
                        policy=policy(limits=(cost_limit(),)))
        self.assertEqual(self.account(free, "money").accounted, D("0.02"))
        self.assertEqual(free.verdict, bg.READY)

    def test_granularity_must_be_a_canonical_power_of_ten(self):
        for granularity in (D("0.010"), D("0.05"), D("10"), D("1E+1"), D("1E-9"), 0.01, 1, D("-0.01"), D("NaN")):
            self.assertRefused(evaluate(policy=policy(granularity=granularity)), bg.GRANULARITY_INVALID)
        self.assertEqual(evaluate(policy=policy(granularity=D("1E-8"), limits=(cost_limit(),))).verdict, bg.READY)

    def test_cost_maximum_must_be_positive_exact_decimal_on_the_granularity(self):
        for maximum in (D("10.005"), D("0"), 10, 10.0, D("-1"), D("1E+13"), D("Infinity")):
            self.assertRefused(evaluate(policy=policy(limits=(cost_limit(maximum=maximum),))),
                               bg.COST_MAXIMUM_INVALID)
        ok = evaluate(policy=policy(limits=(cost_limit(maximum=D("10.0")),)))
        self.assertEqual(self.account(ok, "money").maximum, D("10.00"))

    def test_currency_is_validated_and_never_converted(self):
        for currency in ("eur", "EURO", "E1R", None, ""):
            self.assertRefused(evaluate(policy=policy(currency=currency)), bg.CURRENCY_INVALID)
        foreign = (tariff("t-in", IN, D("3"), currency="USD"), tariff("t-out", OUT, D("15")))
        self.assertRefused(evaluate(tariffs=foreign), bg.TARIFF_CURRENCY_MISMATCH)

    def test_tariff_fields_and_periods_are_validated(self):
        self.assertRefused(evaluate(tariffs=(tariff("t-in", IN, D("3"), per=0),)), bg.TARIFF_PER_QUANTITY_INVALID)
        self.assertRefused(evaluate(tariffs=(tariff("t-in", qc.UNIT_CONCURRENT_EXECUTIONS, D("3")),)),
                           bg.TARIFF_UNIT_INVALID)
        self.assertRefused(evaluate(tariffs=(tariff("t-in", bg.UNIT_COST, D("3")),)), bg.TARIFF_UNIT_INVALID)
        self.assertRefused(evaluate(tariffs=(tariff("t-in", IN, D("3"), until=TARIFF_FROM),)),
                           bg.TARIFF_PERIOD_INVALID)
        self.assertRefused(evaluate(tariffs=(tariff("t-in", IN, D("3"), start="2026-01-01T00:00:00+01:00"),)),
                           bg.TARIFF_PERIOD_INVALID)
        self.assertRefused(evaluate(tariffs=(tariff("t-in", IN, D("3"), provider="Alpha"),)),
                           bg.TARIFF_PROVIDER_INVALID)
        self.assertRefused(evaluate(tariffs=[tariff("t-in", IN, D("3"))]), bg.TARIFFS_MALFORMED)


class TariffTests(BudgetTestBase):
    def test_no_price_is_ever_invented_without_host_tariffs(self):
        result = evaluate(tariffs=())
        money = self.account(result, "money")
        self.assertEqual(money.verdict, bg.UNKNOWN)
        self.assertIn(bg.TARIFF_MISSING, money.reasons)
        self.assertIsNone(money.accounted)
        self.assertEqual(self.account(result, "tok").verdict, bg.READY)
        self.assertEqual(result.verdict, bg.UNKNOWN)

    def test_tariffed_unit_missing_from_the_receipt_is_usage_unknown(self):
        only_input = (receipt("r1", "e1", qty(IN, 1000)),)
        money = self.account(evaluate(receipts=only_input), "money")
        self.assertIn(bg.USAGE_UNKNOWN, money.reasons)
        self.assertNotIn(bg.TARIFF_MISSING, money.reasons)

    def test_total_tokens_report_is_covered_by_tariffed_parts_not_priced_twice(self):
        with_total = self.account(evaluate(), "money")
        without_total = self.account(evaluate(receipts=(receipt("r1", "e1", qty(IN, 1000), qty(OUT, 500)),)),
                                     "money")
        self.assertEqual(with_total.accounted, without_total.accounted)
        total_only = (tariff("t-total", TOTAL, D("10")),)
        priced = self.account(evaluate(tariffs=total_only, receipts=(receipt("r1", "e1", qty(TOTAL, 1500)),)),
                              "money")
        self.assertEqual(priced.accounted, D("0.02"))
        self.assertIn(bg.TARIFF_MISSING, self.account(evaluate(tariffs=total_only), "money").reasons)

    def test_total_and_part_tariffs_of_one_provider_overlapping_are_double_counting(self):
        both = TARIFFS + (tariff("t-total", TOTAL, D("10")),)
        self.assertRefused(evaluate(tariffs=both), bg.TARIFF_DOUBLE_COUNTING)
        other_provider = TARIFFS + (tariff("t-total", TOTAL, D("10"), provider="beta"),)
        self.assertEqual(evaluate(tariffs=other_provider).verdict, bg.READY)
        sequential = (tariff("t-total", TOTAL, D("10"), until="2026-06-01T00:00:00Z"),
                      tariff("t-in", IN, D("3"), start="2026-06-01T00:00:00Z"),
                      tariff("t-out", OUT, D("15"), start="2026-06-01T00:00:00Z"))
        self.assertEqual(evaluate(tariffs=sequential).verdict, bg.READY)

    def test_overlapping_tariffs_for_one_unit_are_ambiguous(self):
        overlapping = TARIFFS + (tariff("t-in2", IN, D("4"), start="2026-05-01T00:00:00Z"),)
        self.assertRefused(evaluate(tariffs=overlapping), bg.TARIFF_AMBIGUOUS)

    def test_the_tariff_in_force_at_the_execution_instant_prices_it(self):
        change = "2026-10-31T10:30:00Z"
        tariffs = (tariff("t-old", SECS, D("1"), per=1, until=change), tariff("t-new", SECS, D("2"), per=1,
                                                                               start=change))
        execs = (execution("e1", incurred="2026-10-31T10:00:00Z"), execution("e2", incurred="2026-10-31T11:00:00Z"))
        receipts = (receipt("r1", "e1", qty(SECS, 10)), receipt("r2", "e2", qty(SECS, 10)))
        money = self.account(evaluate(policy=policy(limits=(cost_limit(maximum=D("100.00")),)), executions=execs,
                                      receipts=receipts, tariffs=tariffs), "money")
        self.assertEqual(money.accounted, D("30.00"))
        later = (tariff("t-in", IN, D("3"), start="2026-10-31T11:30:00Z"),
                 tariff("t-out", OUT, D("15"), start="2026-10-31T11:30:00Z"))
        early = evaluate(policy=policy(limits=(cost_limit(),)), tariffs=later)
        self.assertIn(bg.TARIFF_MISSING, self.account(early, "money").reasons)


class DoubleCountingTests(BudgetTestBase):
    def test_identical_observed_receipts_of_one_execution_are_counted_once(self):
        result = evaluate(receipts=(tokens("r1"), tokens("r2")))
        tok = self.account(result, "tok")
        self.assertEqual(tok.accounted, 1500)
        self.assertEqual(tok.evidence_ids, ("r1", "r2"))
        self.assertEqual(self.account(result, "money").accounted, D("0.02"))
        self.assertEqual(result.verdict, bg.READY)

    def test_differing_observed_receipts_of_one_execution_are_contradictory(self):
        result = evaluate(receipts=(tokens("r1"), tokens("r2", inp=2000)))
        tok = self.account(result, "tok")
        self.assertEqual(tok.verdict, bg.UNKNOWN)
        self.assertIn(bg.EVIDENCE_CONTRADICTORY, tok.reasons)
        self.assertIsNone(tok.accounted)

    def test_observed_supersedes_estimated_per_unit_and_estimates_widen(self):
        est = receipt("r0", "e1", qty(IN, 5000, 9000), qty(OUT, 100, 900), qty(TOTAL, 5100, 9900),
                      basis=bg.BASIS_ESTIMATED)
        partial = receipt("r1", "e1", qty(IN, 1000))
        tok = self.account(evaluate(receipts=(est, tokens())), "tok")
        self.assertEqual((tok.observed, tok.estimated_high, tok.accounted), (1500, 0, 1500))
        in_limit = usage_limit("in", unit=IN, maximum=100_000)
        out_limit = usage_limit("out", unit=OUT, maximum=100_000)
        mixed = evaluate(receipts=(est, partial), policy=policy(limits=(in_limit, out_limit)))
        self.assertEqual(self.account(mixed, "in").observed, 1000)
        self.assertEqual((self.account(mixed, "out").estimated_low, self.account(mixed, "out").estimated_high),
                         (100, 900))
        second = receipt("r2", "e1", qty(OUT, 50, 600), basis=bg.BASIS_ESTIMATED)
        widened = self.account(evaluate(receipts=(est, second), policy=policy(limits=(out_limit,))), "out")
        self.assertEqual((widened.estimated_low, widened.estimated_high), (50, 900))

    def test_an_execution_is_counted_in_every_scope_but_once_per_budget(self):
        limits = (usage_limit("all"), usage_limit("alpha", scope=qc.SCOPE_PROVIDER, provider_id="alpha"),
                  usage_limit("beta", scope=qc.SCOPE_PROVIDER, provider_id="beta"))
        execs = (execution("e1"), execution("e2", provider="beta"))
        result = evaluate(policy=policy(limits=limits), executions=execs,
                          receipts=(tokens("r1"), tokens("r1b"), tokens("r2", "e2", inp=10, out=10)))
        self.assertEqual(self.account(result, "all").accounted, 1520)
        self.assertEqual(self.account(result, "alpha").accounted, 1500)
        self.assertEqual(self.account(result, "beta").accounted, 20)
        self.assertEqual(self.account(result, "beta").execution_ids, ("e2",))

    def test_duplicate_execution_ids_are_refused(self):
        self.assertRefused(evaluate(executions=(execution(), execution(provider="beta"))), bg.EXECUTION_DUPLICATE)

    def test_receipt_for_an_undeclared_execution_is_refused(self):
        self.assertRefused(evaluate(receipts=(tokens(), tokens("r2", "ghost"))), bg.RECEIPT_EXECUTION_UNDECLARED)

    def test_duplicate_receipt_and_cross_namespace_ids_are_refused(self):
        self.assertRefused(evaluate(receipts=(tokens("r1"), tokens("r1"))), bg.ID_DUPLICATE)
        self.assertRefused(evaluate(receipts=(tokens("t-in"),)), bg.ID_DUPLICATE)
        self.assertRefused(evaluate(request_id="pol"), bg.ID_DUPLICATE)

    def test_total_below_its_parts_is_contradictory(self):
        bad = receipt("r1", "e1", qty(IN, 1000), qty(OUT, 500), qty(TOTAL, 1200))
        self.assertIn(bg.EVIDENCE_CONTRADICTORY, self.account(evaluate(receipts=(bad,)), "tok").reasons)


class EvidenceTests(BudgetTestBase):
    def test_execution_without_receipt_is_usage_unknown_in_its_scopes_only(self):
        limits = (usage_limit("all"), usage_limit("beta", scope=qc.SCOPE_PROVIDER, provider_id="beta"))
        result = evaluate(policy=policy(limits=limits), executions=(execution("e1"), execution("e2", "beta")),
                          receipts=(tokens(),))
        self.assertIn(bg.USAGE_UNKNOWN, self.account(result, "all").reasons)
        self.assertIn(bg.USAGE_UNKNOWN, self.account(result, "beta").reasons)
        alpha = evaluate(policy=policy(limits=(usage_limit("alpha", scope=qc.SCOPE_PROVIDER, provider_id="alpha"),)),
                         executions=(execution("e1"), execution("e2", "beta")), receipts=(tokens(),))
        self.assertEqual(alpha.verdict, bg.READY)

    def test_receipt_lacking_the_budget_unit_is_usage_unknown(self):
        secs = usage_limit("secs", unit=SECS, maximum=3600)
        result = evaluate(policy=policy(limits=(secs,)))
        self.assertIn(bg.USAGE_UNKNOWN, self.account(result, "secs").reasons)
        self.assertEqual(result.verdict, bg.UNKNOWN)

    def test_no_executions_or_receipts_is_never_success(self):
        for kw in (dict(executions=(), receipts=()), dict(receipts=())):
            result = evaluate(**kw)
            self.assertEqual(result.verdict, bg.UNKNOWN)
            self.assertIn(bg.NO_EVIDENCE, result.reasons)
            self.assertEqual(result.evidence_ids, ())

    def test_unverified_receipt_is_unknown_and_runner_classified_overclaims(self):
        unverified = evaluate(receipts=(tokens(reliability=qc.RELIABILITY_UNVERIFIED),))
        self.assertIn(bg.EVIDENCE_UNVERIFIED, unverified.reasons)
        self.assertEqual(unverified.verdict, bg.UNKNOWN)
        self.assertRefused(evaluate(receipts=(tokens(reliability=qc.RELIABILITY_RUNNER_CLASSIFIED),)),
                           bg.RECEIPT_RELIABILITY_OVERCLAIMED)
        self.assertRefused(evaluate(receipts=(tokens(reliability="TRUSTED"),)), bg.RECEIPT_RELIABILITY_UNKNOWN)

    def test_future_dated_execution_or_receipt_is_unknown(self):
        future = evaluate(executions=(execution(incurred="2026-10-31T12:00:01Z"),),
                          receipts=(tokens(recorded="2026-10-31T12:30:00Z"),))
        self.assertIn(bg.EVIDENCE_FROM_FUTURE, self.account(future, "tok").reasons)
        self.assertEqual(self.account(future, "tok").execution_ids, ("e1",))
        late = evaluate(receipts=(tokens(recorded="2026-10-31T12:00:01Z"),))
        self.assertIn(bg.EVIDENCE_FROM_FUTURE, late.reasons)

    def test_observed_receipt_recorded_before_its_execution_is_contradictory(self):
        early = evaluate(receipts=(tokens(recorded="2026-10-31T10:59:59Z"),))
        self.assertIn(bg.EVIDENCE_CONTRADICTORY, early.reasons)
        estimate = receipt("r1", "e1", qty(IN, 1000), qty(OUT, 500), qty(TOTAL, 1500), basis=bg.BASIS_ESTIMATED,
                           recorded="2026-10-31T10:00:00Z")
        self.assertEqual(evaluate(receipts=(estimate,)).verdict, bg.READY)

    def test_receipt_quantities_and_ranges_are_validated(self):
        self.assertRefused(evaluate(receipts=(receipt("r1", "e1", qty(IN, 10, 20)),)), bg.RECEIPT_RANGE_INVALID)
        self.assertRefused(evaluate(receipts=(receipt("r1", "e1", qty(IN, 20, 10), basis=bg.BASIS_ESTIMATED),)),
                           bg.RECEIPT_RANGE_INVALID)
        self.assertRefused(evaluate(receipts=(receipt("r1", "e1", qty(IN, 1), qty(IN, 1)),)),
                           bg.RECEIPT_UNIT_DUPLICATE)
        self.assertRefused(evaluate(receipts=(receipt("r1", "e1", qty(qc.UNIT_CONCURRENT_EXECUTIONS, 1)),)),
                           bg.RECEIPT_UNIT_INVALID)
        for amount in (-1, 1.5, True, qc.UNIT_MAXIMUM[IN] + 1):
            self.assertRefused(evaluate(receipts=(receipt("r1", "e1", qty(IN, amount)),)), bg.RECEIPT_UNIT_INVALID)
        self.assertRefused(evaluate(receipts=(receipt("r1", "e1"),)), bg.RECEIPT_QUANTITIES_MALFORMED)
        self.assertRefused(evaluate(receipts=(tokens(basis="BILLED"),)), bg.RECEIPT_BASIS_UNKNOWN)
        self.assertRefused(evaluate(receipts=(tokens(recorded="2026-10-31T11:05:00+02:00"),)),
                           bg.RECEIPT_TIME_INVALID)


class WindowTests(BudgetTestBase):
    def test_rolling_window_excludes_its_exclusive_start_and_older_usage(self):
        execs = (execution("e1", incurred="2026-10-30T12:00:00Z"), execution("e2", incurred="2026-10-30T12:00:01Z"))
        receipts = (tokens("r1", "e1", recorded="2026-10-30T12:10:00Z"),
                    tokens("r2", "e2", inp=10, out=10, recorded="2026-10-30T12:10:00Z"))
        tok = self.account(evaluate(executions=execs, receipts=receipts), "tok")
        self.assertEqual((tok.execution_ids, tok.evidence_ids, tok.accounted), (("e2",), ("r2",), 20))
        self.assertEqual((tok.window_start_utc, tok.window_end_utc), ("2026-10-30T12:00:00Z", AS_OF))

    def test_fixed_window_uses_the_anchored_period_containing_as_of(self):
        hourly = qc.QuotaWindow(qc.WINDOW_FIXED, 3600, anchor_utc="2026-01-01T00:30:00+00:00")
        execs = (execution("e1", incurred="2026-10-31T11:29:59Z"), execution("e2", incurred="2026-10-31T11:30:00Z"))
        receipts = (tokens("r1", "e1", recorded="2026-10-31T11:40:00Z"),
                    tokens("r2", "e2", inp=1, out=1, recorded="2026-10-31T11:40:00Z"))
        tok = self.account(evaluate(policy=policy(limits=(usage_limit(window=hourly),)), executions=execs,
                                    receipts=receipts), "tok")
        self.assertEqual((tok.window_kind, tok.window_start_utc, tok.window_end_utc),
                         (qc.WINDOW_FIXED, "2026-10-31T11:30:00Z", "2026-10-31T12:30:00Z"))
        self.assertEqual((tok.execution_ids, tok.accounted), (("e2",), 2))

    def test_out_of_window_usage_without_receipts_does_not_poison_the_budget(self):
        old = execution("old", incurred="2026-10-01T00:00:00Z")
        result = evaluate(executions=(execution(), old))
        self.assertEqual(result.verdict, bg.READY)
        self.assertEqual(self.account(result, "tok").execution_ids, ("e1",))

    def test_budget_windows_and_units_are_validated_through_the_contract(self):
        self.assertRefused(evaluate(policy=policy(limits=(usage_limit(window=None),))), bg.LIMIT_WINDOW_REQUIRED)
        self.assertRefused(evaluate(policy=policy(limits=(cost_limit(window=None),))), bg.LIMIT_WINDOW_REQUIRED)
        self.assertRefused(evaluate(policy=policy(limits=(cost_limit(window=qc.QuotaWindow("DAILY", 60)),))),
                           bg.WINDOW_KIND_UNKNOWN)
        self.assertRefused(evaluate(policy=policy(limits=(cost_limit(window=(86400,)),))), bg.WINDOW_NOT_TYPED)
        concurrent = qc.QuotaLimit("conc", qc.SCOPE_GLOBAL, qc.UNIT_CONCURRENT_EXECUTIONS, 2)
        self.assertRefused(evaluate(policy=policy(limits=(concurrent,))), bg.LIMIT_UNIT_NOT_CUMULATIVE)
        self.assertRefused(evaluate(policy=policy(limits=(usage_limit(unit=bg.UNIT_COST),))), bg.LIMIT_UNIT_UNKNOWN)
        self.assertRefused(evaluate(policy=policy(limits=(usage_limit(maximum=0),))), bg.LIMIT_MAXIMUM_INVALID)


class OverBudgetTests(BudgetTestBase):
    def test_accounted_above_maximum_is_overrun_and_fail_closed(self):
        result = evaluate(policy=policy(limits=(usage_limit(maximum=1000), cost_limit())))
        tok = self.account(result, "tok")
        self.assertEqual(tok.verdict, bg.WAIT)
        self.assertEqual(tok.reasons, (bg.BUDGET_OVERRUN, bg.LIMIT_SATURATED))
        self.assertEqual((tok.accounted, tok.remaining), (1500, 0))
        self.assertTrue(result.over_budget)
        self.assertEqual(result.verdict, bg.WAIT)

    def test_exhausted_exactly_without_reservation_is_saturated_not_overrun(self):
        tok = self.account(evaluate(policy=policy(limits=(usage_limit(maximum=1500),))), "tok")
        self.assertEqual(tok.reasons, (bg.LIMIT_SATURATED,))
        self.assertFalse(tok.over_budget)

    def test_estimate_upper_bound_decides_saturation_conservatively(self):
        est = receipt("r1", "e1", qty(TOTAL, 100, 2000), basis=bg.BASIS_ESTIMATED)
        tok = self.account(evaluate(receipts=(est,), policy=policy(limits=(usage_limit(maximum=1500),))), "tok")
        self.assertIn(bg.BUDGET_OVERRUN, tok.reasons)
        self.assertEqual((tok.estimated_low, tok.accounted), (100, 2000))

    def test_reservation_that_fits_saturates_or_alone_exceeds(self):
        lim = (usage_limit(maximum=2000),)
        fits = evaluate(policy=policy(limits=lim), reservation=reservation((TOTAL, 500)))
        self.assertEqual(fits.verdict, bg.READY)
        self.assertEqual(self.account(fits, "tok").projected, 2000)
        over = evaluate(policy=policy(limits=lim), reservation=reservation((TOTAL, 501)))
        self.assertEqual(self.account(over, "tok").reasons, (bg.LIMIT_SATURATED,))
        alone = evaluate(policy=policy(limits=lim), reservation=reservation((TOTAL, 2001)))
        self.assertEqual(alone.verdict, bg.REFUSE)
        self.assertIn(bg.RESERVATION_EXCEEDS_LIMIT, alone.reasons)
        self.assertEqual(alone.request_reasons, ())

    def test_reservation_cost_is_priced_at_as_of_and_rounded_up(self):
        res = reservation((IN, 1), (OUT, 1), (TOTAL, 2))
        money = self.account(evaluate(reservation=res), "money")
        self.assertTrue(money.reservation_in_scope)
        self.assertEqual((money.reserved, money.projected), (D("0.01"), D("0.03")))
        missing = self.account(evaluate(reservation=reservation((IN, 1))), "money")
        self.assertIn(bg.USAGE_UNKNOWN, missing.reasons)
        self.assertIsNone(missing.reserved)
        priced_nothing = self.account(evaluate(reservation=res, tariffs=(tariff("t-in", IN, D("3"), provider="b"),)),
                                      "money")
        self.assertIn(bg.TARIFF_MISSING, priced_nothing.reasons)

    def test_reservation_scope_and_units(self):
        beta = usage_limit("beta", scope=qc.SCOPE_PROVIDER, provider_id="beta")
        result = evaluate(policy=policy(limits=(beta,)), executions=(execution("e1", "beta"),),
                          reservation=reservation((TOTAL, 10)))
        self.assertFalse(self.account(result, "beta").reservation_in_scope)
        self.assertIsNone(self.account(result, "beta").reserved)
        no_unit = evaluate(policy=policy(limits=(usage_limit(),)), reservation=reservation((IN, 10)))
        self.assertIn(bg.USAGE_UNKNOWN, no_unit.reasons)
        self.assertRefused(evaluate(reservation=reservation((qc.UNIT_CONCURRENT_EXECUTIONS, 1))),
                           bg.RESERVATION_UNIT_NOT_CUMULATIVE)
        self.assertRefused(evaluate(reservation=reservation((TOTAL, 1), (TOTAL, 2))), bg.RESERVATION_UNIT_DUPLICATE)
        self.assertRefused(evaluate(reservation="next"), bg.RESERVATION_NOT_TYPED)

    def test_resource_scoped_budget_counts_only_its_resource(self):
        gpu = cost_limit("gpu", scope=qc.SCOPE_RESOURCE, resource_id="gpu-a", maximum=D("0.01"))
        execs = (execution("e1", resource="gpu-a"), execution("e2", resource="gpu-b"))
        result = evaluate(policy=policy(limits=(gpu,)), executions=execs, receipts=(tokens(), tokens("r2", "e2")))
        account = self.account(result, "gpu")
        self.assertEqual((account.execution_ids, account.accounted), (("e1",), D("0.02")))
        self.assertIn(bg.BUDGET_OVERRUN, account.reasons)


class StructureTests(BudgetTestBase):
    def test_untyped_and_mutable_inputs_are_refused(self):
        self.assertRefused(bg.evaluate_budget(None), bg.REQUEST_NOT_TYPED)
        self.assertRefused(bg.evaluate_budget(dataclasses.asdict(request())), bg.REQUEST_NOT_TYPED)
        self.assertRefused(evaluate(policy={"policy_id": "pol"}), bg.POLICY_NOT_TYPED)
        self.assertRefused(evaluate(executions=[execution()]), bg.EXECUTIONS_MALFORMED)
        self.assertRefused(evaluate(receipts=[tokens()]), bg.RECEIPTS_MALFORMED)
        self.assertRefused(evaluate(policy=policy(limits=[usage_limit()])), bg.LIMITS_MALFORMED)
        self.assertRefused(evaluate(policy=policy(limits=())), bg.LIMITS_EMPTY)
        self.assertRefused(evaluate(schema_version=2), bg.SCHEMA_VERSION_UNSUPPORTED)
        self.assertRefused(evaluate(as_of_utc="2026-10-31T12:00:00"), bg.AS_OF_INVALID)
        self.assertRefused(evaluate(executions=tuple(execution(f"e{i}") for i in range(bg.MAX_EXECUTIONS + 1))),
                           bg.EXECUTIONS_MALFORMED)
        for bad in (execution(eid="E1"), execution(provider="Al pha"), execution(resource="GPU"),
                    execution(incurred="yesterday")):
            self.assertEqual(evaluate(executions=(bad,), receipts=()).verdict, bg.REFUSE)

    def test_ambiguous_budgets_and_scope_shapes_are_refused(self):
        self.assertRefused(evaluate(policy=policy(limits=(cost_limit("a"), cost_limit("b")))), bg.LIMIT_AMBIGUOUS)
        self.assertRefused(evaluate(policy=policy(limits=(usage_limit("a"), usage_limit("b")))), bg.LIMIT_AMBIGUOUS)
        self.assertRefused(evaluate(policy=policy(limits=(cost_limit(scope=qc.SCOPE_PROVIDER),))),
                           bg.LIMIT_SCOPE_TARGET_INVALID)
        self.assertRefused(evaluate(policy=policy(limits=(cost_limit(scope="TENANT"),))), bg.LIMIT_SCOPE_UNKNOWN)
        distinct = policy(limits=(usage_limit("a"), cost_limit("b")))
        self.assertEqual(evaluate(policy=distinct).verdict, bg.READY)

    def test_secret_shaped_ids_are_refused_and_never_echoed(self):
        secret = "sk-ant-api03-" + "a" * 30
        for kw in (dict(executions=(execution(secret[:40]),), receipts=()),
                   dict(receipts=(tokens(secret[:40]),))):
            result = evaluate(**kw)
            self.assertEqual(result.verdict, bg.REFUSE)
            self.assertNotIn(secret[:20], bg.canonical_json(result))

    def test_fingerprint_is_order_and_decimal_form_independent_but_value_sensitive(self):
        base = request(executions=(execution("e1"), execution("e2")), receipts=(tokens(), tokens("r2", "e2")))
        shuffled = request(executions=(execution("e2"), execution("e1")), receipts=(tokens("r2", "e2"), tokens()),
                           tariffs=(tariff("t-out", OUT, D("15.000")), tariff("t-in", IN, D("3.0"))))
        self.assertEqual(bg.request_fingerprint(base), bg.request_fingerprint(shuffled))
        self.assertEqual(bg.canonical_json(bg.evaluate_budget(base)), bg.canonical_json(bg.evaluate_budget(shuffled)))
        changed = request(tariffs=(tariff("t-in", IN, D("3.0000001")), tariff("t-out", OUT, D("15"))))
        self.assertNotEqual(bg.request_fingerprint(request()), bg.request_fingerprint(changed))
        with self.assertRaises(ValueError):
            bg.request_fingerprint(request(request_id="BAD"))

    def test_canonical_json_is_stable_money_as_text_and_float_free(self):
        result = evaluate()
        text = bg.canonical_json(result)
        self.assertEqual(text, bg.canonical_json(evaluate()))

        def no_float(value):
            raise AssertionError(f"float in output: {value}")
        payload = json.loads(text, parse_float=no_float)
        money = next(a for a in payload["accounts"] if a["unit"] == bg.UNIT_COST)
        self.assertEqual((money["maximum"], money["accounted"], payload["granularity"]), ("10.00", "0.02", "0.01"))
        self.assertEqual(payload["schema"], bg.SCHEMA)
        with self.assertRaises(TypeError):
            bg.canonical_json(dataclasses.asdict(result))

    def test_zero_authority_guarantees_are_fixed_and_unsettable(self):
        for result in (evaluate(), bg.evaluate_budget(None)):
            payload = result.to_dict()
            for flag in ALL_FLAGS:
                self.assertIs(getattr(result, flag), False, flag)
                self.assertIs(payload[flag], False, flag)
                with self.assertRaises(AttributeError):
                    setattr(result, flag, True)
            self.assertEqual(payload["marker"], bg.BUDGET_MARKER)

    def test_hand_made_accounts_cannot_claim_more_than_their_amounts(self):
        account = self.account(evaluate(), "tok")
        for change in (dict(remaining=9000), dict(accounted=10), dict(verdict=bg.WAIT),
                       dict(reasons=(bg.LIMIT_SATURATED,), verdict=bg.WAIT), dict(observed=None),
                       dict(reserved=5), dict(execution_ids=("b", "a")), dict(window_start_utc=AS_OF)):
            with self.assertRaises(ValueError, msg=change):
                dataclasses.replace(account, **change)
        over = self.account(evaluate(policy=policy(limits=(usage_limit(maximum=1000),))), "tok")
        with self.assertRaises(ValueError):
            dataclasses.replace(over, reasons=(), verdict=bg.READY)
        unknown = self.account(evaluate(tariffs=()), "money")
        with self.assertRaises(ValueError):
            dataclasses.replace(unknown, accounted=D("0.00"))

    def test_hand_made_evaluations_cannot_hide_doubt_or_success_without_evidence(self):
        result = evaluate()
        with self.assertRaises(ValueError):
            dataclasses.replace(result, evidence_ids=())
        unknown = evaluate(tariffs=())
        with self.assertRaises(ValueError):
            dataclasses.replace(unknown, reasons=(), verdict=bg.READY)
        with self.assertRaises(ValueError):
            dataclasses.replace(result, granularity=D("0.001"))
        with self.assertRaises(ValueError):
            dataclasses.replace(result, accounts=tuple(reversed(result.accounts)))
        with self.assertRaises(ValueError):
            dataclasses.replace(bg.evaluate_budget(None), request_id="req")

    def test_inputs_are_never_mutated_and_are_frozen(self):
        req = request(reservation=reservation((TOTAL, 1), (IN, 1), (OUT, 1)))
        before = copy.deepcopy(req)
        bg.evaluate_budget(req)
        self.assertEqual(req, before)
        for obj in (req, req.policy, req.executions[0], req.receipts[0], req.receipts[0].quantities[0],
                    req.tariffs[0], req.policy.limits[1]):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(obj, dataclasses.fields(obj)[0].name, "x")

    def test_garbage_never_raises(self):
        values = (None, 0, "", "x", (), [], {}, 1.5, True, D("1"), object())
        for value in values:
            for name in ("request_id", "as_of_utc", "policy", "executions", "receipts", "tariffs", "reservation",
                         "schema_version"):
                result = evaluate(**{name: value})
                self.assertIn(result.verdict, bg.VERDICTS)
                bg.canonical_json(result)
            for name in ("policy_id", "currency", "granularity", "limits", "schema_version"):
                fields = dataclasses.asdict(policy()) | {name: value}
                fields["limits"] = fields["limits"] if name == "limits" else policy().limits
                self.assertIn(evaluate(policy=bg.BudgetPolicy(**fields)).verdict, bg.VERDICTS)


class GovernanceTests(BudgetTestBase):
    def test_no_io_process_network_provider_or_ledger_entry_point(self):
        boom = AssertionError("I/O, provider, ledger or execution entry point")
        patches = [mock.patch.object(subprocess, "Popen", side_effect=boom),
                   mock.patch.object(builtins, "open", side_effect=boom),
                   mock.patch.object(socket, "socket", side_effect=boom),
                   mock.patch.object(flog.FactoryLedger, "append", side_effect=boom),
                   mock.patch.object(flog.FactoryLedger, "__init__", side_effect=boom),
                   mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom),
                   mock.patch.object(rp.PipelineRunner, "_start_ready", side_effect=boom)]
        for patch in patches:
            patch.start()
        try:
            result = evaluate(reservation=reservation((TOTAL, 1), (IN, 1), (OUT, 1)))
            bg.canonical_json(result)
        finally:
            for patch in reversed(patches):
                patch.stop()
        self.assertEqual(result.verdict, bg.READY)

    def test_module_imports_and_code_stay_within_the_governed_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        own = ("fabric_resource_quota_contract", "fabric_scheduler_contract")
        self.assertEqual(imported, {"__future__", "dataclasses", "datetime", "decimal", "hashlib", "re", "typing"}
                         | {f"scripts.ai.{m}" for m in own} | set(own))
        code = _module_code()
        for word in ("subprocess", "open(", "Path(", "os.", "socket", "Thread", "Executor", "PipelineRunner",
                     "FactoryLedger", "runner_factory_ledger", ".write(", "requests.", "urllib", "http", "environ",
                     ".now(",
                     "utcnow", "time.", "sleep", "while ", "claude", "codex", "anthropic", "openai", "eval(",
                     "exec(", "importlib", "random", "float(", "getcontext", "setcontext", "localcontext",
                     "customer", "email", "keyring", "cookie"):
            self.assertNotIn(word, code, word)
        floats = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and type(n.value) is float]
        self.assertEqual(floats, [])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))])

    def test_no_price_table_exists_in_the_module(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        decimals = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Decimal"]
        literal = {ast.unparse(n) for n in decimals}
        self.assertLessEqual(literal, {"Decimal(10)", "Decimal(0)", "Decimal(quantity)",
                                       "Decimal(tariff.per_quantity)"})
        self.assertFalse(any(isinstance(v, D) and v > 0 for v in vars(bg).values() if v is not bg.MAX_MONEY))

    def test_no_mutable_module_state_changes(self):
        modules = (bg, qc, sc)
        snapshots = [{k: copy.deepcopy(v) for k, v in vars(mod).items()
                      if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
                     for mod in modules]
        contexts = [(c.prec, c.rounding) for c in (bg._EXACT, bg._UP, bg._DOWN)]
        evaluate()
        evaluate(tariffs=())
        bg.evaluate_budget(None)
        for mod, snapshot in zip(modules, snapshots):
            self.assertEqual({k: v for k, v in vars(mod).items() if k in snapshot}, snapshot)
        self.assertEqual([(c.prec, c.rounding) for c in (bg._EXACT, bg._UP, bg._DOWN)], contexts)

    def test_vocabularies_unique_disjoint_and_reused(self):
        for vocab in (bg.BUDGET_UNITS, bg.BASES, bg.REQUEST_REASONS, bg.RESULT_REASONS):
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertFalse(set(bg.REQUEST_REASONS) & set(bg.RESULT_REASONS))
        self.assertEqual(set(bg.USAGE_UNITS), set(qc.UNITS) - set(qc.INSTANT_UNITS))
        self.assertNotIn(bg.UNIT_COST, qc.UNITS)
        self.assertEqual(bg.VERDICTS, qc.VERDICTS)
        for code in (bg.RESERVATION_EXCEEDS_LIMIT, bg.NO_EVIDENCE, bg.EVIDENCE_FROM_FUTURE, bg.EVIDENCE_UNVERIFIED,
                     bg.EVIDENCE_CONTRADICTORY, bg.USAGE_UNKNOWN, bg.LIMIT_SATURATED):
            self.assertIn(code, qc.RESULT_REASONS)
        for code in (bg.RESERVATION_EXCEEDS_LIMIT, bg.LIMIT_SATURATED, bg.USAGE_UNKNOWN):
            self.assertEqual(bg.verdict_for((code,)), qc.verdict_for((code,)))

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
