//+------------------------------------------------------------------+
//|                               TestPositionStateRestartStage2.mq5 |
//| Golden Trade X — terminal restart persistence stage 2            |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <GoldenTradeX/PositionStateManager.mqh>

int g_pass = 0;
int g_fail = 0;

void AssertTrue(bool condition, string label)
  {
   if(condition) { g_pass++; Print("[PASS] ", label); }
   else          { g_fail++; Print("[FAIL] ", label); }
  }

void OnStart()
  {
   Print("=== TestPositionStateRestartStage2 BEGIN ===");

   // verify-mql5-tests.ps1 launches each Test*.mq5 in a fresh terminal
   // process. Stage 1 therefore ran before a genuine terminal restart.
   const ulong magic = 993101;
   const ulong positionId = 993101001;

   CPositionStateManager state;
   state.Init(magic);

   AssertTrue(state.IsClosureProcessed(positionId),
              "Closure tombstone survives terminal restart");

   state.Cleanup(positionId);
   AssertTrue(state.IsClosureProcessed(positionId),
              "Restarted cleanup preserves idempotency tombstone");

   AssertTrue(!state.EnsurePosition(0),
              "Zero position ticket fails closed after restart");
   AssertTrue(!state.EnsurePosition(999999999),
              "Unknown position ticket fails closed after restart");

   Print("=== TestPositionStateRestartStage2 END | PASS=", g_pass,
         " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " FAILURE(S) — REVIEW LOG <<<");
  }
//+------------------------------------------------------------------+
