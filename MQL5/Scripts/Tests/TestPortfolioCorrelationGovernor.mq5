//+------------------------------------------------------------------+
//|                          TestPortfolioCorrelationGovernor.mq5    |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <GoldenTradeX/PortfolioCorrelationGovernor.mqh>

int g_pass = 0;
int g_fail = 0;

void AssertTrue(bool condition, string label)
  {
   if(condition) { g_pass++; Print("  PASS  ", label); }
   else          { g_fail++; Print("  FAIL  ", label); }
  }

void AssertNear(double actual, double expected, double tolerance, string label)
  {
   AssertTrue(MathAbs(actual - expected) <= tolerance, label);
  }

void OnStart()
  {
   Print("=== TestPortfolioCorrelationGovernor BEGIN ===");

   CPortfolioCorrelationGovernor governor;
   governor.Init(1.5, 0.80);

   double a[] = {1, 2, 3, 4, 5};
   double b[] = {2, 4, 6, 8, 10};
   double c[] = {10, 8, 6, 4, 2};
   AssertNear(governor.Pearson(a, b, 5), 1.0, 1e-9, "Perfect positive correlation is detected");
   AssertNear(governor.Pearson(a, c, 5), -1.0, 1e-9, "Perfect inverse correlation is detected");

   string reason = "";
   AssertTrue(governor.AllowsRiskBudget(0.75, 0.50, reason), "Candidate inside aggregate risk budget is allowed");
   AssertTrue(!governor.AllowsRiskBudget(1.10, 0.50, reason), "Aggregate risk above cap is blocked");
   AssertTrue(reason == "PORTFOLIO_RISK_CAP", "Risk-cap rejection is explicit");

   AssertTrue(!governor.AllowsPairwiseExposure(0.90, 1, 1, reason),
              "Highly positively correlated same-direction exposure is blocked");
   AssertTrue(reason == "ALIGNED_CORRELATION_LIMIT", "Aligned-correlation rejection is explicit");

   AssertTrue(governor.AllowsPairwiseExposure(0.90, 1, -1, reason),
              "Positive correlation with opposite directions is not treated as aligned exposure");
   AssertTrue(!governor.AllowsPairwiseExposure(-0.90, 1, -1, reason),
              "Strong inverse correlation with opposite directions is blocked as aligned exposure");

   AssertTrue(!governor.AllowsPairwiseExposure(1.20, 1, 1, reason),
              "Invalid correlation fails closed");
   AssertTrue(reason == "CORRELATION_INVALID", "Invalid correlation rejection is explicit");

   Print("=== TestPortfolioCorrelationGovernor END | PASS=", g_pass, " FAIL=", g_fail, " ===");
  }
