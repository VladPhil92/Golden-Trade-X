//+------------------------------------------------------------------+
//|                                                  RiskManager.mqh |
//|   Golden Trade X — Gestión de riesgo y capital                   |
//+------------------------------------------------------------------+
#property strict

class CRiskManager
  {
private:
   double  m_riskPercent;      // % de equity arriesgado por operación
   double  m_maxDailyDD;       // drawdown diario máximo en %
   int     m_maxPositions;
   double  m_maxSpreadPoints;
   ulong   m_magic;
   double  m_dayStartEquity;
   int     m_currentDay;

   void    UpdateDay()
     {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      if(dt.day != m_currentDay)
        {
         m_currentDay     = dt.day;
         m_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
        }
     }

public:
   void Init(double riskPercent, double maxDailyDD, int maxPositions,
             double maxSpreadPoints, ulong magic)
     {
      m_riskPercent     = riskPercent;
      m_maxDailyDD      = maxDailyDD;
      m_maxPositions    = maxPositions;
      m_maxSpreadPoints = maxSpreadPoints;
      m_magic           = magic;
      m_currentDay      = -1;
      UpdateDay();
     }

   //--- Tamaño de lote según riesgo % y distancia al SL
   double CalculateLotSize(string symbol, double entryPrice, double slPrice)
     {
      double equity     = AccountInfoDouble(ACCOUNT_EQUITY);
      double riskMoney  = equity * m_riskPercent / 100.0;
      double slDistance = MathAbs(entryPrice - slPrice);
      if(slDistance <= 0) return(0);

      double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tickValue <= 0 || tickSize <= 0) return(0);

      double lossPerLot = slDistance / tickSize * tickValue;
      if(lossPerLot <= 0) return(0);

      double lots = riskMoney / lossPerLot;

      //--- Normalizar al step del broker
      double minLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double maxLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double lotStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

      lots = MathFloor(lots / lotStep) * lotStep;
      lots = MathMax(minLot, MathMin(maxLot, lots));
      return(NormalizeDouble(lots, 2));
     }

   //--- Control de drawdown diario
   bool IsDailyDrawdownExceeded()
     {
      UpdateDay();
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      if(m_dayStartEquity <= 0) return(false);
      double dd = (m_dayStartEquity - equity) / m_dayStartEquity * 100.0;
      return(dd >= m_maxDailyDD);
     }

   //--- Filtro de spread
   bool IsSpreadAcceptable(string symbol)
     {
      long spread = SymbolInfoInteger(symbol, SYMBOL_SPREAD);
      return(spread <= (long)m_maxSpreadPoints);
     }

   //--- Posiciones abiertas por este EA
   int CountOpenPositions(string symbol)
     {
      int count = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0) continue;
         if(PositionGetString(POSITION_SYMBOL) == symbol &&
            PositionGetInteger(POSITION_MAGIC) == (long)m_magic)
            count++;
        }
      return(count);
     }
  };
//+------------------------------------------------------------------+
