//+------------------------------------------------------------------+
//|                                         TestSignalClosedBar.mq5  |
//| Golden Trade X — closed-bar vs legacy continuation signal tests  |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <GoldenTradeX/SignalEngine.mqh>

int g_pass = 0;
int g_fail = 0;

void AssertSignal(ENUM_SIGNAL actual, ENUM_SIGNAL expected, string label)
  {
   if(actual == expected)
     {
      g_pass++;
      Print("  PASS  ", label);
     }
   else
     {
      g_fail++;
      Print("  FAIL  ", label,
            " actual=", IntegerToString((int)actual),
            " expected=", IntegerToString((int)expected));
     }
  }

void OnStart()
  {
   Print("=== TestSignalClosedBar BEGIN ===");

   // Bull crossover confirmed on bars [2] -> [1], but bar [0] has reverted.
   ENUM_SIGNAL closedBuy = GtxEvaluateCrossCandidate(
      99.0, 102.0, 99.0,
      100.0, 100.0, 100.0,
      60.0,
      45.0, 70.0, 30.0, 55.0,
      true);
   AssertSignal(closedBuy, SIGNAL_BUY,
                "Closed-bar candidate keeps confirmed BUY despite bar0 reversion");

   ENUM_SIGNAL legacyBuy = GtxEvaluateCrossCandidate(
      99.0, 102.0, 99.0,
      100.0, 100.0, 100.0,
      60.0,
      45.0, 70.0, 30.0, 55.0,
      false);
   AssertSignal(legacyBuy, SIGNAL_NONE,
                "Legacy candidate still requires bar0 continuation");

   // Bear crossover confirmed on bars [2] -> [1].
   ENUM_SIGNAL closedSell = GtxEvaluateCrossCandidate(
      101.0, 98.0, 101.0,
      100.0, 100.0, 100.0,
      40.0,
      45.0, 70.0, 30.0, 55.0,
      true);
   AssertSignal(closedSell, SIGNAL_SELL,
                "Closed-bar candidate detects confirmed SELL");

   ENUM_SIGNAL weakMomentum = GtxEvaluateCrossCandidate(
      103.0, 102.0, 99.0,
      100.0, 100.0, 100.0,
      40.0,
      45.0, 70.0, 30.0, 55.0,
      true);
   AssertSignal(weakMomentum, SIGNAL_NONE,
                "RSI momentum still blocks invalid BUY");

   Print("=== TestSignalClosedBar END | PASS=", g_pass,
         " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
