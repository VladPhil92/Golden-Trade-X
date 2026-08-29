//+------------------------------------------------------------------+
//|                               TestPositionStateRestartStage1.mq5 |
//| Golden Trade X — terminal restart persistence stage 1            |
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
   Print("=== TestPositionStateRestartStage1 BEGIN ===");

   const ulong magic = 993101;
   const ulong positionId = 993101001;

   CPositionStateManager state;
   state.Init(magic);
   state.MarkClosureProcessed(positionId);

   AssertTrue(state.IsClosureProcessed(positionId),
              "Stage 1 writes durable closure tombstone");

   Print("=== TestPositionStateRestartStage1 END | PASS=", g_pass,
         " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " FAILURE(S) — REVIEW LOG <<<");
  }
//+------------------------------------------------------------------+
