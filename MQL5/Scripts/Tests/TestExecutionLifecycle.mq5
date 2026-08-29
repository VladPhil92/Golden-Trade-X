//+------------------------------------------------------------------+
//|                                      TestExecutionLifecycle.mq5  |
//| Golden Trade X — execution lifecycle fail-closed verification   |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <Trade/Trade.mqh>
#include <GoldenTradeX/OrderManager.mqh>

int g_pass = 0;
int g_fail = 0;

void AssertTrue(bool condition, string label)
  {
   if(condition) { g_pass++; Print("[PASS] ", label); }
   else          { g_fail++; Print("[FAIL] ", label); }
  }

void OnStart()
  {
   Print("=== TestExecutionLifecycle BEGIN ===");

   CTrade trade;
   COrderManager orders;
   orders.Init(&trade, 0, 0);

   // No identity exists before a server-confirmed open deal.
   AssertTrue(orders.ResolveLastPositionTicket("EURUSD") == 0,
              "No confirmed position identity resolves to ticket 0");

   // Unsupported order kinds must not sneak through the market-entry geometry guard.
   AssertTrue(!orders.ValidateInitialStops(ORDER_TYPE_BUY_LIMIT, 2000.0, 1990.0, 2030.0),
              "Pending BUY_LIMIT rejected by market-entry guard");
   AssertTrue(!orders.ValidateInitialStops(ORDER_TYPE_SELL_LIMIT, 2000.0, 2010.0, 1970.0),
              "Pending SELL_LIMIT rejected by market-entry guard");

   // Missing/invalid tickets fail before any broker modification request is made.
   AssertTrue(!orders.ModifyPosition(0, 1.0, 2.0),
              "Modify ticket 0 fails closed");
   AssertTrue(!orders.ModifyPosition(999999999, 1.0, 2.0),
              "Modify unknown ticket fails closed");

   // Production classification contract for temporary failures.
   uint retryCodes[] = {
      OM_RETCODE_REQUOTE,
      OM_RETCODE_PRICE_CHANGED,
      OM_RETCODE_PRICE_OFF,
      OM_RETCODE_TOO_MANY_REQ,
      OM_RETCODE_CONNECTION,
      OM_RETCODE_TIMEOUT,
      OM_RETCODE_LOCKED
   };
   for(int i = 0; i < ArraySize(retryCodes); i++)
      AssertTrue(orders.ClassifyRetcode(retryCodes[i]) == OM_RESULT_RETRYABLE,
                 "Transient broker code remains retryable: " + IntegerToString((int)retryCodes[i]));

   uint fatalCodes[] = {
      OM_RETCODE_NO_MONEY,
      OM_RETCODE_TRADE_DISABLED,
      OM_RETCODE_SERVER_AT_OFF,
      OM_RETCODE_CLIENT_AT_OFF
   };
   for(int i = 0; i < ArraySize(fatalCodes); i++)
      AssertTrue(orders.ClassifyRetcode(fatalCodes[i]) == OM_RESULT_FATAL,
                 "Fatal broker code remains fatal: " + IntegerToString((int)fatalCodes[i]));

   uint rejectedCodes[] = {
      OM_RETCODE_INVALID_STOPS,
      OM_RETCODE_MARKET_CLOSED,
      OM_RETCODE_FROZEN,
      OM_RETCODE_PLACED,
      OM_RETCODE_NO_CHANGES
   };
   for(int i = 0; i < ArraySize(rejectedCodes); i++)
      AssertTrue(orders.ClassifyRetcode(rejectedCodes[i]) == OM_RESULT_REJECTED,
                 "Non-confirmed broker code remains rejected: " + IntegerToString((int)rejectedCodes[i]));

   AssertTrue(orders.ClassifyRetcode(99999) == OM_RESULT_UNKNOWN,
              "Unknown broker code never becomes success");
   AssertTrue(orders.GetSuccessCount() == 0,
              "Fail-closed lifecycle test creates no successful order");

   Print("=== TestExecutionLifecycle END | PASS=", g_pass,
         " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " FAILURE(S) — REVIEW LOG <<<");
  }
//+------------------------------------------------------------------+
