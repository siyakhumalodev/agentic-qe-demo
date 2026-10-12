using System;
using System.Threading;
using NUnit.Framework;
using OpenQA.Selenium;
using OpenQA.Selenium.Chrome;
using TechTalk.SpecFlow;
using Contoso.Payout.Tests.Pages;

namespace Contoso.Payout.Tests.StepDefinitions
{
    [Binding]
    public class PayoutLimitSteps
    {
        private readonly ScenarioContext _scenarioContext;
        private IWebDriver _driver;
        private PayoutPortalPage _portal;

        public PayoutLimitSteps(ScenarioContext scenarioContext)
        {
            _scenarioContext = scenarioContext;
        }

        [Given(@"I have opened the payout portal")]
        public void GivenIHaveOpenedThePayoutPortal()
        {
            _driver = new ChromeDriver();
            _driver.Manage().Window.Maximize();
            _driver.Navigate().GoToUrl("http://localhost:8085/");
            Thread.Sleep(3000); // wait for the page to load
            _portal = new PayoutPortalPage(_driver);
            _scenarioContext["driver"] = _driver;
        }

        [When(@"I start a payout run for case ""(.*)""")]
        public void WhenIStartAPayoutRunForCase(string caseRef)
        {
            _portal.ClickStartPayoutRun(caseRef);
            Thread.Sleep(2000);
        }

        [When(@"I wait for the payout run to finish")]
        public void WhenIWaitForThePayoutRunToFinish()
        {
            // The run normally takes about 15 seconds; wait 20 to be safe.
            Thread.Sleep(20000);
            _driver.Navigate().Refresh();
            Thread.Sleep(2000);
        }

        [Then(@"the run status should be ""(.*)""")]
        public void ThenTheRunStatusShouldBe(string expectedStatus)
        {
            Assert.AreEqual(expectedStatus, _portal.GetRunStatus());
        }

        [Then(@"the payment for depositor ""(.*)"" should be ""(.*)""")]
        public void ThenThePaymentForDepositorShouldBe(string depositorId, string expectedAmount)
        {
            Assert.AreEqual(expectedAmount, _portal.GetPaymentFor(depositorId));
        }

        [AfterScenario]
        public void TearDown()
        {
            if (_scenarioContext.ContainsKey("driver"))
            {
                ((IWebDriver)_scenarioContext["driver"]).Quit();
            }
        }
    }
}
