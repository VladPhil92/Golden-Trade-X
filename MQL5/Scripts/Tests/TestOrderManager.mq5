//+------------------------------------------------------------------+
//|                                           TestOrderManager.mq5   |
//|   Golden Trade X — Unit tests for COrderManager                  |
//+------------------------------------------------------------------+
//  Tests server retcode classification, the production initial SL/TP
//  guard and clean identity/stat defaults. No live orders are sent.
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <Trade/Trade.mqh>
#include <GoldenTradeX/OrderManager.mqh>

int g_pass = 0;
int g_fail = 0;

void Assert(bool cond, string label)
  {
   if(cond) { Print("[PASS] ", label); g_pass++; }
   else     { Print("[FAIL] ", label); g_fail++; }
  }

void OnStart()
  {
   COrderManager om;
   CTrade trade;
   om.Init(&trade, 3, 100);

   Print("=== TestOrderManager BEGIN ===");

   Assert(om.ClassifyRetcode(10009) == OM_RESULT_SUCCESS,
          "DONE => SUCCESS");
   Assert(om.ClassifyRetcode(10010) == OM_RESULT_PARTIAL_SUCCESS,
          "DONE_PARTIAL => PARTIAL_SUCCESS");

   Assert(om.ClassifyRetcode(10004) == OM_RESULT_RETRYABLE, "REQUOTE => RETRYABLE");
   Assert(om.ClassifyRetcode(10020) == OM_RESULT_RETRYABLE, "PRICE_CHANGED => RETRYABLE");
   Assert(om.ClassifyRetcode(10021) == OM_RESULT_RETRYABLE, "PRICE_OFF => RETRYABLE");
   Assert(om.ClassifyRetcode(10024) == OM_RESULT_RETRYABLE, "TOO_MANY_REQUESTS => RETRYABLE");
   Assert(om.ClassifyRetcode(10031) == OM_RESULT_RETRYABLE, "CONNECTION => RETRYABLE");
   Assert(om.ClassifyRetcode(10012) == OM_RESULT_RETRYABLE, "TIMEOUT => RETRYABLE");
   Assert(om.ClassifyRetcode(10028) == OM_RESULT_RETRYABLE, "LOCKED => RETRYABLE");

   Assert(om.ClassifyRetcode(10019) == OM_RESULT_FATAL, "NO_MONEY => FATAL");
   Assert(om.ClassifyRetcode(10017) == OM_RESULT_FATAL, "TRADE_DISABLED => FATAL");
   Assert(om.ClassifyRetcode(10026) == OM_RESULT_FATAL, "SERVER_AT_OFF => FATAL");
   Assert(om.ClassifyRetcode(10027) == OM_RESULT_FATAL, "CLIENT_AT_OFF => FATAL");

   Assert(om.ClassifyRetcode(10016) == OM_RESULT_REJECTED, "INVALID_STOPS => REJECTED");
   Assert(om.ClassifyRetcode(10018) == OM_RESULT_REJECTED, "MARKET_CLOSED => REJECTED");
   Assert(om.ClassifyRetcode(10029) == OM_RESULT_REJECTED, "FROZEN => REJECTED");
   Assert(om.ClassifyRetcode(10008) == OM_RESULT_REJECTED, "PLACED is not confirmed execution");

   Assert(om.IsRetryableCode(10004), "REQUOTE retryable helper");
   Assert(!om.IsRetryableCode(10016), "INVALID_STOPS not retryable");
   Assert(om.IsFatalCode(10019), "NO_MONEY fatal helper");
   Assert(!om.IsFatalCode(10029), "FROZEN not fatal helper");

   // Production pre-trade stop geometry guard.
   double price = 2000.0;
   Assert(!om.ValidateInitialStops(ORDER_TYPE_BUY, price, 0, 2030),
          "BUY SL=0 rejected");
   Assert(!om.ValidateInitialStops(ORDER_TYPE_BUY, price, 1990, 0),
          "BUY TP=0 rejected");
   Assert(!om.ValidateInitialStops(ORDER_TYPE_BUY, price, 2010, 2030),
          "BUY SL above price rejected");
   Assert(!om.ValidateInitialStops(ORDER_TYPE_BUY, price, 1990, 1980),
          "BUY TP below price rejected");
   Assert(om.ValidateInitialStops(ORDER_TYPE_BUY, price, 1990, 2030),
          "BUY valid SL/TP accepted");

   Assert(!om.ValidateInitialStops(ORDER_TYPE_SELL, price, 0, 1970),
          "SELL SL=0 rejected");
   Assert(!om.ValidateInitialStops(ORDER_TYPE_SELL, price, 2010, 0),
          "SELL TP=0 rejected");
   Assert(!om.ValidateInitialStops(ORDER_TYPE_SELL, price, 1990, 1970),
          "SELL SL below price rejected");
   Assert(!om.ValidateInitialStops(ORDER_TYPE_SELL, price, 2010, 2020),
          "SELL TP above price rejected");
   Assert(om.ValidateInitialStops(ORDER_TYPE_SELL, price, 2010, 1970),
          "SELL valid SL/TP accepted");
   Assert(!om.ValidateInitialStops(ORDER_TYPE_BUY, 0, 1990, 2030),
          "Non-positive entry price rejected");

   Assert(om.GetSuccessCount() == 0, "Initial success count = 0");
   Assert(om.GetFailCount() == 0, "Initial fail count = 0");
   Assert(om.GetLastSlippage() == 0, "Initial last slippage = 0");
   Assert(om.GetAvgSlippage() == 0, "Initial avg slippage = 0");
   Assert(om.GetLastOrderTicket() == 0, "Initial order ticket = 0");
   Assert(om.GetLastDealTicket() == 0, "Initial deal ticket = 0");
   Assert(om.GetLastPositionIdentifier() == 0, "Initial position identifier = 0");
   Assert(om.GetLastPositionTicket() == 0, "Initial position ticket = 0");

   Print("=== TestOrderManager END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " FAILURE(S) — REVIEW LOG <<<");
  }
//+------------------------------------------------------------------+
