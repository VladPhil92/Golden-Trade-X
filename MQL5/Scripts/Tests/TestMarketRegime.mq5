//+------------------------------------------------------------------+
//|                                             TestMarketRegime.mq5 |
//| Golden Trade X — deterministic regime/confluence/SMC unit tests |
//+------------------------------------------------------------------+
//  L2 tests must not require broker connectivity or synchronized market
//  history. Indicator-handle creation/detection belongs to the later
//  terminal/Strategy Tester integration gate. This script verifies the
//  pure production scoring contracts directly.
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
void AssertEq(int a, int b, string label)
  { AssertTrue(a == b, label + " (got=" + IntegerToString(a) + " exp=" + IntegerToString(b) + ")"); }

void OnStart()
  {
   Print("=== TestMarketRegime BEGIN ===");

   //--- Enum serialization
   AssertTrue(RegimeToString(REGIME_TRENDING_BULL) == "TRENDING_BULL", "RegimeToString TRENDING_BULL");
   AssertTrue(RegimeToString(REGIME_TRENDING_BEAR) == "TRENDING_BEAR", "RegimeToString TRENDING_BEAR");
   AssertTrue(RegimeToString(REGIME_RANGING)       == "RANGING",       "RegimeToString RANGING");
   AssertTrue(RegimeToString(REGIME_VOLATILE)      == "VOLATILE",      "RegimeToString VOLATILE");
   AssertTrue(RegimeToString(REGIME_ACCUMULATION)  == "ACCUMULATION",  "RegimeToString ACCUMULATION");
   AssertTrue(RegimeToString(REGIME_DISTRIBUTION)  == "DISTRIBUTION",  "RegimeToString DISTRIBUTION");
   AssertTrue(RegimeToString(REGIME_UNKNOWN)       == "UNKNOWN",       "RegimeToString UNKNOWN");

   //--- Pure regime alignment mapping
   CMarketRegimeEngine regime;
   AssertEq(regime.ScoreForRegime(REGIME_TRENDING_BULL, true),  25, "Bull trend BUY = 25");
   AssertEq(regime.ScoreForRegime(REGIME_TRENDING_BULL, false),  0, "Bull trend SELL = 0");
   AssertEq(regime.ScoreForRegime(REGIME_TRENDING_BEAR, true),   0, "Bear trend BUY = 0");
   AssertEq(regime.ScoreForRegime(REGIME_TRENDING_BEAR, false), 25, "Bear trend SELL = 25");
   AssertEq(regime.ScoreForRegime(REGIME_ACCUMULATION, true),   15, "Accumulation BUY = 15");
   AssertEq(regime.ScoreForRegime(REGIME_ACCUMULATION, false),  15, "Accumulation SELL = 15");
   AssertEq(regime.ScoreForRegime(REGIME_RANGING, true),         5, "Ranging = 5");
   AssertEq(regime.ScoreForRegime(REGIME_DISTRIBUTION, false),   5, "Distribution = 5");
   AssertEq(regime.ScoreForRegime(REGIME_VOLATILE, true),        0, "Volatile BUY = 0");
   AssertEq(regime.ScoreForRegime(REGIME_VOLATILE, false),       0, "Volatile SELL = 0");
   AssertEq(regime.ScoreForRegime(REGIME_UNKNOWN, true),        10, "Unknown neutral = 10");

   //--- Confidence: useHtf=false avoids any indicator handle/data dependency.
   CConfidenceEngine conf;
   AssertTrue(conf.Init("TEST", PERIOD_M15, false, 50), "ConfidenceEngine pure Init succeeds");

   SConfidenceResult r0 = conf.Compute(false, true, 20, 15);
   AssertEq(r0.total, 0, "No base signal => total=0");
   AssertFalse(r0.isBuy,  "No base signal => isBuy=false");
   AssertFalse(r0.isSell, "No base signal => isSell=false");

   SConfidenceResult r1 = conf.Compute(true, true, 25, 30, 20);
   AssertEq(r1.baseSignal, 25, "baseSignal = 25");
   AssertEq(r1.regimeBonus, 25, "regimeBonus = 25");
   AssertEq(r1.smcBonus, 30, "smcBonus = 30");
   AssertEq(r1.htfBonus, 8, "HTF disabled receives neutral 8");
   AssertEq(r1.fibBonus, 5, "Fib score 20 maps to 5");
   AssertEq(r1.total, 93, "Full pure confluence = 93 with HTF neutral");
   AssertTrue(r1.isBuy, "BUY direction preserved");

   SConfidenceResult r2 = conf.Compute(true, false, 0, 0, 0);
   AssertEq(r2.total, 33, "Base-only with neutral HTF = 33");
   AssertTrue(r2.isSell, "SELL direction preserved");
   conf.Release();

   //--- Smart Money scoring is pure over SSmcContext; no Init required.
   CSmartMoneyEngine smc;
   SSmcContext ctx;
   ZeroMemory(ctx);
   AssertEq(smc.SmcScore(ctx, true),  0, "SMC neutral BUY = 0");
   AssertEq(smc.SmcScore(ctx, false), 0, "SMC neutral SELL = 0");

   ctx.bos        = SMC_BULLISH;
   ctx.hasBullFvg = true;
   ctx.hasBullOb  = true;
   AssertEq(smc.SmcScore(ctx, true), 28, "BOS+FVG+OB bull BUY = 28");
   AssertEq(smc.SmcScore(ctx, false), 0, "Bull context contributes 0 to SELL");

   SSmcContext ctx2;
   ZeroMemory(ctx2);
   ctx2.bos   = SMC_BULLISH;
   ctx2.choch = SMC_BULLISH;
   AssertEq(smc.SmcScore(ctx2, true), 17, "BOS+CHOCH bull = 17");

   SSmcContext ctx3;
   ZeroMemory(ctx3);
   ctx3.liquiditySweep = true;
   AssertEq(smc.SmcScore(ctx3, true), 5, "Liquidity sweep = 5");

   SSmcContext ctxMax;
   ZeroMemory(ctxMax);
   ctxMax.bos = SMC_BULLISH;
   ctxMax.choch = SMC_BULLISH;
   ctxMax.hasBullFvg = true;
   ctxMax.hasBullOb = true;
   ctxMax.liquiditySweep = true;
   AssertEq(smc.SmcScore(ctxMax, true), 30, "SMC score clamps at 30");

   Print("=== TestMarketRegime END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
