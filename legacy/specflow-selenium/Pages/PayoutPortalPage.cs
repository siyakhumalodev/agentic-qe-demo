using OpenQA.Selenium;

namespace Contoso.Payout.Tests.Pages
{
    public class PayoutPortalPage
    {
        private readonly IWebDriver _driver;

        public PayoutPortalPage(IWebDriver driver)
        {
            _driver = driver;
        }

        // Absolute XPath recorded with a browser plug-in.
        private const string StartRunButtonXPath = "/html/body/main/table[1]/tbody/tr[1]/td[4]/form/button";
        private const string RunStatusXPath = "/html/body/main/p[3]/span";
        private const string PaymentsTableXPath = "/html/body/main/section[3]/table/tbody";

        public void ClickStartPayoutRun(string caseRef)
        {
            // Assumes the case is always in the first row.
            _driver.FindElement(By.XPath(StartRunButtonXPath)).Click();
        }

        public string GetRunStatus()
        {
            return _driver.FindElement(By.XPath(RunStatusXPath)).Text.Trim();
        }

        public string GetPaymentFor(string depositorId)
        {
            var row = _driver.FindElement(By.XPath(PaymentsTableXPath + "/tr[th[text()='" + depositorId + "']]"));
            return row.FindElement(By.XPath("./td[3]")).Text.Trim();
        }
    }
}
