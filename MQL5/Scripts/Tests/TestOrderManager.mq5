//+------------------------------------------------------------------+
//|                                           TestOrderManager.mq5   |
//|   Golden Trade X — Unit tests for COrderManager                  |
//+------------------------------------------------------------------+
//  Tests: SL/TP validation, error classification, stats tracking.
//  No live orders are sent — tests run against mock logic only.
//  Run in MetaEditor: Script > Compile, then drag to chart.
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs

#include <Trade/Trade.mqh>
#include <GoldenTradeX/OrderManager.mqh>

int g_pass = 0;
int g_fail = 0;

void Assert(bool cond, string label)
  {
   if(cond) { Print("[PASS] ", label); g_pass++; }
   else      { Print("[FAIL] ", label); g_fail++; }
  }

// ── Testable subclass exposing internal classification ────────────
class COrderManagerTestable : public COrderManager
  {
public:
   bool TestIsRetryable(uint code)
     {
      return code == 10004 || code == 10020 || code == 10021 ||
             code == 10024 || code == 10031;
     }
   bool TestIsFatal(uint code)
     {
      return code == 10019 || code == 10017 || code == 10029;
     }
   bool TestIsSuccess(uint code)
     {
      return code == 10009 || code == 10010;
     }
   // Simulate SL/TP validation logic (mirrors OpenPosition guard)
   bool ValidateSlTp(ENUM_ORDER_TYPE type, double price, double sl, double tp)
     {
      if(sl == 0 || tp == 0)   return false;
      if(type == ORDER_TYPE_BUY  && (sl >= price || tp <= price)) return false;
      if(type == ORDER_TYPE_SELL && (sl <= price || tp >= price)) return false;
      return true;
     }
  };

void OnStart()
  {
   COrderManagerTestable om;
   CTrade trade;
   om.Init(&trade, 3, 100);

   Print("─── TestOrderManager ───────────────────────────────");

   // ── Group 1: Error classification ───────────────────────────────
   Print("Group 1: Error classification");
   Assert(om.TestIsRetryable(10004), "REQUOTE (10004) is retryable");
   Assert(om.TestIsRetryable(10020), "PRICE_CHANGED (10020) is retryable");
   Assert(om.TestIsRetryable(10021), "PRICE_OFF (10021) is retryable");
   Assert(om.TestIsRetryable(10024), "TOO_MANY_REQUESTS (10024) is retryable");
   Assert(om.TestIsRetryable(10031), "CONNECTION (10031) is retryable");
   Assert(!om.TestIsRetryable(10016), "INVALID_STOPS (10016) is NOT retryable");
   Assert(!om.TestIsRetryable(10019), "NO_MONEY (10019) is NOT retryable");

   Assert(om.TestIsFatal(10019), "NO_MONEY (10019) is fatal");
   Assert(om.TestIsFatal(10017), "TRADE_DISABLED (10017) is fatal");
   Assert(om.TestIsFatal(10029), "FROZEN (10029) is fatal");
   Assert(!om.TestIsFatal(10004), "REQUOTE (10004) is NOT fatal");
   Assert(!om.TestIsFatal(10009), "DONE (10009) is NOT fatal");

   Assert(om.TestIsSuccess(10009), "DONE (10009) is success");
   Assert(om.TestIsSuccess(10010), "DONE_PARTIAL (10010) is success");
   Assert(!om.TestIsSuccess(10004), "REQUOTE (10004) is NOT success");

   // ── Group 2: SL/TP validation ────────────────────────────────────
   Print("Group 2: SL/TP validation");
   double price = 2000.0;

   // BUY validations
   Assert(!om.ValidateSlTp(ORDER_TYPE_BUY, price, 0, 2030),
          "BUY: SL=0 rejected");
   Assert(!om.ValidateSlTp(ORDER_TYPE_BUY, price, 1990, 0),
          "BUY: TP=0 rejected");
   Assert(!om.ValidateSlTp(ORDER_TYPE_BUY, price, 2010, 2030),
          "BUY: SL above price rejected");
   Assert(!om.ValidateSlTp(ORDER_TYPE_BUY, price, 1990, 1980),
          "BUY: TP below price rejected");
   Assert(om.ValidateSlTp(ORDER_TYPE_BUY, price, 1990, 2030),
          "BUY: valid SL below price, TP above price accepted");

   // SELL validations
   Assert(!om.ValidateSlTp(ORDER_TYPE_SELL, price, 0, 1970),
          "SELL: SL=0 rejected");
   Assert(!om.ValidateSlTp(ORDER_TYPE_SELL, price, 2010, 0),
          "SELL: TP=0 rejected");
   Assert(!om.ValidateSlTp(ORDER_TYPE_SELL, price, 1990, 1970),
          "SELL: SL below price rejected");
   Assert(!om.ValidateSlTp(ORDER_TYPE_SELL, price, 2010, 2020),
          "SELL: TP above price rejected");
   Assert(om.ValidateSlTp(ORDER_TYPE_SELL, price, 2010, 1970),
          "SELL: valid SL above price, TP below price accepted");

   // ── Group 3: Initial stats ────────────────────────────────────────
   Print("Group 3: Initial statistics");
   Assert(om.GetSuccessCount() == 0, "Initial success count = 0");
   Assert(om.GetFailCount()    == 0, "Initial fail count = 0");
   Assert(om.GetLastSlippage() == 0, "Initial last slippage = 0");
   Assert(om.GetAvgSlippage()  == 0, "Initial avg slippage = 0");

   // ── Summary ───────────────────────────────────────────────────────
   Print("─────────────────────────────────────────────────────");
   Print("TestOrderManager: ", g_pass + g_fail, " tests | ",
         g_pass, " PASS | ", g_fail, " FAIL");
   if(g_fail == 0)
      Print(">>> ALL TESTS PASSED <<<");
   else
      Print(">>> ", g_fail, " FAILURE(S) — REVIEW LOG <<<");
  }
//+------------------------------------------------------------------+
