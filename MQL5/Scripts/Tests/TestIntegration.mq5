//+------------------------------------------------------------------+
//|                                              TestIntegration.mq5 |
//| Golden Trade X — deterministic cross-module integration smoke   |
//+------------------------------------------------------------------+
//  Exercises production APIs together without broker connectivity,
//  orders, DLLs or market-history synchronization. This is an L3-lite
//  integration contract; broker/history ownership reconciliation and the
//  Strategy Tester remain later validation layers and are not implied here.
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <Trade/Trade.mqh>
#include <GoldenTradeX/SessionFilter.mqh>
#include <GoldenTradeX/NewsFilter.mqh>
#include <GoldenTradeX/MarketRegimeEngine.mqh>
#include <GoldenTradeX/SmartMoneyEngine.mqh>
#include <GoldenTradeX/ConfidenceEngine.mqh>
#include <GoldenTradeX/RiskManager.mqh>
#include <GoldenTradeX/OrderManager.mqh>
#include <GoldenTradeX/PositionStateManager.mqh>

int g_pass = 0;
int g_fail = 0;

void AssertTrue(bool condition, string label)
  {
   if(condition) { g_pass++; Print("  PASS  ", label); }
   else          { g_fail++; Print("  FAIL  ", label); }
  }

void AssertEq(int actual, int expected, string label)
  { AssertTrue(actual == expected, label + " got=" + IntegerToString(actual)); }

datetime MakeTime(int year, int mon, int day, int hour, int minute = 0)
  {
   MqlDateTime dt;
   ZeroMemory(dt);
   dt.year = year;
   dt.mon = mon;
   dt.day = day;
   dt.hour = hour;
   dt.min = minute;
   return StructToTime(dt);
  }

void OnStart()
  {
   Print("=== TestIntegration BEGIN ===");

   // 1) Session gate: deterministic server-time evaluation.
   CSessionFilter session;
   session.Init(true, 7, 20, true, 19);
   datetime monday = MakeTime(2026, 8, 24, 12, 0);
   AssertTrue(session.IsTradingAllowedAt(monday), "Session gate allows Monday 12:00 server time");

   // 2) News gate: inject server offset. 2026-01-28 is official FOMC date;
   // decision 14:00 ET = 19:00 UTC in January => 21:00 at UTC+2 server.
   CNewsFilter news;
   news.Init(true, 30, 90);
   news.SetServerOffset(2);
   datetime fomc = MakeTime(2026, 1, 28, 21, 0);
   AssertTrue(news.IsNewsBlockedAt(fomc), "News gate blocks official FOMC window");

   // 3) Market regime -> confluence integration, entirely pure.
   CMarketRegimeEngine regime;
   int regimeScore = regime.ScoreForRegime(REGIME_TRENDING_BULL, true);
   AssertEq(regimeScore, 25, "Bull regime contributes max BUY score");

   CSmartMoneyEngine smc;
   SSmcContext ctx;
   ZeroMemory(ctx);
   ctx.bos = SMC_BULLISH;
   ctx.hasBullFvg = true;
   int smcScore = smc.SmcScore(ctx, true);
   AssertEq(smcScore, 20, "Bull BOS+FVG contributes deterministic SMC score");

   CConfidenceEngine confidence;
   AssertTrue(confidence.Init("TEST", PERIOD_M15, false, 50),
              "Confidence engine initializes without market handles when HTF disabled");
   SConfidenceResult score = confidence.Compute(true, true, regimeScore, smcScore, 20);
   AssertTrue(score.total >= 55, "Integrated confluence clears default entry threshold");
   AssertTrue(score.isBuy && !score.isSell, "Integrated direction remains BUY");
   confidence.Release();

   // 4) Execution classification: temporary broker result remains retryable;
   // no CTrade request is performed in this integration test.
   CTrade trade;
   COrderManager orders;
   orders.Init(&trade, 3, 0);
   AssertTrue(orders.ClassifyRetcode(OM_RETCODE_PRICE_CHANGED) == OM_RESULT_RETRYABLE,
              "Execution layer classifies PRICE_CHANGED as retryable");
   AssertTrue(orders.ClassifyRetcode(OM_RETCODE_NO_MONEY) == OM_RESULT_FATAL,
              "Execution layer classifies NO_MONEY as fatal");

   // 5) Risk-state integration: consecutive losses change observable sizing
   // and trip the configured limit, then a win restores normal state.
   const ulong testMagic = 992631;
   CRiskManager risk;
   risk.Init(1.0, 4.0, 1, 350, testMagic, 3, 8.0);
   risk.RegisterTradeResult(1.0); // deterministic reset of persisted test key
   risk.RegisterTradeResult(-1.0);
   risk.RegisterTradeResult(-1.0);
   AssertTrue(MathAbs(risk.GetPositionSizeMultiplier() - 0.75) < 1e-9,
              "Risk layer reduces size after two consecutive losses");
   risk.RegisterTradeResult(-1.0);
   AssertTrue(risk.IsConsecutiveLossLimitReached(),
              "Risk layer trips three-loss guard");
   risk.RegisterTradeResult(1.0);
   AssertTrue(!risk.IsConsecutiveLossLimitReached(),
              "Positive result clears consecutive-loss guard");

   // 6) Position-state identity smoke. Enumerating live positions is local and
   // deterministic; history ownership (`HistorySelectByPosition`) is purposely
   // excluded because it requires broker/history synchronization and belongs to
   // Strategy Tester or broker-backed integration validation.
   CPositionStateManager state;
   state.Init(testMagic);
   const ulong fakePositionId = 963000001;
   AssertTrue(state.FindPositionTicket(fakePositionId) == 0,
              "Unknown POSITION_IDENTIFIER resolves to no live ticket");

   Print("=== TestIntegration END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
