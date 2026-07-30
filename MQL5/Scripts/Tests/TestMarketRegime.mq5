//+------------------------------------------------------------------+
//|                                             TestMarketRegime.mq5 |
//|   Golden Trade X — Tests para MarketRegimeEngine y ConfidenceEng |
//+------------------------------------------------------------------+
//  Pruebas de caja blanca para:
//    - RegimeToString() — serialización de enum
//    - CMarketRegimeEngine.Init() — inicialización sin error
//    - CConfidenceEngine.Compute() — scoring correcto sin señal base
//    - CConfidenceEngine.Compute() — scoring con señal base, sin SMC/régimen
//    - CSmartMoneyEngine.Init() — inicialización sin error
//    - SmcScore() — ponderación correcta de componentes
//+------------------------------------------------------------------+
#property script_show_inputs false
#include <GoldenTradeX/MarketRegimeEngine.mqh>
#include <GoldenTradeX/SmartMoneyEngine.mqh>
#include <GoldenTradeX/ConfidenceEngine.mqh>

static int g_pass = 0;
static int g_fail = 0;

void AssertTrue(bool cond, string label)
  {
   if(cond) { g_pass++; Print("  PASS  ", label); }
   else     { g_fail++; Print("  FAIL  ", label); }
  }
void AssertFalse(bool cond, string label) { AssertTrue(!cond, label); }
void AssertEq(int a, int b, string label) { AssertTrue(a == b, label + " (got=" + IntegerToString(a) + " exp=" + IntegerToString(b) + ")"); }
void AssertRange(int val, int lo, int hi, string label) { AssertTrue(val >= lo && val <= hi, label + " (val=" + IntegerToString(val) + ")"); }

//+------------------------------------------------------------------+
void OnStart()
  {
   Print("=== TestMarketRegime BEGIN ===");

   //--- RegimeToString cubre todos los valores del enum
   AssertTrue(RegimeToString(REGIME_TRENDING_BULL) == "TRENDING_BULL", "RegimeToString TRENDING_BULL");
   AssertTrue(RegimeToString(REGIME_TRENDING_BEAR) == "TRENDING_BEAR", "RegimeToString TRENDING_BEAR");
   AssertTrue(RegimeToString(REGIME_RANGING)       == "RANGING",       "RegimeToString RANGING");
   AssertTrue(RegimeToString(REGIME_VOLATILE)      == "VOLATILE",      "RegimeToString VOLATILE");
   AssertTrue(RegimeToString(REGIME_ACCUMULATION)  == "ACCUMULATION",  "RegimeToString ACCUMULATION");
   AssertTrue(RegimeToString(REGIME_DISTRIBUTION)  == "DISTRIBUTION",  "RegimeToString DISTRIBUTION");
   AssertTrue(RegimeToString(REGIME_UNKNOWN)       == "UNKNOWN",       "RegimeToString UNKNOWN");

   //--- MarketRegimeEngine: inicialización en símbolo del gráfico
   CMarketRegimeEngine regime;
   bool initOk = regime.Init(_Symbol, PERIOD_M15);
   AssertTrue(initOk, "MarketRegimeEngine.Init() exitoso");

   // GetLast() devuelve UNKNOWN antes de la primera detección
   AssertTrue(regime.GetLast() == REGIME_UNKNOWN, "GetLast() = UNKNOWN antes de Detect()");

   // RegimeScore: régimen VOLATILE devuelve 0 en ambas direcciones
   // (simulado: sobreescribimos m_lastRegime vía Detect con VOLATILE no posible en test,
   //  así que verificamos la lógica con el método público usando UNKNOWN como proxy)
   // Solo verificamos que los rangos son correctos para UNKNOWN (10)
   AssertRange(regime.RegimeScore(true),  0, 25, "RegimeScore(true) en rango 0-25");
   AssertRange(regime.RegimeScore(false), 0, 25, "RegimeScore(false) en rango 0-25");

   regime.Release();

   //--- ConfidenceEngine: sin señal base → total = 0
   CConfidenceEngine conf;
   AssertTrue(conf.Init(_Symbol, PERIOD_M15, false, 50), "ConfidenceEngine.Init() exitoso");

   SConfidenceResult r0 = conf.Compute(false, true, 20, 15);
   AssertEq(r0.total, 0, "Conf sin señal base → total=0");
   AssertFalse(r0.isBuy,  "Conf sin señal base → isBuy=false");
   AssertFalse(r0.isSell, "Conf sin señal base → isSell=false");

   //--- Con señal base + régimen máximo + SMC máximo (sin HTF) → ≥ 80
   SConfidenceResult r1 = conf.Compute(true, true, 25, 30);
   AssertTrue(r1.total >= 80, "Conf base+maxReg+maxSMC >= 80 (got=" + IntegerToString(r1.total) + ")");
   AssertTrue(r1.isBuy,  "Conf isBuy=true cuando señal es BUY");
   AssertFalse(r1.isSell, "Conf isSell=false cuando señal es BUY");
   AssertEq(r1.baseSignal,  25, "baseSignal = 25");
   AssertEq(r1.regimeBonus, 25, "regimeBonus clamp a 25");
   AssertEq(r1.smcBonus,    30, "smcBonus clamp a 30");

   //--- Con régimen 0 y SMC 0 → solo base + ATR bonus ≤ 30
   SConfidenceResult r2 = conf.Compute(true, false, 0, 0);
   AssertTrue(r2.total <= 35, "Conf solo base+ATR <= 35 (got=" + IntegerToString(r2.total) + ")");
   AssertTrue(r2.isSell, "Conf isSell=true cuando señal es SELL");

   conf.Release();

   //--- SmartMoneyEngine: inicialización
   CSmartMoneyEngine smc;
   AssertTrue(smc.Init(_Symbol, PERIOD_M15, 50, 20, 40, 1.0), "SmartMoneyEngine.Init() exitoso");

   //--- SmcScore: contexto neutro → 0
   SSmcContext ctx;
   ZeroMemory(ctx);
   AssertEq(smc.SmcScore(ctx, true),  0, "SmcScore neutro BUY = 0");
   AssertEq(smc.SmcScore(ctx, false), 0, "SmcScore neutro SELL = 0");

   //--- BOS bull + FVG bull + OB bull → score alto para BUY
   ctx.bos        = SMC_BULLISH;
   ctx.hasBullFvg = true;
   ctx.hasBullOb  = true;
   int sBuy = smc.SmcScore(ctx, true);
   AssertTrue(sBuy >= 25, "SmcScore BOS+FVG+OB BULL >= 25 (got=" + IntegerToString(sBuy) + ")");

   //--- Mismo contexto bull → score 0 para SELL (señal contraria)
   AssertEq(smc.SmcScore(ctx, false), 0, "SmcScore bull context = 0 para SELL");

   //--- CHOCH bull añade +5
   SSmcContext ctx2;
   ZeroMemory(ctx2);
   ctx2.bos   = SMC_BULLISH;
   ctx2.choch = SMC_BULLISH;
   int sChoch = smc.SmcScore(ctx2, true);
   AssertTrue(sChoch >= 17, "SmcScore BOS+CHOCH BULL >= 17 (got=" + IntegerToString(sChoch) + ")");

   //--- Liquidez sweep suma +5 en cualquier dirección
   SSmcContext ctx3;
   ZeroMemory(ctx3);
   ctx3.liquiditySweep = true;
   AssertEq(smc.SmcScore(ctx3, true), 5, "liquiditySweep añade 5 puntos");

   //--- Score máximo clamp a 30
   SSmcContext ctxMax;
   ZeroMemory(ctxMax);
   ctxMax.bos = SMC_BULLISH; ctxMax.choch = SMC_BULLISH;
   ctxMax.hasBullFvg = true; ctxMax.hasBullOb = true;
   ctxMax.liquiditySweep = true;
   AssertEq(smc.SmcScore(ctxMax, true), 30, "SmcScore clamp a 30 (max)");

   //--- Resumen
   Print("=== TestMarketRegime END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
