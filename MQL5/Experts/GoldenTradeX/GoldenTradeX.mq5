//+------------------------------------------------------------------+
//|                                                 GoldenTradeX.mq5 |
//|                    Golden Trade X v2.63 — Expert Advisor          |
//|                    CTG One Technology S.A.S.                      |
//+------------------------------------------------------------------+
#property copyright "CTG One Technology S.A.S."
#property link      "https://github.com/VladPhil92/Golden-Trade-X"
#property version   "2.63"
#property strict
#property description "Golden Trade X v2.63: verificación MQL5 automatizada, integration smoke determinista y gates DevSecOps."

#include <Trade/Trade.mqh>
#include <GoldenTradeX/RiskManager.mqh>
#include <GoldenTradeX/SignalEngine.mqh>
#include <GoldenTradeX/SessionFilter.mqh>
#include <GoldenTradeX/NewsFilter.mqh>
#include <GoldenTradeX/TradeLogger.mqh>
#include <GoldenTradeX/MarketRegimeEngine.mqh>
#include <GoldenTradeX/SmartMoneyEngine.mqh>
#include <GoldenTradeX/ConfidenceEngine.mqh>
#include <GoldenTradeX/FibonacciEngine.mqh>
#include <GoldenTradeX/PartialTakeProfit.mqh>
#include <GoldenTradeX/EquityCurveFilter.mqh>
#include <GoldenTradeX/OrderManager.mqh>
#include <GoldenTradeX/HealthMonitor.mqh>
#include <GoldenTradeX/PositionStateManager.mqh>
#include <GoldenTradeX/ResearchTelemetry.mqh>

input group "=== Identidad ==="
input ulong   InpMagicNumber      = 920260;
input string  InpTradeComment     = "GoldenTradeX";

input group "=== Señales ==="
input int     InpEmaFast          = 21;
input int     InpEmaSlow          = 55;
input int     InpRsiPeriod        = 14;
input double  InpRsiUpper         = 70.0;
input double  InpRsiLower         = 30.0;
input double  InpRsiLongMin       = 45.0;
input double  InpRsiShortMax      = 55.0;
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_M15;
input int     InpAtrPeriod        = 14;
input double  InpAtrMinRatio      = 0.8;
input double  InpAtrMaxRatio      = 3.0;
input int     InpAdxPeriod        = 14;
input double  InpAdxMinLevel      = 25.0;
input int     InpMinTickVolume    = 10;

input group "=== Filtro de Tendencia HTF ==="
input bool    InpUseHtfFilter     = true;
input int     InpHtfEmaPeriod     = 50;

input group "=== Confluence Score & Smart Money (heurístico) ==="
input bool    InpUseRegimeFilter  = true;
input bool    InpUseSmcFilter     = true;
input int     InpMinConfidence    = 55;
input int     InpConfWeightBase   = 25;
input int     InpConfWeightRegime = 25;
input int     InpConfWeightSmc    = 30;
input int     InpConfWeightHtf    = 15;
input int     InpConfWeightFib    = 5;

input group "=== Riesgo ==="
input double  InpRiskPercent      = 1.0;
input double  InpMaxDailyDD       = 4.0;
input double  InpMaxWeeklyDD      = 8.0;
input double  InpMaxMonthlyDD     = 15.0;
input int     InpMaxConsecLosses  = 3;
input int     InpMaxPositions     = 1;
input double  InpAtrSlMultiplier  = 2.0;
input double  InpAtrTpMultiplier  = 3.0;
input double  InpMaxSpreadPoints  = 350;
input double  InpCpThresholdPct   = 8.0;
input double  InpMinInitialRR     = 0.0;  // 0=off hasta research OOS

input group "=== Trailing Stop y Break-Even ==="
input bool    InpUseTrailing      = true;
input double  InpTrailAtrMult     = 1.5;
input bool    InpUseBreakEven     = true;
input double  InpBreakEvenR       = 0.5;

input group "=== Partial Take Profit ==="
input bool    InpUsePartialTP     = true;
input double  InpPartialTPR       = 1.0;
input double  InpPartialTPPct     = 50.0;

input group "=== Equity Curve Filter ==="
input bool    InpUseEqCurveFilter = true;
input int     InpEqCurvePeriod    = 20;

input group "=== Kelly Criterion ==="
input bool    InpUseKelly         = false;
input double  InpKellyFraction    = 0.25;
input int     InpKellyMinTrades   = 30;

input group "=== Portfolio Risk Cap ==="
input bool    InpUsePortfolioCap     = false;
input double  InpMaxPortfolioRiskPct = 1.5;

input group "=== Order Manager ==="
input int     InpOrderMaxRetries  = 3;
input int     InpOrderRetryDelay  = 500;
input double  InpMinMarginLevel   = 200.0;

input group "=== Sesiones ==="
input bool    InpUseSessionFilter = true;
input int     InpStartHour        = 7;
input int     InpEndHour          = 20;
input bool    InpCloseOnFriday    = true;
input int     InpFridayCloseHour  = 19;

input group "=== Noticias ==="
input bool    InpUseNewsFilter    = true;
input int     InpNewsBufferBefore = 30;
input int     InpNewsBufferAfter  = 90;
input ENUM_NEWS_CALENDAR_POLICY InpNewsCalendarPolicy = NEWS_CALENDAR_WARN;
input bool    InpPauseForNews     = false;

input group "=== Registro ==="
input bool    InpEnableTradeLog          = true;
input bool    InpEnableResearchTelemetry = true;

CTrade                trade;
CRiskManager          riskManager;
CSignalEngine         signalEngine;
CSessionFilter        sessionFilter;
CNewsFilter           newsFilter;
CTradeLogger          tradeLogger;
CMarketRegimeEngine   regimeEngine;
CSmartMoneyEngine     smcEngine;
CConfidenceEngine     confEngine;
CFibonacciEngine      fibEngine;
CPartialTP            partialTP;
CEquityCurveFilter    eqCurveFilter;
COrderManager         orderMgr;
CHealthMonitor        healthMonitor;
CPositionStateManager positionState;
CResearchTelemetry    researchTelemetry;

datetime g_lastBarTime = 0;
string   g_gvLastBarKey = "";
int      g_lastConfidence = 0;
ENUM_MARKET_REGIME g_lastRegime = REGIME_UNKNOWN;

void LogResearchGuard(string reason)
  {
   researchTelemetry.LogSignal(g_lastBarTime,
                               "GUARD", "REJECTED", reason, "NONE",
                               -1, (int)g_lastRegime,
                               0, 0, 0, 0, 0,
                               0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
  }

bool PositionIdentifierIsOpen(ulong positionId)
  { return positionState.IsPositionOpen(positionId); }

bool PositionHistoryBelongsExclusivelyToEA(ulong positionId)
  { return positionState.PositionBelongsExclusivelyToEA(positionId); }

bool HasForeignNettingPosition(string symbol)
  {
   ENUM_ACCOUNT_MARGIN_MODE marginMode =
      (ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(marginMode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING) return false;
   if(!PositionSelect(symbol)) return false;
   long magic = PositionGetInteger(POSITION_MAGIC);
   if(magic == (long)InpMagicNumber) return false;

   Print("GoldenTradeX: FAIL-CLOSED netting — existe posición en ", symbol,
         " con magic=", magic,
         ". No se mezclará ownership dentro de una posición netting.");
   return true;
  }

int OnInit()
  {
   if(InpEmaFast >= InpEmaSlow)
     { Print("GoldenTradeX: InpEmaFast debe ser menor que InpEmaSlow"); return INIT_PARAMETERS_INCORRECT; }
   if(InpRsiLower >= InpRsiUpper)
     { Print("GoldenTradeX: InpRsiLower debe ser menor que InpRsiUpper"); return INIT_PARAMETERS_INCORRECT; }
   if(InpRsiLongMin >= InpRsiUpper || InpRsiShortMax <= InpRsiLower)
     { Print("GoldenTradeX: rangos RSI de momentum inconsistentes"); return INIT_PARAMETERS_INCORRECT; }
   if(InpRiskPercent <= 0 || InpRiskPercent > 10)
     { Print("GoldenTradeX: InpRiskPercent fuera de rango (0-10%)"); return INIT_PARAMETERS_INCORRECT; }
   if(InpBreakEvenR <= 0)
     { Print("GoldenTradeX: InpBreakEvenR debe ser > 0"); return INIT_PARAMETERS_INCORRECT; }
   if(InpMinConfidence < 0 || InpMinConfidence > 100)
     { Print("GoldenTradeX: InpMinConfidence debe ser 0-100"); return INIT_PARAMETERS_INCORRECT; }
   if(InpMinInitialRR < 0)
     { Print("GoldenTradeX: InpMinInitialRR no puede ser negativo"); return INIT_PARAMETERS_INCORRECT; }
   if(InpPartialTPR <= 0)
     { Print("GoldenTradeX: InpPartialTPR debe ser > 0"); return INIT_PARAMETERS_INCORRECT; }
   if(InpPartialTPPct <= 0 || InpPartialTPPct >= 100)
     { Print("GoldenTradeX: InpPartialTPPct debe estar en (0,100)"); return INIT_PARAMETERS_INCORRECT; }
   if(InpAtrSlMultiplier <= 0 || InpAtrTpMultiplier <= 0 || InpTrailAtrMult <= 0)
     { Print("GoldenTradeX: multiplicadores ATR deben ser > 0"); return INIT_PARAMETERS_INCORRECT; }

   ENUM_ACCOUNT_TRADE_MODE mode = (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   Print("GoldenTradeX: cuenta tipo=",
         mode == ACCOUNT_TRADE_MODE_DEMO ? "DEMO" :
         mode == ACCOUNT_TRADE_MODE_REAL ? "REAL (¡DINERO REAL!)" : "CONTEST",
         " broker=", AccountInfoString(ACCOUNT_COMPANY),
         " divisa=", AccountInfoString(ACCOUNT_CURRENCY),
         " login=", AccountInfoInteger(ACCOUNT_LOGIN));

   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
     { Print("GoldenTradeX: Trading NO permitido en el terminal."); return INIT_FAILED; }
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
     { Print("GoldenTradeX: MQL Trade NOT ALLOWED."); return INIT_FAILED; }

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(_Symbol);

   if(!signalEngine.Init(_Symbol, InpTimeframe,
                         InpEmaFast, InpEmaSlow,
                         InpRsiPeriod, InpRsiUpper, InpRsiLower,
                         InpRsiLongMin, InpRsiShortMax,
                         InpAtrPeriod, InpAtrMinRatio,
                         InpAdxMinLevel, InpAtrMaxRatio,
                         InpUseHtfFilter, InpHtfEmaPeriod,
                         (long)InpMinTickVolume, InpAdxPeriod))
     { Print("GoldenTradeX: error inicializando SignalEngine"); return INIT_FAILED; }

   riskManager.Init(InpRiskPercent, InpMaxDailyDD, InpMaxPositions,
                    InpMaxSpreadPoints, InpMagicNumber,
                    InpMaxConsecLosses, InpMaxWeeklyDD,
                    InpMaxMonthlyDD, InpCpThresholdPct);

   sessionFilter.Init(InpUseSessionFilter, InpStartHour, InpEndHour,
                      InpCloseOnFriday, InpFridayCloseHour);
   newsFilter.Init(InpUseNewsFilter, InpNewsBufferBefore, InpNewsBufferAfter,
                   InpNewsCalendarPolicy);
   tradeLogger.Init(InpEnableTradeLog, InpMagicNumber);
   researchTelemetry.Init(InpEnableResearchTelemetry, InpMagicNumber,
                          _Symbol, InpTimeframe);

   if(InpUseRegimeFilter)
     {
      if(!regimeEngine.Init(_Symbol, InpTimeframe, InpEmaFast, InpEmaSlow,
                            25.0, 20.0, 2.0, 0.70, InpAtrPeriod, InpAdxPeriod))
        { Print("GoldenTradeX: error inicializando MarketRegimeEngine"); return INIT_FAILED; }
     }

   if(InpUseSmcFilter)
     {
      if(!smcEngine.Init(_Symbol, InpTimeframe, 50, 20, 40, 1.0, InpAtrPeriod))
        { Print("GoldenTradeX: error inicializando SmartMoneyEngine"); return INIT_FAILED; }
     }

   if(!confEngine.Init(_Symbol, InpTimeframe, InpUseHtfFilter, InpHtfEmaPeriod,
                       InpConfWeightBase, InpConfWeightRegime, InpConfWeightSmc,
                       InpConfWeightHtf, InpConfWeightFib))
     { Print("GoldenTradeX: error inicializando ConfidenceEngine"); return INIT_FAILED; }

   if(!fibEngine.Init(_Symbol, InpTimeframe, 100, 0.5, InpAtrPeriod))
     { Print("GoldenTradeX: error inicializando FibonacciEngine"); return INIT_FAILED; }

   partialTP.Init(InpUsePartialTP, InpMagicNumber);
   eqCurveFilter.Init(InpUseEqCurveFilter, InpEqCurvePeriod, InpMagicNumber);
   orderMgr.Init(&trade, InpOrderMaxRetries, InpOrderRetryDelay);
   if(!healthMonitor.Init(_Symbol, InpTimeframe, InpMagicNumber, InpMinMarginLevel,
                          3.0, 60, InpAtrPeriod))
     { Print("GoldenTradeX: error inicializando HealthMonitor"); return INIT_FAILED; }

   positionState.Init(InpMagicNumber);
   int rebuilt = positionState.ReconcileOpenPositions();
   if(rebuilt > 0)
      Print("GoldenTradeX: PositionState reconciliado: ", rebuilt, " estado(s).");

   riskManager.InitKelly(InpUseKelly, InpKellyFraction, InpKellyMinTrades);
   riskManager.InitPortfolioCap(InpUsePortfolioCap, InpMaxPortfolioRiskPct);

   g_gvLastBarKey = StringFormat("GTX_%d_LastBar", (int)InpMagicNumber);
   g_lastBarTime = (datetime)GlobalVariableGet(g_gvLastBarKey);

   EventSetTimer(60);
   newsFilter.PrintStatus();
   riskManager.PrintStatus();
   Print("GoldenTradeX v2.63 inicializado en ", _Symbol,
         " | MinConf=", InpMinConfidence,
         " | MinRR=", DoubleToString(InpMinInitialRR, 2),
         " | Retries=", InpOrderMaxRetries,
         " | PartialTP=", InpUsePartialTP ? "ON" : "OFF",
         " | EqFilter=", InpUseEqCurveFilter ? "ON" : "OFF",
         " | Kelly=", InpUseKelly ? "ON" : "OFF",
         " | PortfolioCap=", InpUsePortfolioCap ? "ON" : "OFF",
         " | ResearchTelemetry=", InpEnableResearchTelemetry ? "ON" : "OFF");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   signalEngine.Release();
   regimeEngine.Release();
   confEngine.Release();
   smcEngine.Release();
   fibEngine.Release();
   healthMonitor.Release();
   orderMgr.PrintStats();
   Print("GoldenTradeX: deinit razón=", reason);
  }

void OnTimer()
  {
   healthMonitor.Check(trade);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber) continue;
      positionState.UpdateExcursions(ticket);
     }
  }

void OnTick()
  {
   if(sessionFilter.MustCloseAll())
     { CloseAllPositions("Cierre de fin de semana"); return; }

   ManageOpenPositions();

   if(!IsNewBar()) return;
   eqCurveFilter.Sample();

   if(riskManager.IsKillSwitchActive())
     {
      LogResearchGuard("KILL_SWITCH");
      Comment("GoldenTradeX: KILL SWITCH activo. Operaciones detenidas.");
      return;
     }
   if(!sessionFilter.IsTradingAllowed())
     { LogResearchGuard("SESSION_BLOCKED"); return; }
   if(!riskManager.IsSpreadAcceptable(_Symbol))
     { LogResearchGuard("SPREAD_TOO_WIDE"); return; }
   if(riskManager.IsDailyDrawdownExceeded())
     {
      LogResearchGuard("DAILY_DD_LIMIT");
      Comment("GoldenTradeX: DD diario alcanzado. Pausa hasta mañana.");
      return;
     }
   if(riskManager.IsWeeklyDrawdownExceeded())
     {
      LogResearchGuard("WEEKLY_DD_LIMIT");
      Comment("GoldenTradeX: DD semanal alcanzado. Pausa hasta la semana siguiente.");
      return;
     }
   if(riskManager.IsMonthlyCircuitBreakerTripped())
     {
      LogResearchGuard("MONTHLY_CIRCUIT_BREAKER");
      Comment("GoldenTradeX: Circuit Breaker mensual disparado.");
      return;
     }
   if(riskManager.IsConsecutiveLossLimitReached())
     {
      LogResearchGuard("CONSECUTIVE_LOSS_LIMIT");
      Comment("GoldenTradeX: límite de pérdidas consecutivas alcanzado.");
      return;
     }
   if(newsFilter.IsNewsBlocked())
     {
      LogResearchGuard("NEWS_WINDOW");
      Comment("GoldenTradeX: ventana de noticias activa. Esperando...");
      return;
     }
   if(InpPauseForNews)
     {
      LogResearchGuard("MANUAL_NEWS_PAUSE");
      Comment("GoldenTradeX: pausa manual activa.");
      return;
     }
   if(riskManager.CountOpenPositions(_Symbol) >= InpMaxPositions)
     { LogResearchGuard("MAX_POSITIONS"); return; }
   if(HasForeignNettingPosition(_Symbol))
     { LogResearchGuard("FOREIGN_NETTING_POSITION"); return; }
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
     { LogResearchGuard("TERMINAL_DISCONNECTED"); return; }

   if(InpUseRegimeFilter)
     {
      g_lastRegime = regimeEngine.Detect();
      if(g_lastRegime == REGIME_VOLATILE)
        {
         LogResearchGuard("REGIME_VOLATILE");
         Comment("GoldenTradeX: régimen VOLATILE. Sin entradas.");
         return;
        }
     }
   else
      g_lastRegime = REGIME_UNKNOWN;

   ENUM_SIGNAL signal = signalEngine.GetSignal();
   if(signal == SIGNAL_NONE)
     {
      researchTelemetry.LogSignal(g_lastBarTime,
                                  "BASE_SIGNAL", "NO_SIGNAL", "SIGNAL_NONE", "NONE",
                                  0, (int)g_lastRegime,
                                  0, 0, 0, 0, 0,
                                  0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
      return;
     }
   bool isBuy = (signal == SIGNAL_BUY);
   string direction = isBuy ? "BUY" : "SELL";

   int regScore = InpUseRegimeFilter ? regimeEngine.RegimeScore(isBuy) : 15;
   int smcScore = 0;
   if(InpUseSmcFilter)
     {
      SSmcContext smcCtx = smcEngine.Analyze();
      smcScore = smcEngine.SmcScore(smcCtx, isBuy);
     }

   SFibContext fibCtx = fibEngine.Analyze();
   int fibScore = fibEngine.FibScore(fibCtx, isBuy);
   SConfidenceResult conf = confEngine.Compute(true, isBuy, regScore, smcScore, fibScore);
   g_lastConfidence = conf.total;

   researchTelemetry.LogSignal(g_lastBarTime,
                               "CONFLUENCE", "CANDIDATE", "", direction,
                               conf.total, (int)g_lastRegime,
                               conf.baseSignal, conf.regimeBonus, conf.smcBonus,
                               conf.htfBonus, conf.fibBonus,
                               0.0, 0.0, 0.0, 0.0, 0.0, 0.0);

   if(conf.total < InpMinConfidence)
     {
      researchTelemetry.LogSignal(g_lastBarTime,
                                  "CONFLUENCE", "REJECTED", "CONFIDENCE_TOO_LOW", direction,
                                  conf.total, (int)g_lastRegime,
                                  conf.baseSignal, conf.regimeBonus, conf.smcBonus,
                                  conf.htfBonus, conf.fibBonus,
                                  0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
      Comment("GoldenTradeX: Conf=", conf.total, "/100 < ", InpMinConfidence,
              " | Base=", conf.baseSignal, " Reg=", conf.regimeBonus,
              " SMC=", conf.smcBonus, " HTF=", conf.htfBonus, " Fib=", conf.fibBonus);
      return;
     }

   if(riskManager.IsCapitalPreservationActive())
      Print("GoldenTradeX: Capital Preservation Mode activo.");

   double atr = signalEngine.GetATR();
   if(atr <= 0)
     {
      researchTelemetry.LogSignal(g_lastBarTime,
                                  "GEOMETRY", "REJECTED", "ATR_INVALID", direction,
                                  conf.total, (int)g_lastRegime,
                                  conf.baseSignal, conf.regimeBonus, conf.smcBonus,
                                  conf.htfBonus, conf.fibBonus,
                                  atr, 0.0, 0.0, 0.0, 0.0, 0.0);
      return;
     }

   double price, sl, tp;
   ENUM_ORDER_TYPE type;
   if(isBuy)
     {
      type = ORDER_TYPE_BUY;
      price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      sl = price - atr * InpAtrSlMultiplier;
      tp = price + atr * InpAtrTpMultiplier;
      if(fibCtx.swingLow > 0 && fibCtx.swingLow < price)
        {
         double structSL = fibCtx.swingLow - atr * 0.1;
         sl = MathMin(sl, structSL);
        }
     }
   else
     {
      type = ORDER_TYPE_SELL;
      price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      sl = price + atr * InpAtrSlMultiplier;
      tp = price - atr * InpAtrTpMultiplier;
      if(fibCtx.swingHigh > 0 && fibCtx.swingHigh > price)
        {
         double structSL = fibCtx.swingHigh + atr * 0.1;
         sl = MathMax(sl, structSL);
        }
     }

   double riskDistance = MathAbs(price - sl);
   double rewardDistance = MathAbs(tp - price);
   if(riskDistance <= 0 || rewardDistance <= 0)
     {
      researchTelemetry.LogSignal(g_lastBarTime,
                                  "GEOMETRY", "REJECTED", "INVALID_RISK_REWARD_DISTANCE", direction,
                                  conf.total, (int)g_lastRegime,
                                  conf.baseSignal, conf.regimeBonus, conf.smcBonus,
                                  conf.htfBonus, conf.fibBonus,
                                  atr, price, sl, tp, 0.0, 0.0);
      return;
     }
   double initialRR = rewardDistance / riskDistance;
   if(InpMinInitialRR > 0 && initialRR < InpMinInitialRR)
     {
      researchTelemetry.LogSignal(g_lastBarTime,
                                  "RR", "REJECTED", "RR_TOO_LOW", direction,
                                  conf.total, (int)g_lastRegime,
                                  conf.baseSignal, conf.regimeBonus, conf.smcBonus,
                                  conf.htfBonus, conf.fibBonus,
                                  atr, price, sl, tp, initialRR, 0.0);
      Print("GoldenTradeX: RR_TOO_LOW — RR=", DoubleToString(initialRR, 3),
            " < mínimo=", DoubleToString(InpMinInitialRR, 3));
      Comment("GoldenTradeX: RR inicial insuficiente: ", DoubleToString(initialRR, 2));
      return;
     }

   double lots = riskManager.CalculateLotSize(_Symbol, price, sl);
   if(lots <= 0)
     {
      researchTelemetry.LogSignal(g_lastBarTime,
                                  "SIZING", "REJECTED", "LOT_SIZE_INVALID", direction,
                                  conf.total, (int)g_lastRegime,
                                  conf.baseSignal, conf.regimeBonus, conf.smcBonus,
                                  conf.htfBonus, conf.fibBonus,
                                  atr, price, sl, tp, initialRR, lots);
      return;
     }

   double eqMult = eqCurveFilter.GetMultiplier();
   if(eqMult < 1.0)
     {
      double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
      double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      if(lotStep <= 0)
        {
         researchTelemetry.LogSignal(g_lastBarTime,
                                     "SIZING", "REJECTED", "VOLUME_STEP_INVALID", direction,
                                     conf.total, (int)g_lastRegime,
                                     conf.baseSignal, conf.regimeBonus, conf.smcBonus,
                                     conf.htfBonus, conf.fibBonus,
                                     atr, price, sl, tp, initialRR, lots);
         return;
        }
      lots = MathFloor(lots * eqMult / lotStep) * lotStep;
      if(lots < minLot)
        {
         researchTelemetry.LogSignal(g_lastBarTime,
                                     "SIZING", "REJECTED", "EQUITY_FILTER_BELOW_MIN_LOT", direction,
                                     conf.total, (int)g_lastRegime,
                                     conf.baseSignal, conf.regimeBonus, conf.smcBonus,
                                     conf.htfBonus, conf.fibBonus,
                                     atr, price, sl, tp, initialRR, lots);
         return;
        }
      Print("GoldenTradeX: EqCurveFilter — lote reducido (equity<EMA).");
     }

   string comment = StringFormat("%s|Conf=%d|Reg=%s",
                                  InpTradeComment, conf.total,
                                  RegimeToString(g_lastRegime));

   researchTelemetry.LogSignal(g_lastBarTime,
                               "EXECUTION", "ORDER_REQUESTED", "", direction,
                               conf.total, (int)g_lastRegime,
                               conf.baseSignal, conf.regimeBonus, conf.smcBonus,
                               conf.htfBonus, conf.fibBonus,
                               atr, price, sl, tp, initialRR, lots);

   double requestedSL = NormalizeDouble(sl, _Digits);
   double requestedTP = NormalizeDouble(tp, _Digits);
   bool ok = orderMgr.OpenPosition(_Symbol, type, lots, price,
                                   requestedSL,
                                   requestedTP,
                                   comment);

   ulong telemetryOrder = orderMgr.GetLastOrderTicket();
   ulong telemetryDeal = orderMgr.GetLastDealTicket();
   ulong telemetryPositionId = orderMgr.GetLastPositionIdentifier();
   ulong telemetryPositionTicket = orderMgr.GetLastPositionTicket();
   double confirmedPrice = ok ? trade.ResultPrice() : 0.0;
   double confirmedVolume = ok ? trade.ResultVolume() : 0.0;
   double confirmedSlippage = ok ? orderMgr.GetLastSlippage() : 0.0;

   researchTelemetry.LogOrderResult("OPEN",
                                    ok ? "SERVER_CONFIRMED" : "FAILED",
                                    direction,
                                    price, requestedSL, requestedTP, lots,
                                    trade.ResultRetcode(),
                                    (int)orderMgr.GetLastResultClass(),
                                    confirmedPrice, confirmedVolume, confirmedSlippage,
                                    telemetryOrder, telemetryDeal,
                                    telemetryPositionId, telemetryPositionTicket,
                                    trade.ResultComment());

   researchTelemetry.LogSignal(g_lastBarTime,
                               "EXECUTION",
                               ok ? "OPEN_CONFIRMED" : "OPEN_FAILED",
                               ok ? "SERVER_CONFIRMED" : trade.ResultComment(),
                               direction,
                               conf.total, (int)g_lastRegime,
                               conf.baseSignal, conf.regimeBonus, conf.smcBonus,
                               conf.htfBonus, conf.fibBonus,
                               atr, price, sl, tp, initialRR, lots,
                               telemetryPositionId, telemetryOrder, telemetryDeal);

   if(ok)
     {
      ulong positionId = telemetryPositionId;
      ulong positionTicket = telemetryPositionTicket;
      if(positionTicket == 0)
         positionTicket = orderMgr.ResolveLastPositionTicket(_Symbol);

      if(positionId == 0 || positionTicket == 0 ||
         !positionState.EnsurePosition(positionTicket, conf.total, (int)g_lastRegime))
        {
         Print("GoldenTradeX: SEV0 — apertura confirmada pero PositionState no pudo ",
               "reconciliar identidad/Initial R. Kill Switch activado. position_id=",
               positionId, " ticket=", positionTicket);
         riskManager.SetKillSwitch(true);
         return;
        }

      if(InpUsePortfolioCap)
        {
         if(!PositionSelectByTicket(positionTicket))
           {
            Print("GoldenTradeX: SEV0 — posición confirmada no seleccionable para registrar riesgo.");
            riskManager.SetKillSwitch(true);
            return;
           }
         double realSl = PositionGetDouble(POSITION_SL);
         double realOpen = PositionGetDouble(POSITION_PRICE_OPEN);
         double realLots = PositionGetDouble(POSITION_VOLUME);
         double riskPct = riskManager.CalcRiskPctForPosition(_Symbol, realOpen, realSl, realLots);
         if(riskPct <= 0)
           {
            Print("GoldenTradeX: SEV0 — riesgo real no calculable tras apertura confirmada.");
            riskManager.SetKillSwitch(true);
            return;
           }
         riskManager.RegisterOpenRisk(positionId, riskPct);
        }
     }
   else if(orderMgr.LastErrorIsFatal())
     {
      Print("GoldenTradeX: error fatal al abrir posición — activando Kill Switch.");
      riskManager.SetKillSwitch(true);
     }
  }

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(trans.deal_type != DEAL_TYPE_BUY && trans.deal_type != DEAL_TYPE_SELL) return;

   ulong dealTicket = trans.deal;
   if(dealTicket == 0 || !HistoryDealSelect(dealTicket)) return;

   long entry = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
   long dealMagic = HistoryDealGetInteger(dealTicket, DEAL_MAGIC);

   if(entry == DEAL_ENTRY_IN)
     {
      if(dealMagic == (long)InpMagicNumber)
         researchTelemetry.LogDeal(dealTicket);
      return;
     }

   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT) return;

   ulong positionId = (ulong)HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);
   if(positionId == 0) return;
   if(!PositionHistoryBelongsExclusivelyToEA(positionId)) return;

   // Exit deals can be manual/broker-side (magic 0). Ownership is proven from
   // the position history before the immutable deal is admitted to research.
   researchTelemetry.LogDeal(dealTicket);

   if(PositionIdentifierIsOpen(positionId))
     {
      Print("GoldenTradeX: cierre parcial position_id=", positionId,
            " — posición sigue abierta; no se contabiliza como trade final.");
      return;
     }

   if(positionState.IsClosureProcessed(positionId)) return;

   double posNet = 0.0;
   if(!HistorySelectByPosition(positionId)) return;
   for(int i = 0; i < HistoryDealsTotal(); i++)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0) continue;
      long e = HistoryDealGetInteger(d, DEAL_ENTRY);
      if(e != DEAL_ENTRY_OUT && e != DEAL_ENTRY_INOUT) continue;
      posNet += HistoryDealGetDouble(d, DEAL_PROFIT)
              + HistoryDealGetDouble(d, DEAL_COMMISSION)
              + HistoryDealGetDouble(d, DEAL_SWAP)
              + HistoryDealGetDouble(d, DEAL_FEE);
     }

   SPositionState finalState;
   bool hasState = positionState.Load(positionId, finalState);
   if(hasState)
     {
      Print("GoldenTradeX: cierre position_id=", positionId,
            " MFE=", DoubleToString(finalState.mfeR, 2), "R",
            " MAE=", DoubleToString(finalState.maeR, 2), "R");

      long exitType = HistoryDealGetInteger(dealTicket, DEAL_TYPE);
      string direction = exitType == DEAL_TYPE_SELL ? "BUY" : "SELL";
      datetime closeTime = (datetime)HistoryDealGetInteger(dealTicket, DEAL_TIME);
      string closedSymbol = HistoryDealGetString(dealTicket, DEAL_SYMBOL);
      double closePrice = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
      double realizedR = posNet / finalState.initialRiskMoney;

      researchTelemetry.LogPositionOutcome(closeTime,
                                           closedSymbol,
                                           positionId,
                                           direction,
                                           finalState.entryTime,
                                           finalState.entryPrice,
                                           finalState.initialSL,
                                           finalState.initialTP,
                                           finalState.initialRiskPrice,
                                           finalState.initialRiskMoney,
                                           finalState.initialVolume,
                                           finalState.confidence,
                                           finalState.regime,
                                           finalState.mfeR,
                                           finalState.mfePrice,
                                           finalState.mfeTime,
                                           finalState.maeR,
                                           finalState.maePrice,
                                           finalState.maeTime,
                                           posNet,
                                           realizedR,
                                           closePrice);
     }
   else
      Print("ResearchTelemetry: outcome omitido — PositionState final no demostrable para position_id=",
            positionId);

   riskManager.RegisterTradeResult(posNet);
   riskManager.ReleaseOpenRisk(positionId);
   tradeLogger.LogTrade(dealTicket);
   partialTP.Cleanup(positionId);
   positionState.MarkClosureProcessed(positionId);
   positionState.Cleanup(positionId);
  }

bool IsNewBar()
  {
   datetime t = iTime(_Symbol, InpTimeframe, 0);
   if(t != g_lastBarTime)
     {
      g_lastBarTime = t;
      GlobalVariableSet(g_gvLastBarKey, (double)g_lastBarTime);
      return true;
     }
   return false;
  }

void ManageOpenPositions()
  {
   double atr = signalEngine.GetATR();
   if(atr <= 0) return;

   double trail = atr * InpTrailAtrMult;
   double trailActivation = atr;
   double beBuffer = atr * 0.1;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber) continue;

      ulong positionId = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
      if(positionId == 0) continue;

      if(!positionState.EnsurePosition(ticket))
        {
         Print("GoldenTradeX: SEV0 — no se pudo asegurar PositionState para position_id=",
               positionId, ". Kill Switch activado.");
         riskManager.SetKillSwitch(true);
         continue;
        }
      positionState.UpdateExcursions(ticket);

      SPositionState s;
      if(!positionState.Load(positionId, s)) continue;

      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      long type = PositionGetInteger(POSITION_TYPE);

      if(InpUsePartialTP)
         partialTP.Check(trade, ticket, InpPartialTPR, InpPartialTPPct);

      double beActivation = s.initialRiskPrice * InpBreakEvenR;

      if(type == POSITION_TYPE_BUY)
        {
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double bePrice = NormalizeDouble(s.entryPrice + beBuffer, _Digits);
         if(InpUseBreakEven && bid - s.entryPrice >= beActivation &&
            sl < bePrice && bePrice < bid)
            orderMgr.ModifyPosition(ticket, bePrice, tp);

         if(!InpUseTrailing) continue;
         if(bid - openPrice < trailActivation) continue;
         double newSl = NormalizeDouble(bid - trail, _Digits);
         if(newSl > sl && newSl < bid)
            orderMgr.ModifyPosition(ticket, newSl, tp);
        }
      else
        {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double bePrice = NormalizeDouble(s.entryPrice - beBuffer, _Digits);
         if(InpUseBreakEven && s.entryPrice - ask >= beActivation &&
            (sl > bePrice || sl == 0) && bePrice > ask)
            orderMgr.ModifyPosition(ticket, bePrice, tp);

         if(!InpUseTrailing) continue;
         if(openPrice - ask < trailActivation) continue;
         double newSl = NormalizeDouble(ask + trail, _Digits);
         if((newSl < sl || sl == 0) && newSl > ask)
            orderMgr.ModifyPosition(ticket, newSl, tp);
        }
     }
  }

void CloseAllPositions(string reason)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber) continue;
      if(!orderMgr.ClosePosition(ticket))
         Print("GoldenTradeX: fallo cerrando #", ticket);
     }
   Comment("GoldenTradeX: ", reason);
  }
//+------------------------------------------------------------------+
