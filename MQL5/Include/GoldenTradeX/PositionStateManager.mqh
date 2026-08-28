//+------------------------------------------------------------------+
//|                                      PositionStateManager.mqh   |
//| Golden Trade X v2.62 — Estado persistente por POSITION_IDENTIFIER|
//+------------------------------------------------------------------+
//  Fuente de verdad de estado inmutable y excursiones por posición.
//  Clave estable: account + magic + POSITION_IDENTIFIER.
//
//  Persiste mediante Terminal Global Variables:
//    entry price, InitialSL, InitialTP, InitialRiskPrice,
//    InitialRiskMoney, InitialVolume, entry time, confidence, regime,
//    MFE price/R/time y MAE price/R/time.
//
//  El estado puede reconstruirse desde el historial tras un reinicio. Si no
//  se puede demostrar que la posición pertenece exclusivamente a este EA,
//  falla cerrado y no crea estado sintético.
//+------------------------------------------------------------------+
#property strict

struct SPositionState
  {
   ulong    positionId;
   ulong    positionTicket;
   double   entryPrice;
   double   initialSL;
   double   initialTP;
   double   initialRiskPrice;
   double   initialRiskMoney;
   double   initialVolume;
   datetime entryTime;
   int      confidence;
   int      regime;
   double   mfePrice;
   double   mfeR;
   datetime mfeTime;
   double   maePrice;
   double   maeR;
   datetime maeTime;
  };

class CPositionStateManager
  {
private:
   ulong  m_magic;
   long   m_login;
   string m_prefix;

   string Key(ulong positionId, string field)
     { return m_prefix + IntegerToString(positionId) + "_" + field; }

   void Set(ulong positionId, string field, double value)
     { GlobalVariableSet(Key(positionId, field), value); }

   bool Get(ulong positionId, string field, double &value)
     {
      string key = Key(positionId, field);
      if(!GlobalVariableCheck(key)) return false;
      value = GlobalVariableGet(key);
      return true;
     }

   bool HasCoreState(ulong positionId)
     {
      return GlobalVariableCheck(Key(positionId, "ENTRY")) &&
             GlobalVariableCheck(Key(positionId, "ISL")) &&
             GlobalVariableCheck(Key(positionId, "IRP")) &&
             GlobalVariableCheck(Key(positionId, "IRM")) &&
             GlobalVariableCheck(Key(positionId, "IVOL"));
     }

   bool HistoryOwnership(ulong positionId, string symbol,
                         bool &hasOwnEntry, bool &hasForeignEntry)
     {
      hasOwnEntry = false;
      hasForeignEntry = false;
      if(positionId == 0 || !HistorySelectByPosition(positionId)) return false;

      for(int i = 0; i < HistoryDealsTotal(); i++)
        {
         ulong deal = HistoryDealGetTicket(i);
         if(deal == 0) continue;
         long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
         if(entry != DEAL_ENTRY_IN && entry != DEAL_ENTRY_INOUT) continue;
         if(symbol != "" && HistoryDealGetString(deal, DEAL_SYMBOL) != symbol) continue;

         long magic = HistoryDealGetInteger(deal, DEAL_MAGIC);
         if(magic == (long)m_magic) hasOwnEntry = true;
         else                       hasForeignEntry = true;
        }
      return hasOwnEntry;
     }

   bool ReconstructFromHistory(ulong positionId, ulong positionTicket,
                               int confidence, int regime)
     {
      string symbol = "";
      if(positionTicket > 0 && PositionSelectByTicket(positionTicket))
         symbol = PositionGetString(POSITION_SYMBOL);

      bool ownEntry, foreignEntry;
      if(!HistoryOwnership(positionId, symbol, ownEntry, foreignEntry) ||
         !ownEntry || foreignEntry)
        {
         Print("PositionState: FAIL-CLOSED ownership position_id=", positionId,
               " own=", ownEntry ? "true" : "false",
               " foreign=", foreignEntry ? "true" : "false");
         return false;
        }

      if(!HistorySelectByPosition(positionId)) return false;
      datetime earliest = 0;
      double entryPrice = 0.0, initialSL = 0.0, initialTP = 0.0;
      double initialVolume = 0.0;
      long entryType = -1;

      for(int i = 0; i < HistoryDealsTotal(); i++)
        {
         ulong deal = HistoryDealGetTicket(i);
         if(deal == 0) continue;
         if(HistoryDealGetInteger(deal, DEAL_MAGIC) != (long)m_magic) continue;
         long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
         if(entry != DEAL_ENTRY_IN && entry != DEAL_ENTRY_INOUT) continue;

         double vol = HistoryDealGetDouble(deal, DEAL_VOLUME);
         initialVolume += vol;

         datetime t = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
         if(earliest == 0 || t < earliest)
           {
            earliest = t;
            entryPrice = HistoryDealGetDouble(deal, DEAL_PRICE);
            initialSL = HistoryDealGetDouble(deal, DEAL_SL);
            initialTP = HistoryDealGetDouble(deal, DEAL_TP);
            entryType = HistoryDealGetInteger(deal, DEAL_TYPE);
            if(symbol == "") symbol = HistoryDealGetString(deal, DEAL_SYMBOL);
           }
        }

      if(entryPrice <= 0 || initialSL <= 0 || initialVolume <= 0 || symbol == "")
        {
         Print("PositionState: FAIL-CLOSED initial data missing position_id=", positionId);
         return false;
        }

      bool isBuy = (entryType == DEAL_TYPE_BUY);
      if((isBuy && initialSL >= entryPrice) || (!isBuy && initialSL <= entryPrice))
        return false;

      double initialRiskPrice = MathAbs(entryPrice - initialSL);
      double pnlAtStop = 0.0;
      ENUM_ORDER_TYPE orderType = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      if(!OrderCalcProfit(orderType, symbol, initialVolume,
                          entryPrice, initialSL, pnlAtStop))
        {
         Print("PositionState: OrderCalcProfit failed position_id=", positionId,
               " error=", GetLastError());
         return false;
        }
      double initialRiskMoney = MathAbs(pnlAtStop);
      if(initialRiskPrice <= 0 || initialRiskMoney <= 0) return false;

      Set(positionId, "ENTRY", entryPrice);
      Set(positionId, "ISL", initialSL);
      Set(positionId, "ITP", initialTP);
      Set(positionId, "IRP", initialRiskPrice);
      Set(positionId, "IRM", initialRiskMoney);
      Set(positionId, "IVOL", initialVolume);
      Set(positionId, "ETIME", (double)earliest);
      Set(positionId, "CONF", (double)confidence);
      Set(positionId, "REG", (double)regime);
      Set(positionId, "MFE_R", 0.0);
      Set(positionId, "MAE_R", 0.0);
      Set(positionId, "MFE_P", entryPrice);
      Set(positionId, "MAE_P", entryPrice);
      Set(positionId, "MFE_T", (double)earliest);
      Set(positionId, "MAE_T", (double)earliest);

      Print("PositionState: reconstructed position_id=", positionId,
            " initialRiskMoney=", DoubleToString(initialRiskMoney, 2));
      return true;
     }

public:
   void Init(ulong magic)
     {
      m_magic = magic;
      m_login = AccountInfoInteger(ACCOUNT_LOGIN);
      m_prefix = StringFormat("GTX_PS_%d_%d_", (int)m_login, (int)m_magic);
     }

   ulong FindPositionTicket(ulong positionId, string symbol = "")
     {
      if(positionId == 0) return 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0) continue;
         if((ulong)PositionGetInteger(POSITION_IDENTIFIER) != positionId) continue;
         if(symbol != "" && PositionGetString(POSITION_SYMBOL) != symbol) continue;
         return ticket;
        }
      return 0;
     }

   bool IsPositionOpen(ulong positionId)
     { return FindPositionTicket(positionId) != 0; }

   bool PositionBelongsExclusivelyToEA(ulong positionId, string symbol = "")
     {
      bool ownEntry, foreignEntry;
      if(!HistoryOwnership(positionId, symbol, ownEntry, foreignEntry)) return false;
      return ownEntry && !foreignEntry;
     }

   // Llamar inmediatamente tras apertura server-confirmed con la posición
   // seleccionable. Si no hay estado, reconstruye desde historial.
   bool EnsurePosition(ulong positionTicket, int confidence = -1, int regime = -1)
     {
      if(positionTicket == 0 || !PositionSelectByTicket(positionTicket)) return false;
      if(PositionGetInteger(POSITION_MAGIC) != (long)m_magic) return false;

      ulong positionId = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
      if(positionId == 0) return false;

      if(!HasCoreState(positionId))
        {
         if(!ReconstructFromHistory(positionId, positionTicket, confidence, regime))
            return false;
        }
      else
        {
         if(confidence >= 0) Set(positionId, "CONF", (double)confidence);
         if(regime >= 0)     Set(positionId, "REG", (double)regime);
        }
      return true;
     }

   int ReconcileOpenPositions()
     {
      int reconstructed = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0) continue;
         if(PositionGetInteger(POSITION_MAGIC) != (long)m_magic) continue;
         ulong positionId = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
         if(positionId == 0) continue;
         if(!HasCoreState(positionId) && EnsurePosition(ticket)) reconstructed++;
        }
      if(reconstructed > 0)
         Print("PositionState: ", reconstructed,
               " posición(es) reconstruida(s) al iniciar.");
      return reconstructed;
     }

   bool Load(ulong positionId, SPositionState &s)
     {
      ZeroMemory(s);
      if(!HasCoreState(positionId)) return false;

      double v;
      s.positionId = positionId;
      s.positionTicket = FindPositionTicket(positionId);
      if(Get(positionId, "ENTRY", v)) s.entryPrice = v;
      if(Get(positionId, "ISL", v))   s.initialSL = v;
      if(Get(positionId, "ITP", v))   s.initialTP = v;
      if(Get(positionId, "IRP", v))   s.initialRiskPrice = v;
      if(Get(positionId, "IRM", v))   s.initialRiskMoney = v;
      if(Get(positionId, "IVOL", v))  s.initialVolume = v;
      if(Get(positionId, "ETIME", v)) s.entryTime = (datetime)v;
      if(Get(positionId, "CONF", v))  s.confidence = (int)v; else s.confidence = -1;
      if(Get(positionId, "REG", v))   s.regime = (int)v; else s.regime = -1;
      if(Get(positionId, "MFE_P", v)) s.mfePrice = v;
      if(Get(positionId, "MFE_R", v)) s.mfeR = v;
      if(Get(positionId, "MFE_T", v)) s.mfeTime = (datetime)v;
      if(Get(positionId, "MAE_P", v)) s.maePrice = v;
      if(Get(positionId, "MAE_R", v)) s.maeR = v;
      if(Get(positionId, "MAE_T", v)) s.maeTime = (datetime)v;
      return s.entryPrice > 0 && s.initialRiskPrice > 0 && s.initialRiskMoney > 0;
     }

   bool UpdateExcursions(ulong positionTicket)
     {
      if(positionTicket == 0 || !PositionSelectByTicket(positionTicket)) return false;
      if(PositionGetInteger(POSITION_MAGIC) != (long)m_magic) return false;

      ulong positionId = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
      if(positionId == 0) return false;
      if(!HasCoreState(positionId) && !EnsurePosition(positionTicket)) return false;

      SPositionState s;
      if(!Load(positionId, s)) return false;

      string symbol = PositionGetString(POSITION_SYMBOL);
      long type = PositionGetInteger(POSITION_TYPE);
      double price = (type == POSITION_TYPE_BUY)
                     ? SymbolInfoDouble(symbol, SYMBOL_BID)
                     : SymbolInfoDouble(symbol, SYMBOL_ASK);
      if(price <= 0) return false;

      double favorable = (type == POSITION_TYPE_BUY)
                         ? (price - s.entryPrice)
                         : (s.entryPrice - price);
      double adverse = (type == POSITION_TYPE_BUY)
                       ? (s.entryPrice - price)
                       : (price - s.entryPrice);
      double currentMfeR = MathMax(0.0, favorable / s.initialRiskPrice);
      double currentMaeR = MathMax(0.0, adverse / s.initialRiskPrice);
      datetime now = TimeCurrent();

      if(currentMfeR > s.mfeR)
        {
         Set(positionId, "MFE_R", currentMfeR);
         Set(positionId, "MFE_P", price);
         Set(positionId, "MFE_T", (double)now);
        }
      if(currentMaeR > s.maeR)
        {
         Set(positionId, "MAE_R", currentMaeR);
         Set(positionId, "MAE_P", price);
         Set(positionId, "MAE_T", (double)now);
        }
      return true;
     }

   void Cleanup(ulong positionId)
     {
      if(positionId == 0) return;
      string fields[] = {
         "ENTRY","ISL","ITP","IRP","IRM","IVOL","ETIME","CONF","REG",
         "MFE_P","MFE_R","MFE_T","MAE_P","MAE_R","MAE_T"
      };
      for(int i = 0; i < ArraySize(fields); i++)
         GlobalVariableDel(Key(positionId, fields[i]));
     }
  };
//+------------------------------------------------------------------+
