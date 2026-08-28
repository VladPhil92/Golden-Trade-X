//+------------------------------------------------------------------+
//|                                               TestFibonacci.mq5 |
//| Golden Trade X — deterministic CFibonacciEngine unit tests      |
//+------------------------------------------------------------------+
//  Tests the production ScoreForRatio() mapping directly. Market-data
//  proximity/swing detection remains a Strategy Tester integration concern.
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <GoldenTradeX/FibonacciEngine.mqh>

int g_pass = 0;
int g_fail = 0;

void Assert(bool condition, string desc)
  {
   if(condition) { g_pass++; Print("  PASS  ", desc); }
   else          { g_fail++; Print("  FAIL  ", desc); }
  }

void OnStart()
  {
   Print("=== TestFibonacci BEGIN ===");
   CFibonacciEngine fib;

   // Invalid context exits before any market-data access.
   SFibContext badCtx;
   ZeroMemory(badCtx);
   Assert(fib.FibScore(badCtx, true)  == 0, "Invalid context BUY = 0");
   Assert(fib.FibScore(badCtx, false) == 0, "Invalid context SELL = 0");

   // Golden ratios.
   Assert(fib.ScoreForRatio(0.382, false, false, true)  == 20, "38.2% BUY neutral = 20");
   Assert(fib.ScoreForRatio(0.618, false, false, false) == 20, "61.8% SELL neutral = 20");

   // 50%.
   Assert(fib.ScoreForRatio(0.500, false, false, true)  == 15, "50% BUY neutral = 15");
   Assert(fib.ScoreForRatio(0.500, false, false, false) == 15, "50% SELL neutral = 15");

   // Outer retracements.
   Assert(fib.ScoreForRatio(0.236, false, false, true)  == 10, "23.6% = 10");
   Assert(fib.ScoreForRatio(0.786, false, false, false) == 10, "78.6% = 10");

   // Extensions/default tier.
   Assert(fib.ScoreForRatio(1.272, false, false, true)  == 5, "127.2% = 5");
   Assert(fib.ScoreForRatio(1.618, false, false, false) == 5, "161.8% = 5");

   // Unfavorable-zone penalty.
   Assert(fib.ScoreForRatio(0.382, true, false, true) == 10,
          "BUY in Premium halves 38.2 score");
   Assert(fib.ScoreForRatio(0.500, true, false, true) == 7,
          "BUY in Premium floors half of 15 to 7");
   Assert(fib.ScoreForRatio(0.382, false, true, false) == 10,
          "SELL in Discount halves 38.2 score");
   Assert(fib.ScoreForRatio(0.500, false, true, false) == 7,
          "SELL in Discount floors half of 15 to 7");

   // Favorable zones are not penalized.
   Assert(fib.ScoreForRatio(0.618, false, true, true) == 20,
          "BUY in Discount remains 20");
   Assert(fib.ScoreForRatio(0.382, true, false, false) == 20,
          "SELL in Premium remains 20");

   // Symmetry and cap.
   int s382 = fib.ScoreForRatio(0.382, false, false, true);
   int s618 = fib.ScoreForRatio(0.618, false, false, true);
   Assert(s382 == s618, "38.2 and 61.8 are symmetric");
   Assert(s382 <= 20, "Score never exceeds 20");

   Print("=== TestFibonacci END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
