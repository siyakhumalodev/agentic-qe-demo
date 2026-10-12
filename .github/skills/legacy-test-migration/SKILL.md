---
name: legacy-test-migration
description: Mapping guide for migrating SpecFlow + Selenium WebDriver (C#) tests to pytest-bdd + Playwright for Python, or to Reqnroll + Playwright .NET - bindings, context, hooks, waits, locators, assertions - plus a procedure for flagging stale business rules. Use when migrating or reviewing tests under legacy/.
---

# Legacy test migration (SpecFlow + Selenium -> modern stacks)

Two independent decisions:
- **BDD layer:** SpecFlow (no longer maintained) -> **Reqnroll** (open-source successor; keeps C# and
  Gherkin) or **pytest-bdd** (Python).
- **Browser layer:** Selenium WebDriver -> **Playwright** (.NET, Python or TypeScript): auto-waiting,
  role-based locators, tracing.

The Gherkin `.feature` files usually move almost unchanged; the value is in bindings and waits.

## SpecFlow -> pytest-bdd / Reqnroll

| SpecFlow (C#) | pytest-bdd (Python) | Reqnroll (C#) |
|---|---|---|
| `[Binding] public class XSteps` | module `tests/.../test_x_steps.py` + `scenarios("...feature")` | `[Binding]` (namespace `Reqnroll`) |
| `[Given(@"I start a run for case ""(.*)""")]` | `@given(parsers.parse('I start a run for case "{case_ref}"'))` | `[Given("I start a run for case {string}")]` (cucumber expressions) or regex |
| `ScenarioContext.Current["x"]` / context injection | fixtures and `target_fixture="x"` | context injection (constructor) |
| `[BeforeScenario]` / `[AfterScenario]` | fixtures with `yield` | `[BeforeScenario]` / `[AfterScenario]` |
| `Table` / `table.CreateSet<T>()` | `datatable` argument (pytest-bdd 8) or plain steps | `DataTable` helpers |
| `Assert.AreEqual(a, b)` | `assert a == b, "message"` / `expect(...)` | `Assert...` / Playwright assertions |
| `SpecFlow.Plus.LivingDoc` | pytest `--junitxml` + traceability report | Reqnroll reporting |

## Selenium -> Playwright

| Selenium | Playwright (Python) | Why |
|---|---|---|
| `new ChromeDriver()` + `Navigate().GoToUrl(url)` | `page` fixture + `page.goto("/")` (base_url) | managed browser lifecycle |
| `FindElement(By.XPath("//table/tbody/tr[1]/td[5]/form/button"))` | `page.get_by_role("button", name="Start payout run")` | resilient, accessible |
| `FindElement(By.Id("status")).Text` | `page.get_by_test_id("run-status")` | stable test ids |
| `Thread.Sleep(15000)` | `expect(locator).to_have_text("Completed", timeout=120_000)` | waits only as long as needed |
| `WebDriverWait(...).Until(...)` | `expect(...)` auto-waiting | built in |
| `driver.Quit()` in `[AfterScenario]` | automatic | - |
| Screenshot on failure (custom) | `--screenshot only-on-failure`, `--tracing retain-on-failure` | built in |

## Procedure

1. Inventory: scenarios, step bindings, page objects, waits, locators, **hard-coded business values**.
2. Check every business value against the `deposit-compensation-rules` skill. A mismatch is a **rule
   conflict** - e.g. an expected payment of £85,000.00 for a depositor above the limit is the limit
   before 1 Dec 2025; today it is `payout.config.DEPOSIT_LIMIT_GBP` (£120,000.00).
3. Migrate structure first (feature + bindings), then locators and waits, then data.
4. Express rule-dependent expectations through configuration (`DEPOSIT_LIMIT_GBP`), and list every
   changed expectation under "Rule conflicts" for a human decision.
5. Validate: collect-only always; run against the estate when it is up.
6. Leave the legacy sources untouched; write `reports/MIGRATION-<name>.md`.
