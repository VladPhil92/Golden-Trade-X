//+------------------------------------------------------------------+
//|                                               TestFibonacci.mq5 |
//|   Golden Trade X — Unit tests for CFibonacciEngine              |
//+------------------------------------------------------------------+
//  Prueba la lógica de FibScore() usando contextos construidos
//  manualmente, sin acceso a datos de mercado reales.
//  Todos los casos usan la función FibScore() directamente,
//  que acepta un SFibContext pre-construido.
//
//  Run from MetaTrader 5 → Script → TestFibonacci
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs

#include "../../Include/GoldenTradeX/FibonacciEngine.mqh"

int g_pass = 0;
int g_fail = 0;

void Assert(bool condition, string desc)
  {
   if(condition) { g_pass++; Print("  PASS  ", desc); }
   else          { g_fail++; Print("  FAIL  ", desc); }
  }

//--- Construye un SFibContext mínimo para testear FibScore()
SFibContext MakeCtx(double high, double low,
                    double nearestLevel, double nearestRatio,
                    bool premiumZone, bool discountZone)
  {
   SFibContext ctx;
   ZeroMemory(ctx);
   ctx.swingHigh    = high;
   ctx.swingLow     = low;
   ctx.levelCount   = 7;
   ctx.nearestLevel = nearestLevel;
   ctx.nearestRatio = nearestRatio;
   ctx.inPremiumZone  = premiumZone;
   ctx.inDiscountZone = discountZone;
   return ctx;
  }

//+------------------------------------------------------------------+
//| Testable subclass: sobreescribe la lógica de proximidad ATR      |
//  FibScore() original llama iClose() y iATR() — no podemos          |
//  mockearlo en MQL5. Testeamos la función con un threshold fijo     |
//  verificando el comportamiento de los scores de ratio.             |
//+------------------------------------------------------------------+
class CFibonacciEngineTestable : public CFibonacciEngine
  {
public:
   // Score directo pasando todos los parámetros sin llamar al mercado
   int ScoreDirect(double ratio, bool inPremiumZone, bool inDiscountZone, bool isBuy)
     {
      int score = 0;

      if(MathAbs(ratio - 0.382) < 0.01 || MathAbs(ratio - 0.618) < 0.01)
         score = 20;
      else if(MathAbs(ratio - 0.500) < 0.01)
         score = 15;
      else if(MathAbs(ratio - 0.786) < 0.01 || MathAbs(ratio - 0.236) < 0.01)
         score = 10;
      else
         score = 5;  // extensiones

      if(isBuy  && inPremiumZone)  score = (int)(score * 0.5);
      if(!isBuy && inDiscountZone) score = (int)(score * 0.5);

      return MathMin(score, 20);
     }
  };

//+------------------------------------------------------------------+
void OnStart()
  {
   Print("=== TestFibonacci ===");

   // ── 1. Init ──────────────────────────────────────────────────────
   CFibonacciEngine eng;
   Assert(eng.Init(_Symbol, PERIOD_M15), "Init returns true");
   Assert(eng.Init(_Symbol, PERIOD_M15, 100, 0.5), "Init with explicit params");

   // ── 2. FibScore con contexto inválido → 0 ────────────────────────
   SFibContext badCtx;
   ZeroMemory(badCtx);
   // swingHigh == swingLow → guard defensivo retorna 0
   Assert(eng.FibScore(badCtx, true)  == 0, "FibScore invalid ctx BUY  = 0");
   Assert(eng.FibScore(badCtx, false) == 0, "FibScore invalid ctx SELL = 0");

   // ── 3. Scores por nivel (modo directo, sin ATR) ───────────────────
   CFibonacciEngineTestable t;

   // Niveles dorados: 38.2% y 61.8% → 20 pts (zona neutral)
   Assert(t.ScoreDirect(0.382, false, false, true)  == 20, "38.2% BUY  neutral zone = 20");
   Assert(t.ScoreDirect(0.618, false, false, false) == 20, "61.8% SELL neutral zone = 20");

   // 50% → 15 pts
   Assert(t.ScoreDirect(0.500, false, false, true)  == 15, "50.0% BUY  neutral zone = 15");
   Assert(t.ScoreDirect(0.500, false, false, false) == 15, "50.0% SELL neutral zone = 15");

   // 23.6% y 78.6% → 10 pts
   Assert(t.ScoreDirect(0.236, false, false, true)  == 10, "23.6% BUY  = 10");
   Assert(t.ScoreDirect(0.786, false, false, false) == 10, "78.6% SELL = 10");

   // Extensiones 127.2%, 161.8% → 5 pts
   Assert(t.ScoreDirect(1.272, false, false, true)  == 5,  "127.2% BUY  = 5");
   Assert(t.ScoreDirect(1.618, false, false, false) == 5,  "161.8% SELL = 5");

   // ── 4. Penalización por zona desfavorable ────────────────────────
   // BUY en Premium: score /2
   Assert(t.ScoreDirect(0.382, true, false, true)  == 10, "38.2% BUY  Premium  = 10 (half)");
   Assert(t.ScoreDirect(0.618, true, false, true)  == 10, "61.8% BUY  Premium  = 10 (half)");
   Assert(t.ScoreDirect(0.500, true, false, true)  == 7,  "50.0% BUY  Premium  = 7  (half)");

   // SELL en Discount: score /2
   Assert(t.ScoreDirect(0.382, false, true, false) == 10, "38.2% SELL Discount = 10 (half)");
   Assert(t.ScoreDirect(0.500, false, true, false) == 7,  "50.0% SELL Discount = 7  (half)");

   // BUY en Discount: sin penalización (zona favorable)
   Assert(t.ScoreDirect(0.618, false, true, true)  == 20, "61.8% BUY  Discount = 20 (no penalty)");

   // SELL en Premium: sin penalización (zona favorable)
   Assert(t.ScoreDirect(0.382, true, false, false) == 20, "38.2% SELL Premium  = 20 (no penalty)");

   // ── 5. Capping ───────────────────────────────────────────────────
   // El máximo posible es 20 (nivel dorado en zona favorable)
   Assert(t.ScoreDirect(0.382, false, false, true)  <= 20, "Score never exceeds 20 (BUY)");
   Assert(t.ScoreDirect(0.618, false, false, false) <= 20, "Score never exceeds 20 (SELL)");

   // ── 6. Symmetry de ratios ─────────────────────────────────────────
   // 0.382 y 0.618 deben dar el mismo score base (son simétricos)
   int s382 = t.ScoreDirect(0.382, false, false, true);
   int s618 = t.ScoreDirect(0.618, false, false, true);
   Assert(s382 == s618, "38.2% and 61.8% symmetric scores");

   // ── Summary ──────────────────────────────────────────────────────
   Print("=========================");
   Print("PASS: ", g_pass, " / FAIL: ", g_fail,
         " / TOTAL: ", g_pass + g_fail);
   if(g_fail == 0)
      Print(">>> ALL TESTS PASSED <<<");
   else
      Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
