# Legacy sample: SpecFlow + Selenium WebDriver (C#)

A small, representative legacy UI test used by the **Framework Migrator** agent (optional Demo 4).
It is **not built or run** in this kit - there is no .csproj on purpose.

| File | Typical legacy traits |
|---|---|
| `Features/PayoutLimit.feature` | Gherkin scenario with a hard-coded business expectation |
| `StepDefinitions/PayoutLimitSteps.cs` | SpecFlow bindings, `ScenarioContext`, Selenium WebDriver, `Thread.Sleep` |
| `Pages/PayoutPortalPage.cs` | Page object with brittle absolute XPath locators |

Try: agent **Framework Migrator** with the prompt in `.github/prompts/migrate-legacy-test.prompt.md`.
Fictional data; simplified rules for demonstration only — not FSCS policy.
