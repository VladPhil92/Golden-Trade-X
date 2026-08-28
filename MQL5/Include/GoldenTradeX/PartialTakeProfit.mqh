//+------------------------------------------------------------------+
//|                                           PartialTakeProfit.mqh  |
//|   Golden Trade X v2.62 — Partial TP basado en Initial R          |
//+------------------------------------------------------------------+
//  Cierra un % de la posición cuando el flotante alcanza el múltiplo
//  configurado del R INICIAL. El riesgo nunca se recalcula usando el SL
//  actual, porque break-even/trailing modifican ese SL y podrían disparar
//  prematuramente el parcial.
//
//  La fuente de verdad del Initial R es el deal de entrada de la posición:
//    initialRiskPrice = abs(entryPrice - initialSL)
//  HistorySelectByPosition(POSITION_IDENTIFIER) permite reconstruirlo tras
//  reinicios del EA. Si no puede reconstruirse de forma segura, fail closed:
//  NO ejecuta el parcial.
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

class CPartialTP
  {
private:
   string m_gvPrefix;
   bool   m_enabled;
   ulong  m_magic;

   bool IsDone(ulong positionId)
     { return GlobalVariableCheck(m_gvPrefix + IntegerToString(positionId)); }

   void MarkDone(ulong positionId)
     { GlobalVariableSet(m_gvPrefix + IntegerToString(positionId), 1.0); }

   // Reconstruye el precio de entrada y SL originales usando el identificador
   // estable de posición. Solo acepta deals pertenecientes a esta instancia.
   bool GetInitialRiskData(ulong positionId, string symbol,
                           double &entryPrice, double &initialSL,
                           double &initialRiskPrice)
     {
      entryPrice = 0.0;
      initialSL = 0.0;
      initialRiskPrice = 0.0;
      if(positionId == 0 || !HistorySelectByPosition(positionId)) return false;

      datetime earliest = 0;
      for(int i = 0; i < HistoryDealsTotal(); i++)
        {
         ulong deal = HistoryDealGetTicket(i);
         if(deal == 0) continue;
         if(HistoryDealGetInteger(deal, DEAL_MAGIC) != (long)m_magic) continue;
         if(HistoryDealGetString(deal, DEAL_SYMBOL) != symbol) continue;

         long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
         if(entry != DEAL_ENTRY_IN && entry != DEAL_ENTRY_INOUT) continue;

         datetime dealTime = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
         double dealSL = HistoryDealGetDouble(deal, DEAL_SL);
         double dealPrice = HistoryDealGetDouble(deal, DEAL_PRICE);
         if(dealPrice <= 0 || dealSL <= 0) continue;

         if(earliest == 0 || dealTime < earliest)
           {
            earliest = dealTime;
            entryPrice = dealPrice;
            initialSL = dealSL;
           }
        }

      if(entryPrice <= 0 || initialSL <= 0) return false;
      initialRiskPrice = MathAbs(entryPrice - initialSL);
      return initialRiskPrice > 0;
     }

public:
   void Init(bool enabled, ulong magic)
     {
      m_enabled = enabled;
      m_magic = magic;
      long login = AccountInfoInteger(ACCOUNT_LOGIN);
      // v2.62: estado por POSITION_IDENTIFIER, no por ticket mutable.
      m_gvPrefix = StringFormat("GTX_PTP_%d_%d_PID_", (int)login, (int)magic);
     }

   bool Check(CTrade &tradeObj, ulong ticket, double partialR, double partialPct)
     {
      if(!m_enabled) return false;
      if(!PositionSelectByTicket(ticket)) return false;

      ulong positionId = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
      if(positionId == 0 || IsDone(positionId)) return false;

      double currentOpen = PositionGetDouble(POSITION_PRICE_OPEN);
      double lots        = PositionGetDouble(POSITION_VOLUME);
      long   posType     = PositionGetInteger(POSITION_TYPE);
      string symbol      = PositionGetString(POSITION_SYMBOL);

      double initialEntry, initialSL, initialRisk;
      if(!GetInitialRiskData(positionId, symbol, initialEntry, initialSL, initialRisk))
        {
         Print("PartialTP: FAIL-CLOSED — no se pudo reconstruir Initial R para position_id=",
               positionId, " ticket=", ticket, ". Parcial omitido.");
         return false;
        }

      double curPrice = (posType == POSITION_TYPE_BUY)
                        ? SymbolInfoDouble(symbol, SYMBOL_BID)
                        : SymbolInfoDouble(symbol, SYMBOL_ASK);
      double profitDistance = (posType == POSITION_TYPE_BUY)
                              ? (curPrice - initialEntry)
                              : (initialEntry - curPrice);
      double currentR = profitDistance / initialRisk;

      if(currentR < partialR) return false;

      double lotStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      double minLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      if(lotStep <= 0 || minLot <= 0) return false;

      double closeVol = MathFloor(lots * partialPct / 100.0 / lotStep) * lotStep;
      closeVol = MathMax(closeVol, minLot);

      if(closeVol >= lots)
        {
         MarkDone(positionId);
         Print("PartialTP: lote ", DoubleToString(lots, 2), " no divisible ",
               "(minLot=", DoubleToString(minLot, 2), ") — parcial omitido ",
               "para position_id=", positionId, ".");
         return false;
        }

      // CTrade::PositionClosePartial(true) solo confirma chequeo local; exigir
      // retcode server-side + deal antes de persistir MarkDone.
      bool basicOk = tradeObj.PositionClosePartial(ticket, closeVol);
      uint rc = tradeObj.ResultRetcode();
      bool serverConfirmed =
         (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_DONE_PARTIAL) &&
         tradeObj.ResultDeal() != 0;

      if(serverConfirmed)
        {
         MarkDone(positionId);
         Print("PartialTP ► position_id=", positionId,
               " ticket=", ticket,
               " cerró=", closeVol,
               " lotes @ InitialR=", DoubleToString(currentR, 2),
               " deal=", tradeObj.ResultDeal());
         return true;
        }

      Print("PartialTP: cierre NO confirmado por servidor position_id=", positionId,
            " basic_ok=", basicOk ? "true" : "false",
            " retcode=", rc, " comment=", tradeObj.ResultComment());
      return false;
     }

   // Limpiar estado al cierre total usando el identificador estable.
   void Cleanup(ulong positionId)
     {
      if(positionId == 0) return;
      GlobalVariableDel(m_gvPrefix + IntegerToString(positionId));
     }
  };
//+------------------------------------------------------------------+
