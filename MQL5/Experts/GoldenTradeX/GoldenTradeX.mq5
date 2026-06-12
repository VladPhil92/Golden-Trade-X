//+------------------------------------------------------------------+
//|                                                 GoldenTradeX.mq5 |
//|                    Golden Trade X — Expert Advisor para XAUUSD   |
//|                    CTG One Technology S.A.S.                     |
//+------------------------------------------------------------------+
#property copyright "CTG One Technology S.A.S."
#property link      "https://github.com/VladPhil92/Golden-Trade-X"
#property version   "1.00"
#property strict
#property description "EA de tendencia para Oro (XAUUSD): EMA cross + RSI + filtro ATR, gestión de riesgo por % de equity, trailing stop y límites de drawdown diario."

#include <Trade/Trade.mqh>
#include <GoldenTradeX/RiskManager.mqh>
#include <GoldenTradeX/SignalEngine.mqh>
#include <GoldenTradeX/SessionFilter.mqh>

//--- Parámetros de entrada
input group "=== Identidad ==="
input ulong   InpMagicNumber      = 920260;   // Magic Number
input string  InpTradeComment     = "GoldenTradeX";

input group "=== Señales (SignalEngine) ==="
input int     InpEmaFast          = 21;       // EMA rápida
input int     InpEmaSlow          = 55;       // EMA lenta
input int     InpRsiPeriod        = 14;       // Periodo RSI
input double  InpRsiUpper         = 70.0;     // RSI sobrecompra (no comprar encima)
input double  InpRsiLower         = 30.0;     // RSI sobreventa (no vender debajo)
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_M15; // Timeframe de señal

input group "=== Riesgo (RiskManager) ==="
input double  InpRiskPercent      = 1.0;      // Riesgo por operación (% equity)
input double  InpMaxDailyDD       = 4.0;      // Drawdown diario máximo (%)
input int     InpMaxPositions     = 1;        // Posiciones simultáneas máximas
input double  InpAtrSlMultiplier  = 2.0;      // SL = ATR x este factor
input double  InpAtrTpMultiplier  = 3.0;      // TP = ATR x este factor
input int     InpAtrPeriod        = 14;       // Periodo ATR
input double  InpMaxSpreadPoints  = 350;      // Spread máximo permitido (puntos)

input group "=== Trailing Stop ==="
input bool    InpUseTrailing      = true;     // Activar trailing stop
input double  InpTrailAtrMult     = 1.5;      // Trailing = ATR x este factor

input group "=== Sesiones (SessionFilter) ==="
input bool    InpUseSessionFilter = true;     // Operar solo Londres/NY
input int     InpStartHour        = 7;        // Hora inicio (servidor)
input int     InpEndHour          = 20;       // Hora fin (servidor)
input bool    InpCloseOnFriday    = true;     // Cerrar todo viernes tarde
input int     InpFridayCloseHour  = 19;       // Hora de cierre viernes

//--- Objetos globales
CTrade        trade;
CRiskManager  riskManager;
CSignalEngine signalEngine;
CSessionFilter sessionFilter;

datetime      g_lastBarTime = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(_Symbol);

   if(!signalEngine.Init(_Symbol, InpTimeframe, InpEmaFast, InpEmaSlow,
                         InpRsiPeriod, InpRsiUpper, InpRsiLower, InpAtrPeriod))
     {
      Print("GoldenTradeX: error inicializando SignalEngine");
      return(INIT_FAILED);
     }

   riskManager.Init(InpRiskPercent, InpMaxDailyDD, InpMaxPositions,
                    InpMaxSpreadPoints, InpMagicNumber);

   sessionFilter.Init(InpUseSessionFilter, InpStartHour, InpEndHour,
                      InpCloseOnFriday, InpFridayCloseHour);

   Print("GoldenTradeX v1.00 inicializado en ", _Symbol);
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
   //--- Cierre obligatorio de viernes
   if(sessionFilter.MustCloseAll())
     {
      CloseAllPositions("Cierre de fin de semana");
      return;
     }

   //--- Trailing stop en cada tick
   if(InpUseTrailing)
      ManageTrailing();

   //--- Lógica de entrada solo en nueva vela
   if(!IsNewBar())
      return;

   //--- Filtros previos
   if(!sessionFilter.IsTradingAllowed())          return;
   if(!riskManager.IsSpreadAcceptable(_Symbol))   return;
   if(riskManager.IsDailyDrawdownExceeded())
     {
      Comment("GoldenTradeX: drawdown diario alcanzado. Pausa hasta mañana.");
      return;
     }
   if(riskManager.CountOpenPositions(_Symbol) >= InpMaxPositions) return;

   //--- Obtener señal
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
      Print("GoldenTradeX: fallo al abrir posición. Error: ", trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| Detecta nueva vela en el timeframe de señal                      |
//+------------------------------------------------------------------+
bool IsNewBar()
  {
   datetime t = iTime(_Symbol, InpTimeframe, 0);
   if(t != g_lastBarTime)
     {
      g_lastBarTime = t;
      return(true);
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| Trailing stop basado en ATR                                      |
//+------------------------------------------------------------------+
void ManageTrailing()
  {
   double atr = signalEngine.GetATR();
   if(atr <= 0) return;
   double trail = atr * InpTrailAtrMult;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber) continue;

      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      long   type = PositionGetInteger(POSITION_TYPE);

      if(type == POSITION_TYPE_BUY)
        {
         double bid   = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double newSl = NormalizeDouble(bid - trail, _Digits);
         if(newSl > sl && newSl < bid)
            trade.PositionModify(ticket, newSl, tp);
        }
      else
        {
         double ask   = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double newSl = NormalizeDouble(ask + trail, _Digits);
         if((newSl < sl || sl == 0) && newSl > ask)
            trade.PositionModify(ticket, newSl, tp);
        }
     }
  }

//+------------------------------------------------------------------+
//| Cierra todas las posiciones del EA                               |
//+------------------------------------------------------------------+
void CloseAllPositions(string reason)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagicNumber) continue;
      trade.PositionClose(ticket);
     }
   Comment("GoldenTradeX: ", reason);
  }
//+------------------------------------------------------------------+
