//+------------------------------------------------------------------+
//|                                                 GoldenTradeX.mq5 |
//|                    Golden Trade X — Expert Advisor para XAUUSD   |
//|                    CTG One Technology S.A.S.                     |
//+------------------------------------------------------------------+
#property copyright "CTG One Technology S.A.S."
#property link      "https://github.com/VladPhil92/Golden-Trade-X"
#property version   "1.20"
#property strict
#property description "EA de tendencia para Oro (XAUUSD): EMA cross + RSI + ADX + ATR + H4, gestión de riesgo multicapa con DD diario/semanal, pérdidas consecutivas y pausa por noticias."

#include <Trade/Trade.mqh>
#include <GoldenTradeX/RiskManager.mqh>
#include <GoldenTradeX/SignalEngine.mqh>
#include <GoldenTradeX/SessionFilter.mqh>

//--- Identidad
input group "=== Identidad ==="
input ulong   InpMagicNumber      = 920260;
input string  InpTradeComment     = "GoldenTradeX";

//--- Señales base
input group "=== Señales ==="
input int     InpEmaFast          = 21;
input int     InpEmaSlow          = 55;
input int     InpRsiPeriod        = 14;
input double  InpRsiUpper         = 70.0;    // RSI: techo para longs
input double  InpRsiLower         = 30.0;    // RSI: suelo para shorts
input double  InpRsiLongMin       = 45.0;    // RSI minimo para longs (momentum alcista)
input double  InpRsiShortMax      = 55.0;    // RSI maximo para shorts (momentum bajista)
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_M15;
input int     InpAtrPeriod        = 14;
input double  InpAtrMinRatio      = 0.8;     // ATR / ATR_SMA(20): minimo para operar
input double  InpAtrMaxRatio      = 3.0;     // ATR / ATR_SMA(20): maximo (bloquea spikes)
input double  InpAdxMinLevel      = 25.0;    // ADX minimo: regimen tendencial (0=off)

//--- Filtro de tendencia H4
input group "=== Filtro de Tendencia HTF ==="
input bool    InpUseHtfFilter     = true;    // Solo operar a favor de la tendencia H4
input int     InpHtfEmaPeriod     = 50;      // Periodo EMA en H4

//--- Gestion de riesgo
input group "=== Riesgo ==="
input double  InpRiskPercent      = 1.0;
input double  InpMaxDailyDD       = 4.0;     // Drawdown diario maximo (%)
input double  InpMaxWeeklyDD      = 8.0;     // Drawdown semanal maximo (%)
input int     InpMaxConsecLosses  = 3;       // Perdidas consecutivas antes de pausa (0=off)
input int     InpMaxPositions     = 1;
input double  InpAtrSlMultiplier  = 2.0;     // SL = ATR x factor
input double  InpAtrTpMultiplier  = 3.0;     // TP = ATR x factor
input double  InpMaxSpreadPoints  = 350;

//--- Trailing stop
input group "=== Trailing Stop ==="
input bool    InpUseTrailing      = true;
input double  InpTrailAtrMult     = 1.5;     // Trailing = ATR x factor (activo desde +1R)

//--- Sesiones
input group "=== Sesiones ==="
input bool    InpUseSessionFilter = true;
input int     InpStartHour        = 7;
input int     InpEndHour          = 20;
input bool    InpCloseOnFriday    = true;
input int     InpFridayCloseHour  = 19;

//--- Noticias
input group "=== Noticias ==="
input bool    InpPauseForNews     = false;   // Pausa manual en dias de alto impacto (NFP/FOMC/CPI)

//--- Objetos globales
CTrade         trade;
CRiskManager   riskManager;
CSignalEngine  signalEngine;
CSessionFilter sessionFilter;

datetime  g_lastBarTime  = 0;
string    g_gvLastBarKey = "";

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpEmaFast >= InpEmaSlow)
     {
      Print("GoldenTradeX: InpEmaFast debe ser menor que InpEmaSlow");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpRsiLower >= InpRsiUpper)
     {
      Print("GoldenTradeX: InpRsiLower debe ser menor que InpRsiUpper");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpRsiLongMin >= InpRsiUpper || InpRsiShortMax <= InpRsiLower)
     {
      Print("GoldenTradeX: rangos RSI de momentum inconsistentes");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpRiskPercent <= 0 || InpRiskPercent > 10)
     {
      Print("GoldenTradeX: InpRiskPercent fuera de rango (0-10%)");
      return(INIT_PARAMETERS_INCORRECT);
     }

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
     {
      Print("GoldenTradeX: error inicializando SignalEngine");
      return(INIT_FAILED);
     }

   riskManager.Init(InpRiskPercent, InpMaxDailyDD, InpMaxPositions,
                    InpMaxSpreadPoints, InpMagicNumber,
                    InpMaxConsecLosses, InpMaxWeeklyDD);

   sessionFilter.Init(InpUseSessionFilter, InpStartHour, InpEndHour,
                      InpCloseOnFriday, InpFridayCloseHour);

   g_gvLastBarKey = StringFormat("GTX_%d_LastBar", (int)InpMagicNumber);
   g_lastBarTime  = (datetime)GlobalVariableGet(g_gvLastBarKey);

   Print("GoldenTradeX v1.20 inicializado en ", _Symbol);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   signalEngine.Release();
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   if(sessionFilter.MustCloseAll())
     {
      CloseAllPositions("Cierre de fin de semana");
      return;
     }

   if(InpUseTrailing)
      ManageTrailing();

   if(!IsNewBar()) return;

   if(!sessionFilter.IsTradingAllowed())         return;
   if(!riskManager.IsSpreadAcceptable(_Symbol))  return;

   if(riskManager.IsDailyDrawdownExceeded())
     {
      Comment("GoldenTradeX: DD diario alcanzado. Pausa hasta manana.");
      return;
     }
   if(riskManager.IsWeeklyDrawdownExceeded())
     {
      Comment("GoldenTradeX: DD semanal alcanzado. Pausa hasta la semana siguiente.");
      return;
     }
   if(riskManager.IsConsecutiveLossLimitReached())
     {
      Comment("GoldenTradeX: ", InpMaxConsecLosses,
              " perdidas consecutivas. Pausa hasta nueva semana.");
      return;
     }
   if(InpPauseForNews)
     {
      Comment("GoldenTradeX: pausa manual activa (evento de noticias).");
      return;
     }

   if(riskManager.CountOpenPositions(_Symbol) >= InpMaxPositions) return;
   if(!TerminalInfoInteger(TERMINAL_CONNECTED)) return;

   ENUM_SIGNAL signal = signalEngine.GetSignal();
   if(signal == SIGNAL_NONE) return;

   double atr = signalEngine.GetATR();
   if(atr <= 0) return;

   double price, sl, tp;
   ENUM_ORDER_TYPE type;

   if(signal == SIGNAL_BUY)
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

   if(!trade.PositionOpen(_Symbol, type, lots, price,
                          NormalizeDouble(sl, _Digits),
                          NormalizeDouble(tp, _Digits),
                          InpTradeComment))
      Print("GoldenTradeX: fallo al abrir posicion. Error: ",
            trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| Registra resultado de cada deal cerrado para tracking de perdidas |
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
  }

//+------------------------------------------------------------------+
bool IsNewBar()
  {
   datetime t = iTime(_Symbol, InpTimeframe, 0);
   if(t != g_lastBarTime)
     {
      g_lastBarTime = t;
      GlobalVariableSet(g_gvLastBarKey, (double)g_lastBarTime);
      return(true);
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| Trailing stop: activo solo cuando la posicion alcanza 1R         |
//+------------------------------------------------------------------+
void ManageTrailing()
  {
   double atr = signalEngine.GetATR();
   if(atr <= 0) return;

   double trail      = atr * InpTrailAtrMult;
   double activation = atr * InpAtrSlMultiplier;

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
         if(bid - openPrice < activation) continue;
         double newSl = NormalizeDouble(bid - trail, _Digits);
         if(newSl > sl && newSl < bid)
            trade.PositionModify(ticket, newSl, tp);
        }
      else
        {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         if(openPrice - ask < activation) continue;
         double newSl = NormalizeDouble(ask + trail, _Digits);
         if((newSl < sl || sl == 0) && newSl > ask)
            trade.PositionModify(ticket, newSl, tp);
        }
     }
  }

//+------------------------------------------------------------------+
//| Cierra todas las posiciones del EA con verificacion de resultado  |
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
         Print("GoldenTradeX: fallo cerrando #", ticket,
               " — ", trade.ResultRetcodeDescription());
     }
   Comment("GoldenTradeX: ", reason);
  }
//+------------------------------------------------------------------+
