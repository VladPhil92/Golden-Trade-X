//+------------------------------------------------------------------+
//|                                           PartialTakeProfit.mqh  |
//|   Golden Trade X v2.20 — Cierre parcial al alcanzar R objetivo   |
//+------------------------------------------------------------------+
//  Cierra un % de la posición cuando el flotante alcanza InpPartialTPR,
//  luego deja correr el resto bajo el trailing stop normal.
//  El estado "ya cerrado parcialmente" se persiste en GlobalVariable
//  para sobrevivir reinicios del EA.
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

class CPartialTP
  {
private:
   string m_gvPrefix;
   bool   m_enabled;

   bool IsDone(ulong ticket)
     { return GlobalVariableCheck(m_gvPrefix + IntegerToString(ticket)); }

   void MarkDone(ulong ticket)
     { GlobalVariableSet(m_gvPrefix + IntegerToString(ticket), 1.0); }

public:
   void Init(bool enabled, ulong magic)
     {
      m_enabled = enabled;
      long login = AccountInfoInteger(ACCOUNT_LOGIN);
      m_gvPrefix = StringFormat("GTX_PTP_%d_%d_", (int)login, (int)magic);
     }

   // Llama en ManageTrailing() para cada posición.
   // partialR:   flotante mínimo en R para activar el cierre (ej. 1.0)
   // partialPct: % del lote a cerrar (ej. 50.0)
   // Retorna true si ejecutó el cierre parcial este tick.
   bool Check(CTrade &tradeObj, ulong ticket, double partialR, double partialPct)
     {
      if(!m_enabled || IsDone(ticket)) return false;
      if(!PositionSelectByTicket(ticket)) return false;

      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl        = PositionGetDouble(POSITION_SL);
      double lots      = PositionGetDouble(POSITION_VOLUME);
      long   posType   = PositionGetInteger(POSITION_TYPE);
      string symbol    = PositionGetString(POSITION_SYMBOL);

      double risk = MathAbs(openPrice - sl);
      if(risk <= 0) return false;

      double curPrice = (posType == POSITION_TYPE_BUY)
                        ? SymbolInfoDouble(symbol, SYMBOL_BID)
                        : SymbolInfoDouble(symbol, SYMBOL_ASK);
      double profit   = (posType == POSITION_TYPE_BUY)
                        ? (curPrice - openPrice)
                        : (openPrice - curPrice);

      if(profit / risk < partialR) return false;

      double lotStep  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      double minLot   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double closeVol = MathFloor(lots * partialPct / 100.0 / lotStep) * lotStep;
      closeVol = MathMax(closeVol, minLot);

      if(closeVol >= lots) return false;  // evitar cerrar el total

      if(tradeObj.PositionClosePartial(ticket, closeVol))
        {
         MarkDone(ticket);
         Print("PartialTP ► ticket=", ticket,
               " cerró=", closeVol, " lotes @ R=", DoubleToString(profit/risk, 2));
         return true;
        }
      return false;
     }

   // Limpiar GV al cerrar una posición completamente
   void Cleanup(ulong ticket)
     { GlobalVariableDel(m_gvPrefix + IntegerToString(ticket)); }
  };
//+------------------------------------------------------------------+
