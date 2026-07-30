//+------------------------------------------------------------------+
//|                                                 GoldenTradeX.mq5 |
//|                    Golden Trade X v2.30 — Expert Advisor          |
//|                    CTG One Technology S.A.S.                      |
//+------------------------------------------------------------------+
#property copyright "CTG One Technology S.A.S."
#property link      "https://github.com/VladPhil92/Golden-Trade-X"
#property version   "2.40"
#property strict
#property description "EA de precisión para Oro (XAUUSD): EMA+RSI+ADX+ATR+H4 + Market Regime + Smart Money Concepts + Fibonacci + Ensemble Confidence Score. Gestión de riesgo multicapa con circuit breaker mensual, kill switch persistente, Capital Preservation Mode, Partial TP, Equity Curve Filter y OrderManager production-grade con retry automático."

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

//--- Identidad
input group "=== Identidad ==="
input ulong   InpMagicNumber      = 920260;
input string  InpTradeComment     = "GoldenTradeX";

//--- Señales base
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
input double  InpAdxMinLevel      = 25.0;
input int     InpMinTickVolume    = 10;      // v2.20: volumen mínimo de ticks (0=off)

//--- Filtro HTF
input group "=== Filtro de Tendencia HTF ==="
input bool    InpUseHtfFilter     = true;
input int     InpHtfEmaPeriod     = 50;

//--- Módulos v2.00
input group "=== Ensemble & Smart Money ==="
input bool    InpUseRegimeFilter  = true;
input bool    InpUseSmcFilter     = true;
input int     InpMinConfidence    = 55;

//--- Gestión de riesgo
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

//--- Trailing y Break-even
input group "=== Trailing Stop y Break-Even ==="
input bool    InpUseTrailing      = true;
input double  InpTrailAtrMult     = 1.5;
input bool    InpUseBreakEven     = true;
input double  InpBreakEvenR       = 0.5;

//--- Partial Take Profit (v2.20)
input group "=== Partial Take Profit ==="
input bool    InpUsePartialTP     = true;
input double  InpPartialTPR       = 1.0;
input double  InpPartialTPPct     = 50.0;

//--- Equity Curve Filter (v2.20)
input group "=== Equity Curve Filter ==="
input bool    InpUseEqCurveFilter = true;
input int     InpEqCurvePeriod    = 20;

//--- Kelly Criterion (v2.40)
input group "=== Kelly Criterion (v2.40) ==="
input bool    InpUseKelly         = false;   // Activar Kelly Criterion fraccional
input double  InpKellyFraction    = 0.25;    // Fracción de Kelly (0.25 = quarter-Kelly)
input int     InpKellyMinTrades   = 30;      // Trades mínimos para activar Kelly

//--- Order Manager (v2.30)
input group "=== Order Manager (v2.30) ==="
input int     InpOrderMaxRetries  = 3;       // Reintentos máximos por error temporal
input int     InpOrderRetryDelay  = 500;     // Delay entre reintentos (ms)
input double  InpMinMarginLevel   = 200.0;   // Nivel mínimo de margen % (alerta HealthMonitor)

//--- Sesiones
input group "=== Sesiones ==="
input bool    InpUseSessionFilter = true;
input int     InpStartHour        = 7;
input int     InpEndHour          = 20;
input bool    InpCloseOnFriday    = true;
input int     InpFridayCloseHour  = 19;

//--- Noticias
input group "=== Noticias ==="
input bool    InpUseNewsFilter    = true;
input int     InpNewsBufferBefore = 30;
input int     InpNewsBufferAfter  = 90;
input bool    InpPauseForNews     = false;

//--- Registro
input group "=== Registro ==="
input bool    InpEnableTradeLog   = true;

//--- Objetos globales
CTrade             trade;
CRiskManager       riskManager;
CSignalEngine      signalEngine;
CSessionFilter     sessionFilter;
CNewsFilter        newsFilter;
CTradeLogger       tradeLogger;
CMarketRegimeEngine regimeEngine;
CSmartMoneyEngine  smcEngine;
CConfidenceEngine  confEngine;
CFibonacciEngine   fibEngine;
CPartialTP         partialTP;
CEquityCurveFilter eqCurveFilter;
COrderManager      orderMgr;
CHealthMonitor     healthMonitor;

datetime  g_lastBarTime  = 0;
string    g_gvLastBarKey = "";
int       g_lastConfidence = 0;
ENUM_MARKET_REGIME g_lastRegime = REGIME_UNKNOWN;

//+------------------------------------------------------------------+
int OnInit()
  {
   // ── Validaciones de parámetros ─────────────────────────────────────
   if(InpEmaFast >= InpEmaSlow)
     { Print("GoldenTradeX: InpEmaFast debe ser menor que InpEmaSlow"); return INIT_PARAMETERS_INCORRECT; }
   if(InpRsiLower >= InpRsiUpper)
     { Print("GoldenTradeX: InpRsiLower debe ser menor que InpRsiUpper"); return INIT_PARAMETERS_INCORRECT; }
   if(InpRsiLongMin >= InpRsiUpper || InpRsiShortMax <= InpRsiLower)
     { Print("GoldenTradeX: rangos RSI de momentum inconsistentes"); return INIT_PARAMETERS_INCORRECT; }
   if(InpRiskPercent <= 0 || InpRiskPercent > 10)
     { Print("GoldenTradeX: InpRiskPercent fuera de rango (0-10%)"); return INIT_PARAMETERS_INCORRECT; }
   if(InpBreakEvenR <= 0 || InpBreakEvenR > InpAtrSlMultiplier)
     { Print("GoldenTradeX: InpBreakEvenR debe estar en (0, AtrSlMultiplier]"); return INIT_PARAMETERS_INCORRECT; }
   if(InpMinConfidence < 0 || InpMinConfidence > 100)
     { Print("GoldenTradeX: InpMinConfidence debe ser 0-100"); return INIT_PARAMETERS_INCORRECT; }

   // ── Validación de cuenta (producción) ─────────────────────────────
   ENUM_ACCOUNT_TRADE_MODE mode = (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   Print("GoldenTradeX: cuenta tipo=",
         mode == ACCOUNT_TRADE_MODE_DEMO  ? "DEMO" :
         mode == ACCOUNT_TRADE_MODE_REAL  ? "REAL (¡DINERO REAL!)" : "CONTEST",
         " broker=",  AccountInfoString(ACCOUNT_COMPANY),
         " divisa=",  AccountInfoString(ACCOUNT_CURRENCY),
         " login=",   AccountInfoInteger(ACCOUNT_LOGIN));

   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
     { Print("GoldenTradeX: Trading NO permitido en el terminal. Revisa opciones."); return INIT_FAILED; }
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
     { Print("GoldenTradeX: MQL Trade NOT ALLOWED — activar 'Permitir trading automático'."); return INIT_FAILED; }

   // ── Configurar CTrade ──────────────────────────────────────────────
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(_Symbol);

   // ── Inicializar módulos ─────────────────────────────────────────────
   if(!signalEngine.Init(_Symbol, InpTimeframe,
                         InpEmaFast, InpEmaSlow,
                         InpRsiPeriod, InpRsiUpper, InpRsiLower,
                         InpRsiLongMin, InpRsiShortMax,
                         InpAtrPeriod, InpAtrMinRatio,
                         InpAdxMinLevel, InpAtrMaxRatio,
                         InpUseHtfFilter, InpHtfEmaPeriod,
                         (long)InpMinTickVolume))
     { Print("GoldenTradeX: error inicializando SignalEngine"); return INIT_FAILED; }

   riskManager.Init(InpRiskPercent, InpMaxDailyDD, InpMaxPositions,
                    InpMaxSpreadPoints, InpMagicNumber,
                    InpMaxConsecLosses, InpMaxWeeklyDD,
                    InpMaxMonthlyDD, InpCpThresholdPct);

   sessionFilter.Init(InpUseSessionFilter, InpStartHour, InpEndHour,
                      InpCloseOnFriday, InpFridayCloseHour);

   newsFilter.Init(InpUseNewsFilter, InpNewsBufferBefore, InpNewsBufferAfter);
   tradeLogger.Init(InpEnableTradeLog, InpMagicNumber);

   if(InpUseRegimeFilter)
     {
      if(!regimeEngine.Init(_Symbol, InpTimeframe, InpEmaFast, InpEmaSlow))
        { Print("GoldenTradeX: error inicializando MarketRegimeEngine"); return INIT_FAILED; }
     }

   if(InpUseSmcFilter)
     { smcEngine.Init(_Symbol, InpTimeframe); }

   if(!confEngine.Init(_Symbol, InpTimeframe, InpUseHtfFilter, InpHtfEmaPeriod))
     { Print("GoldenTradeX: error inicializando ConfidenceEngine"); return INIT_FAILED; }

   fibEngine.Init(_Symbol, InpTimeframe);
   partialTP.Init(InpUsePartialTP, InpMagicNumber);
   eqCurveFilter.Init(InpUseEqCurveFilter, InpEqCurvePeriod, InpMagicNumber);
   orderMgr.Init(&trade, InpOrderMaxRetries, InpOrderRetryDelay);
   healthMonitor.Init(_Symbol, InpMagicNumber, InpMinMarginLevel);
   riskManager.InitKelly(InpUseKelly, InpKellyFraction, InpKellyMinTrades);

   // ── Persistencia de barra ──────────────────────────────────────────
   g_gvLastBarKey = StringFormat("GTX_%d_LastBar", (int)InpMagicNumber);
   g_lastBarTime  = (datetime)GlobalVariableGet(g_gvLastBarKey);

   // ── Timer: health check cada 60 segundos ──────────────────────────
   EventSetTimer(60);

   newsFilter.PrintStatus();
   riskManager.PrintStatus();
   Print("GoldenTradeX v2.40 inicializado en ", _Symbol,
         " | MinConf=",    InpMinConfidence,
         " | Retries=",    InpOrderMaxRetries,
         " | PartialTP=",  InpUsePartialTP  ? "ON" : "OFF",
         " | EqFilter=",   InpUseEqCurveFilter ? "ON" : "OFF",
         " | Kelly=",      InpUseKelly ? StringFormat("ON(f=%.0f%%,min=%d)", InpKellyFraction*100, InpKellyMinTrades) : "OFF");
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   signalEngine.Release();
   regimeEngine.Release();
   confEngine.Release();
   orderMgr.PrintStats();
   Print("GoldenTradeX: deinit razón=", reason);
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   // Health check periódico (60s): orphan SL, margen, conexión
   healthMonitor.Check(trade);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   if(sessionFilter.MustCloseAll())
     { CloseAllPositions("Cierre de fin de semana"); return; }

   if(InpUseTrailing)
      ManageTrailing();

   if(!IsNewBar()) return;

   // ── Guardianes de riesgo ──────────────────────────────────────────
   if(riskManager.IsKillSwitchActive())
     { Comment("GoldenTradeX: KILL SWITCH activo. Operaciones detenidas."); return; }
   if(!sessionFilter.IsTradingAllowed())        return;
   if(!riskManager.IsSpreadAcceptable(_Symbol)) return;

   if(riskManager.IsDailyDrawdownExceeded())
     { Comment("GoldenTradeX: DD diario alcanzado. Pausa hasta mañana."); return; }
   if(riskManager.IsWeeklyDrawdownExceeded())
     { Comment("GoldenTradeX: DD semanal alcanzado. Pausa hasta la semana siguiente."); return; }
   if(riskManager.IsMonthlyCircuitBreakerTripped())
     { Comment("GoldenTradeX: Circuit Breaker mensual disparado."); return; }
   if(riskManager.IsConsecutiveLossLimitReached())
     { Comment("GoldenTradeX: ", InpMaxConsecLosses, " pérdidas consecutivas. Pausa."); return; }
   if(newsFilter.IsNewsBlocked())
     { Comment("GoldenTradeX: ventana de noticias activa. Esperando..."); return; }
   if(InpPauseForNews)
     { Comment("GoldenTradeX: pausa manual activa."); return; }
   if(riskManager.CountOpenPositions(_Symbol) >= InpMaxPositions) return;
   if(!TerminalInfoInteger(TERMINAL_CONNECTED)) return;

   // ── Régimen de mercado ────────────────────────────────────────────
   if(InpUseRegimeFilter)
     {
      g_lastRegime = regimeEngine.Detect();
      if(g_lastRegime == REGIME_VOLATILE)
        { Comment("GoldenTradeX: régimen VOLATILE. Sin entradas."); return; }
     }

   // ── Señal base ────────────────────────────────────────────────────
   ENUM_SIGNAL signal = signalEngine.GetSignal();
   if(signal == SIGNAL_NONE) return;

   bool isBuy = (signal == SIGNAL_BUY);

   // ── Ensemble Confidence Score ─────────────────────────────────────
   int regScore = InpUseRegimeFilter ? regimeEngine.RegimeScore(isBuy) : 15;
   int smcScore = 0;
   if(InpUseSmcFilter)
     {
      SSmcContext smcCtx = smcEngine.Analyze();
      smcScore = smcEngine.SmcScore(smcCtx, isBuy);
     }

   SFibContext fibCtx = fibEngine.Analyze();
   int fibScore       = fibEngine.FibScore(fibCtx, isBuy);

   SConfidenceResult conf = confEngine.Compute(true, isBuy, regScore, smcScore, fibScore);
   g_lastConfidence = conf.total;

   if(conf.total < InpMinConfidence)
     {
      Comment("GoldenTradeX: Conf=", conf.total, "/100 < ", InpMinConfidence,
              " | Base=", conf.baseSignal, " Reg=", conf.regimeBonus,
              " SMC=", conf.smcBonus, " HTF=", conf.htfBonus, " Fib=", conf.fibBonus);
      return;
     }

   if(riskManager.IsCapitalPreservationActive())
      Print("GoldenTradeX: Capital Preservation Mode activo.");

   double atr = signalEngine.GetATR();
   if(atr <= 0) return;

   double price, sl, tp;
   ENUM_ORDER_TYPE type;

   if(isBuy)
     {
      type  = ORDER_TYPE_BUY;
      price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      sl    = price - atr * InpAtrSlMultiplier;
      tp    = price + atr * InpAtrTpMultiplier;
      // v2.20: anclaje estructural al swing low Fibonacci
      if(fibCtx.swingLow > 0 && fibCtx.swingLow < price)
        {
         double structSL = fibCtx.swingLow - atr * 0.1;
         sl = MathMin(sl, structSL);
        }
     }
   else
     {
      type  = ORDER_TYPE_SELL;
      price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      sl    = price + atr * InpAtrSlMultiplier;
      tp    = price - atr * InpAtrTpMultiplier;
      // v2.20: anclaje estructural al swing high Fibonacci
      if(fibCtx.swingHigh > 0 && fibCtx.swingHigh > price)
        {
         double structSL = fibCtx.swingHigh + atr * 0.1;
         sl = MathMax(sl, structSL);
        }
     }

   double lots = riskManager.CalculateLotSize(_Symbol, price, sl);
   if(lots <= 0) return;

   // v2.20: Equity Curve Filter
   double eqMult = eqCurveFilter.Update();
   if(eqMult < 1.0)
     {
      double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
      double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      lots = MathFloor(lots * eqMult / lotStep) * lotStep;
      if(lots < minLot) return;
      Print("GoldenTradeX: EqCurveFilter — lote reducido al 50% (equity<EMA).");
     }

   string comment = StringFormat("%s|Conf=%d|Reg=%s",
                                  InpTradeComment, conf.total,
                                  RegimeToString(g_lastRegime));

   // v2.30: usar OrderManager (retry + validación + slippage tracking)
   bool ok = orderMgr.OpenPosition(_Symbol, type, lots, price,
                                   NormalizeDouble(sl, _Digits),
                                   NormalizeDouble(tp, _Digits),
                                   comment);
   if(!ok && orderMgr.LastErrorIsFatal())
     {
      Print("GoldenTradeX: error fatal al abrir posición — activando Kill Switch.");
      riskManager.SetKillSwitch(true);
     }
  }

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest     &request,
                        const MqlTradeResult      &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(trans.deal_type != DEAL_TYPE_BUY && trans.deal_type != DEAL_TYPE_SELL) return;

   ulong dealTicket = trans.deal;
   if(!HistoryDealSelect(dealTicket)) return;
   if(HistoryDealGetInteger(dealTicket, DEAL_MAGIC) != (long)InpMagicNumber) return;

   long entry = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT) return;

   double profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT);
   riskManager.RegisterTradeResult(profit);
   tradeLogger.LogTrade(dealTicket);

   ulong posTicket = HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);
   if(entry == DEAL_ENTRY_OUT)
      partialTP.Cleanup(posTicket);
  }

//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
void ManageTrailing()
  {
   double atr = signalEngine.GetATR();
   if(atr <= 0) return;

   double trail           = atr * InpTrailAtrMult;
   double trailActivation = atr;   // v2.20: 1 ATR
   double beActivation    = atr * InpAtrSlMultiplier * InpBreakEvenR;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)  != (long)InpMagicNumber) continue;

      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl        = PositionGetDouble(POSITION_SL);
      double tp        = PositionGetDouble(POSITION_TP);
      long   type      = PositionGetInteger(POSITION_TYPE);

      // v2.20: Partial TP
      partialTP.Check(trade, ticket, InpPartialTPR, InpPartialTPPct);

      if(type == POSITION_TYPE_BUY)
        {
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         // v2.20: break-even sin continue → trailing actúa el mismo tick
         if(InpUseBreakEven && bid - openPrice >= beActivation && sl < openPrice)
            orderMgr.ModifyPosition(ticket, NormalizeDouble(openPrice, _Digits), tp);

         if(!InpUseTrailing) continue;
         if(bid - openPrice < trailActivation) continue;
         double newSl = NormalizeDouble(bid - trail, _Digits);
         if(newSl > sl && newSl < bid)
            orderMgr.ModifyPosition(ticket, newSl, tp);
        }
      else
        {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         // v2.20: break-even sin continue → trailing actúa el mismo tick
         if(InpUseBreakEven && openPrice - ask >= beActivation && (sl > openPrice || sl == 0))
            orderMgr.ModifyPosition(ticket, NormalizeDouble(openPrice, _Digits), tp);

         if(!InpUseTrailing) continue;
         if(openPrice - ask < trailActivation) continue;
         double newSl = NormalizeDouble(ask + trail, _Digits);
         if((newSl < sl || sl == 0) && newSl > ask)
            orderMgr.ModifyPosition(ticket, newSl, tp);
        }
     }
  }

//+------------------------------------------------------------------+
void CloseAllPositions(string reason)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)  != (long)InpMagicNumber) continue;
      if(!orderMgr.ClosePosition(ticket))
         Print("GoldenTradeX: fallo cerrando #", ticket);
     }
   Comment("GoldenTradeX: ", reason);
  }
//+------------------------------------------------------------------+
