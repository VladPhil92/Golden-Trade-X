//+------------------------------------------------------------------+
//|                                         TestPositionState.mq5   |
//|   Golden Trade X v2.62 — PositionState persistence smoke tests  |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs

#include <GoldenTradeX/PositionStateManager.mqh>

int g_pass = 0;
int g_fail = 0;

void Assert(bool condition, string label)
  {
   if(condition) { Print("[PASS] ", label); g_pass++; }
   else          { Print("[FAIL] ", label); g_fail++; }
  }

void OnStart()
  {
   const ulong magic = 992620;
   const ulong fakePid = 987654321;

   CPositionStateManager state;
   state.Init(magic);

   Print("─── TestPositionState ──────────────────────────────");
   Assert(state.FindPositionTicket(fakePid) == 0,
          "Unknown POSITION_IDENTIFIER has no live ticket");
   Assert(!state.IsPositionOpen(fakePid),
          "Unknown POSITION_IDENTIFIER is not open");
   Assert(!state.IsClosureProcessed(fakePid),
          "Closure tombstone initially absent");

   state.MarkClosureProcessed(fakePid);
   Assert(state.IsClosureProcessed(fakePid),
          "Closure tombstone persists by POSITION_IDENTIFIER");

   // Cleanup intentionally preserves CLOSED tombstone to prevent duplicate
   // processing when one close creates multiple DEAL_ENTRY_OUT transactions.
   state.Cleanup(fakePid);
   Assert(state.IsClosureProcessed(fakePid),
          "Cleanup preserves closure tombstone");

   Print("TestPositionState: ", g_pass + g_fail, " tests | ",
         g_pass, " PASS | ", g_fail, " FAIL");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
  }
//+------------------------------------------------------------------+
