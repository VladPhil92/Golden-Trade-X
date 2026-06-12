//+------------------------------------------------------------------+
//|                                                 GoldenTradeX.mq5 |
//|                    Golden Trade X — Expert Advisor para XAUUSD   |
//|                    CTG One Technology S.A.S.                     |
//+------------------------------------------------------------------+
#property copyright "CTG One Technology S.A.S."
#property link      "https://github.com/VladPhil92/Golden-Trade-X"
#property version   "1.20"
#property strict
#property description "EA de tendencia para Oro (XAUUSD): EMA cross + RSI + filtro ATR + ADX + tendencia H4, gestión de riesgo por % de equity, trailing stop con activación 1R, límites de drawdown diario/semanal y control de pérdidas consecutivas."

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
input double  InpRsiUpper         = 70.0;   // RSI: techo para longs
input double  InpRsiLower         = 30.0;   // RSI: suelo para shorts
input double  InpRsiLongMin       = 45.0;   // RSI mínimo para longs (momentum alcista)
input double  InpRsiShortMax      = 55.0;   // RSI máximo para shorts (momentum bajista)
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_M15;
input int     InpAtrPeriod        = 14;
input double  InpAtrMinRatio      = 0.8;    // ATR / ATR_SMA(20): mínimo para operar
input int     InpAdxPeriod        = 14;     // Periodo ADX para filtro de régimen
input double  InpAdxMinLevel      = 25.0;   // ADX mínimo (0 = desactivado)
input double  InpAtrMaxRatio      = 3.0;    // ATR máximo vs ATR_SMA (0 = desactivado)

//--- Filtro de tendencia H4
input group "=== Filtro de Tendencia HTF ==="
input bool    InpUseHtfFilter     = true;   // Solo operar a favor de la tendencia H4
input int     InpHtfEmaPeriod     = 50;     // Periodo EMA en H4

//--- Gestión de riesgo
input group "=== Riesgo ==="
input double  InpRiskPercent      = 1.0;
input double  InpMaxDailyDD       = 4.0;
input int     InpMaxPositions     = 1;
input double  InpAtrSlMultiplier  = 2.0;    // SL = ATR × factor
input double  InpAtrTpMultiplier  = 3.0;    // TP = ATR × factor
input double  InpMaxSpreadPoints  = 350;
input double  InpMaxWeeklyDD      = 8.0;    // Drawdown semanal máximo (%)
input int     InpMaxConsecLosses  = 3;      // Pérdidas consecutivas máx antes de pausa

//--- Trailing stop
input group "=== Trailing Stop ==="
input bool    InpUseTrailing      = true;
input double  InpTrailAtrMult     = 1.5;    // Trailing = ATR × factor

//--- Sesiones
input group "=== Sesiones ==="
input bool    InpUseSessionFilter = true;
input int     InpStartHour        = 7;
input int     InpEndHour          = 20;
input bool    InpCloseOnFriday    = true;
input int     InpFridayCloseHour  = 19;

//--- Noticias
input group "=== Noticias ==="
input bool    InpPauseForNews     = false;  // Pausar EA manualmente en días de noticias

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
   // Validar parámetros antes de inicializar indicadores
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
      Print("GoldenTradeX: InpRiskPercent fuera de rango (0–10%)");
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

   // Recuperar última barra procesada para evitar entrada espuria al reiniciar
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
   // Cierre obligatorio de viernes antes de cualquier otra lógica
   if(sessionFilter.MustCloseAll())
     {
      CloseAllPositions("Cierre de fin de semana");
      return;
     }

   // Trailing stop en cada tick (solo si la posición alcanzó 1R)
   if(InpUseTrailing)
      ManageTrailing();

   if(!IsNewBar()) return;

   // Filtros de sesión y condiciones de mercado
   if(!sessionFilter.IsTradingAllowed())         return;
   if(!riskManager.IsSpreadAcceptable(_Symbol))  return;
   if(riskManager.IsDailyDrawdownExceeded())
     {
      Comment("GoldenTradeX: drawdown diario alcanzado. Pausa hasta mañana.");
      return;
     }
   if(riskManager.IsWeeklyDrawdownExceeded())
     {
      Comment("GoldenTradeX: drawdown semanal alcanzado. Pausa hasta la semana siguiente.");
      return;
     }
   if(riskManager.IsConsecutiveLossLimitReached())
     {
      Comment("GoldenTradeX: ", InpMaxConsecLosses, " pérdidas consecutivas. Pausa temporal.");
      return;
     }
   if(InpPauseForNews)
     {
      Comment("GoldenTradeX: pausa manual por evento de noticias.");
      return;
     }
   if(riskManager.CountOpenPositions(_Symbol) >= InpMaxPositions) return;

   // Verificar conexión al servidor antes de intentar operar
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
      Print("GoldenTradeX: fallo al abrir posición. Error: ",
            trade.ResultRetcodeDescription());
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
//| Trailing stop: se activa solo cuando la posición alcanza 1R      |
//+------------------------------------------------------------------+
void ManageTrailing()
  {
   double atr = signalEngine.GetATR();
   if(atr <= 0) return;

   double trail      = atr * InpTrailAtrMult;
   double activation = atr * InpAtrSlMultiplier;  // 1R = distancia al SL inicial

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
         if(bid - openPrice < activation) continue;  // no alcanzó 1R aún
         double newSl = NormalizeDouble(bid - trail, _Digits);
         if(newSl > sl && newSl < bid)
            trade.PositionModify(ticket, newSl, tp);
        }
      else
        {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         if(openPrice - ask < activation) continue;  // no alcanzó 1R aún
         double newSl = NormalizeDouble(ask + trail, _Digits);
         if((newSl < sl || sl == 0) && newSl > ask)
            trade.PositionModify(ticket, newSl, tp);
        }
     }
  }

//+------------------------------------------------------------------+
//| Cierra todas las posiciones del EA con verificación de resultado  |
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
//| Detecta operaciones cerradas y registra resultado para tracking   |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest     &request,
                        const MqlTradeResult      &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(trans.deal_type != DEAL_TYPE_BUY && trans.deal_type != DEAL_TYPE_SELL) return;

   ulong dealTicket = trans.deal;
   if(!HistoryDealSelect(dealTicket)) return;

   long magic = HistoryDealGetInteger(dealTicket, DEAL_MAGIC);
   if(magic != (long)InpMagicNumber) return;

   long entry = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT) return;

   double profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT);
   riskManager.RegisterTradeResult(profit);
  }
//+------------------------------------------------------------------+
