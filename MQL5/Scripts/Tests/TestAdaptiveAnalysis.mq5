//+------------------------------------------------------------------+
//|                                      TestAdaptiveAnalysis.mq5    |
//| Golden Trade X — deterministic adaptive analysis scoring tests   |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <GoldenTradeX/AdaptiveAnalysisEngine.mqh>

int g_pass = 0;
int g_fail = 0;

void AssertTrue(bool condition, string label)
  {
   if(condition) { g_pass++; Print("  PASS  ", label); }
   else          { g_fail++; Print("  FAIL  ", label); }
  }

void AssertEq(int actual, int expected, string label)
  {
   AssertTrue(actual == expected,
              label + " actual=" + IntegerToString(actual) +
              " expected=" + IntegerToString(expected));
  }

void OnStart()
  {
   Print("=== TestAdaptiveAnalysis BEGIN ===");

   AssertTrue(GtxResolveAnalysisProfile("GOLD", GTX_ANALYSIS_AUTO) == GTX_ANALYSIS_GOLD,
              "AUTO resolves GOLD profile");
   AssertTrue(GtxResolveAnalysisProfile("XAUUSD", GTX_ANALYSIS_AUTO) == GTX_ANALYSIS_GOLD,
              "AUTO resolves XAU profile");
   AssertTrue(GtxResolveAnalysisProfile("BTCUSD", GTX_ANALYSIS_AUTO) == GTX_ANALYSIS_BTC,
              "AUTO resolves BTC profile");

   double spread = GtxSpreadBps(80000.0, 80040.0);
   AssertTrue(MathAbs(spread - 4.9987503124) < 0.000001,
              "BTC spread normalization in bps");

   SAdaptiveMetrics strong;
   ZeroMemory(strong);
   strong.valid = true;
   strong.trendSeparationAtr = 0.65;
   strong.directionalSlopeAtr = 0.50;
   strong.rsi = 62.0;
   strong.adx = 34.0;
   strong.candleEfficiency = 0.75;
   strong.atrBps = 85.0;
   strong.spreadBps = 3.0;
   strong.volumeRatio = 1.30;
   strong.rangePosition = 0.82;
   strong.htfAligned = true;

   SAdaptiveAnalysisResult buy = GtxScoreAdaptiveMetrics(
      strong, true, GTX_ANALYSIS_BTC, 58, 10.0);
   AssertTrue(buy.valid, "Strong snapshot valid");
   AssertTrue(buy.directionAligned, "Strong BUY direction aligned");
   AssertTrue(buy.quality >= 75, "Strong BUY quality high");
   AssertTrue(buy.passed, "Strong BUY passes adaptive gate");

   SAdaptiveMetrics contradictory = strong;
   contradictory.directionalSlopeAtr = -0.20;
   SAdaptiveAnalysisResult badDirection = GtxScoreAdaptiveMetrics(
      contradictory, true, GTX_ANALYSIS_GOLD, 50, 10.0);
   AssertTrue(!badDirection.directionAligned,
              "Contradictory slope fails directional alignment");
   AssertTrue(!badDirection.passed,
              "Contradictory slope cannot pass even with sufficient points");

   SAdaptiveMetrics wide = strong;
   wide.spreadBps = 15.0;
   SAdaptiveAnalysisResult wideSpread = GtxScoreAdaptiveMetrics(
      wide, true, GTX_ANALYSIS_BTC, 50, 10.0);
   AssertTrue(!wideSpread.passed, "Spread above configured bps limit fails");

   SAdaptiveMetrics sellMetrics = strong;
   sellMetrics.directionalSlopeAtr = 0.45;
   sellMetrics.rsi = 38.0;
   sellMetrics.rangePosition = 0.18;
   SAdaptiveAnalysisResult sell = GtxScoreAdaptiveMetrics(
      sellMetrics, false, GTX_ANALYSIS_GOLD, 58, 6.0);
   AssertTrue(sell.directionAligned, "Strong SELL direction aligned");
   AssertTrue(sell.passed, "Strong SELL passes adaptive gate");

   SAdaptiveMetrics invalid;
   ZeroMemory(invalid);
   SAdaptiveAnalysisResult invalidResult = GtxScoreAdaptiveMetrics(
      invalid, true, GTX_ANALYSIS_GENERIC, 0, 0.0);
   AssertTrue(!invalidResult.valid, "Invalid market snapshot fails closed");
   AssertEq(invalidResult.quality, 0, "Invalid snapshot has zero quality");

   Print("=== TestAdaptiveAnalysis END | PASS=", g_pass,
         " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
