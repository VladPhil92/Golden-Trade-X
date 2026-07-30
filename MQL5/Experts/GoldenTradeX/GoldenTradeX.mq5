//+------------------------------------------------------------------+
//|                                                 GoldenTradeX.mq5 |
//|                    Golden Trade X v2.00 — Expert Advisor          |
//|                    CTG One Technology S.A.S.                      |
//+------------------------------------------------------------------+
#property copyright "CTG One Technology S.A.S."
#property link      "https://github.com/VladPhil92/Golden-Trade-X"
#property version   "2.10"
#property strict
#property description "EA de precisión para Oro (XAUUSD): EMA+RSI+ADX+ATR+H4 + Market Regime + Smart Money Concepts + Ensemble Confidence Score. Gestión de riesgo multicapa con circuit breaker mensual, kill switch y Capital Preservation Mode."

#include <Trade/Trade.mqh>
#include <GoldenTradeX/RiskManager.mqh>
#include <GoldenTradeX/SignalEngine.mqh>
#include <GoldenTradeX/SessionFilter.mqh>
#include <GoldenTradeX/NewsFilter.mqh>
#include <GoldenTradeX/TradeLogger.mqh>
#include <GoldenTradeX/MarketRegimeEngine.mqh>
#include <GoldenTradeX/SmartMoneyEngine.mqh>
#include <GoldenTradeX/ConfidenceEngine.mqh>

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

//--- Filtro HTF
input group "=== Filtro de Tendencia HTF ==="
input bool    InpUseHtfFilter     = true;
input int     InpHtfEmaPeriod     = 50;

//--- Módulos v2.00
input group "=== Ensemble & Smart Money (v2.00) ==="
input bool    InpUseRegimeFilter  = true;    // Activar filtro de régimen de mercado
input bool    InpUseSmcFilter     = true;    // Activar Smart Money Concepts
input int     InpMinConfidence    = 55;      // Score mínimo (0-100) para operar

//--- Gestión de riesgo
input group "=== Riesgo ==="
input double  InpRiskPercent      = 1.0;
input double  InpMaxDailyDD       = 4.0;
input double  InpMaxWeeklyDD      = 8.0;
input double  InpMaxMonthlyDD     = 15.0;   // v2.00: circuit breaker mensual (0=off)
input int     InpMaxConsecLosses  = 3;
input int     InpMaxPositions     = 1;
input double  InpAtrSlMultiplier  = 2.0;
input double  InpAtrTpMultiplier  = 3.0;
input double  InpMaxSpreadPoints  = 350;
input double  InpCpThresholdPct   = 8.0;    // v2.00: % DD diario que activa Capital Preservation

//--- Trailing y Break-even
input group "=== Trailing Stop y Break-Even ==="
input bool    InpUseTrailing      = true;
input double  InpTrailAtrMult     = 1.5;
input bool    InpUseBreakEven     = true;
input double  InpBreakEvenR       = 0.5;

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

datetime  g_lastBarTime  = 0;
string    g_gvLastBarKey = "";
int       g_lastConfidence = 0;
ENUM_MARKET_REGIME g_lastRegime = REGIME_UNKNOWN;

//+------------------------------------------------------------------+
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
   if(InpBreakEvenR <= 0 || InpBreakEvenR > InpAtrSlMultiplier)
     { Print("GoldenTradeX: InpBreakEvenR debe estar en (0, AtrSlMultiplier]"); return INIT_PARAMETERS_INCORRECT; }
   if(InpMinConfidence < 0 || InpMinConfidence > 100)
     { Print("GoldenTradeX: InpMinConfidence debe ser 0-100"); return INIT_PARAMETERS_INCORRECT; }

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(_Symbol);

   if(!signalEngine.Init(_Symbol, InpTimeframe,
                         InpEmaFast, InpEmaSlow,
                         InpRsiPeriod, InpRsiUpper, InpRsiLower,
                         InpRsiLongMin, InpRsiShortMax,
                         InpAtrPeriod, InpAtrMinRatio,
                         InpAdxMinLevel, InpAtrMaxRatio,
                         InpUseHtfFilter, InpHtfEmaPeriod))
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

   if(!confEngine.Init(_Symbol, InpTimeframe, InpUseHtfFilter, InpHtfEmaPeriod, InpAtrPeriod))
     { Print("GoldenTradeX: error inicializando ConfidenceEngine"); return INIT_FAILED; }

   g_gvLastBarKey = StringFormat("GTX_%d_LastBar", (int)InpMagicNumber);
   g_lastBarTime  = (datetime)GlobalVariableGet(g_gvLastBarKey);

   newsFilter.PrintStatus();
   Print("GoldenTradeX v2.00 inicializado en ", _Symbol,
         " | MinConf=", InpMinConfidence,
         " | Regime=", InpUseRegimeFilter ? "ON" : "OFF",
         " | SMC=",    InpUseSmcFilter    ? "ON" : "OFF");
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   signalEngine.Release();
   regimeEngine.Release();
   confEngine.Release();
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

   if(!sessionFilter.IsTradingAllowed())         return;
   if(!riskManager.IsSpreadAcceptable(_Symbol))  return;

   if(riskManager.IsDailyDrawdownExceeded())
     { Comment("GoldenTradeX: DD diario alcanzado. Pausa hasta mañana."); return; }
   if(riskManager.IsWeeklyDrawdownExceeded())
     { Comment("GoldenTradeX: DD semanal alcanzado. Pausa hasta la semana siguiente."); return; }
   if(riskManager.IsMonthlyCircuitBreakerTripped())
     { Comment("GoldenTradeX: Circuit Breaker mensual disparado. Pausa hasta el mes siguiente."); return; }
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
      SSmcContext ctx = smcEngine.Analyze();
      smcScore = smcEngine.SmcScore(ctx, isBuy);
     }

   SConfidenceResult conf = confEngine.Compute(true, isBuy, regScore, smcScore);
   g_lastConfidence = conf.total;

   if(conf.total < InpMinConfidence)
     {
      Comment("GoldenTradeX: Conf=", conf.total, "/100 < ", InpMinConfidence,
              " | Base=", conf.baseSignal,
              " Reg=", conf.regimeBonus,
              " SMC=", conf.smcBonus,
              " HTF=", conf.htfBonus,
              " ATR=", conf.atrBonus);
      return;
     }

   // ── Capital Preservation: riesgo reducido automáticamente ─────────
   if(riskManager.IsCapitalPreservationActive())
      Print("GoldenTradeX: Capital Preservation Mode activo — riesgo reducido al 25%.");

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
     }
   else
     {
      type  = ORDER_TYPE_SELL;
      price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      sl    = price + atr * InpAtrSlMultiplier;
      tp    = price - atr * InpAtrTpMultiplier;
     }

   double lots = riskManager.CalculateLotSize(_Symbol, price, sl);
   if(lots <= 0) return;

   string comment = StringFormat("%s|Conf=%d|Reg=%s",
                                  InpTradeComment, conf.total,
                                  RegimeToString(g_lastRegime));

   if(!trade.PositionOpen(_Symbol, type, lots, price,
                          NormalizeDouble(sl, _Digits),
                          NormalizeDouble(tp, _Digits),
                          comment))
      Print("GoldenTradeX: fallo al abrir posición. Error: ",
            trade.ResultRetcodeDescription());
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

   double trail        = atr * InpTrailAtrMult;
   double trailActivation = atr * InpAtrSlMultiplier;
   double beActivation = atr * InpAtrSlMultiplier * InpBreakEvenR;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber) continue;

      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl        = PositionGetDouble(POSITION_SL);
      double tp        = PositionGetDouble(POSITION_TP);
      long   type      = PositionGetInteger(POSITION_TYPE);

      if(type == POSITION_TYPE_BUY)
        {
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         if(InpUseBreakEven && bid - openPrice >= beActivation && sl < openPrice)
           { trade.PositionModify(ticket, NormalizeDouble(openPrice, _Digits), tp); continue; }
         if(bid - openPrice < trailActivation) continue;
         double newSl = NormalizeDouble(bid - trail, _Digits);
         if(newSl > sl && newSl < bid)
            trade.PositionModify(ticket, newSl, tp);
        }
      else
        {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         if(InpUseBreakEven && openPrice - ask >= beActivation && (sl > openPrice || sl == 0))
           { trade.PositionModify(ticket, NormalizeDouble(openPrice, _Digits), tp); continue; }
         if(openPrice - ask < trailActivation) continue;
         double newSl = NormalizeDouble(ask + trail, _Digits);
         if((newSl < sl || sl == 0) && newSl > ask)
            trade.PositionModify(ticket, newSl, tp);
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
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber) continue;
      if(!trade.PositionClose(ticket))
         Print("GoldenTradeX: fallo cerrando #", ticket, " — ",
               trade.ResultRetcodeDescription());
     }
   Comment("GoldenTradeX: ", reason);
  }
//+------------------------------------------------------------------+
