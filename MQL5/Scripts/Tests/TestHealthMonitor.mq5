//+------------------------------------------------------------------+
//|                                            TestHealthMonitor.mq5 |
//| Golden Trade X — deterministic health/lifecycle safety tests     |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <GoldenTradeX/HealthMonitor.mqh>

int g_pass = 0;
int g_fail = 0;

void AssertTrue(bool condition, string label)
  {
   if(condition) { g_pass++; Print("[PASS] ", label); }
   else          { g_fail++; Print("[FAIL] ", label); }
  }

void AssertEq(string actual, string expected, string label)
  {
   AssertTrue(actual == expected,
              label + " got='" + actual + "' expected='" + expected + "'");
  }

void OnStart()
  {
   Print("=== TestHealthMonitor BEGIN ===");

   CHealthMonitor health;

   // Constructor must be deterministic before Init(). This protects startup
   // and error paths where a later indicator initialization can fail.
   AssertTrue(health.GetOrphanFixCount() == 0,
              "Constructor initializes orphan-fix counter");

   AssertEq(health.BuildAlert(true, 250.0), "",
            "Healthy connection and margin produce no alert");
   AssertEq(health.BuildAlert(false, 250.0), "DISCONNECTED",
            "Disconnected terminal is represented explicitly");
   AssertEq(health.BuildAlert(true, 150.0), "MARGIN_LOW:150%",
            "Low margin is represented explicitly");
   AssertEq(health.BuildAlert(false, 150.0),
            "MARGIN_LOW:150%|DISCONNECTED",
            "Low margin and disconnect compose deterministically");

   // Default check interval is 60 seconds and last-check starts at epoch 0.
   AssertTrue(!health.IsCheckDueAt((datetime)59),
              "Health check is rate-limited before interval");
   AssertTrue(health.IsCheckDueAt((datetime)60),
              "Health check becomes due at interval boundary");
   AssertTrue(health.IsCheckDueAt((datetime)120),
              "Health check remains due after interval boundary");

   Print("=== TestHealthMonitor END | PASS=", g_pass,
         " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " FAILURE(S) — REVIEW LOG <<<");
  }
//+------------------------------------------------------------------+
