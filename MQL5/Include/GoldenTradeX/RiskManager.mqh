//+------------------------------------------------------------------+
//|                                                  RiskManager.mqh |
//|   Golden Trade X — Gestión de riesgo y capital                   |
//+------------------------------------------------------------------+
#property strict

class CRiskManager
  {
private:
   double  m_riskPercent;
   double  m_maxDailyDD;
   int     m_maxPositions;
   double  m_maxSpreadPoints;
   ulong   m_magic;
   double  m_dayStartEquity;
   int     m_currentDay;      // año*10000 + mes*100 + día
   string  m_gvDayKey;        // GlobalVariable: día persistido
   string  m_gvEquityKey;     // GlobalVariable: equity de inicio de día

   void UpdateDay()
     {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      int todayIndex = dt.year * 10000 + dt.mon * 100 + dt.day;

      if(todayIndex == m_currentDay) return;

      // Intentar recuperar el valor persistido para hoy (sobrevive a reinicios del EA)
      if(GlobalVariableCheck(m_gvDayKey))
        {
         int persistedDay = (int)GlobalVariableGet(m_gvDayKey);
         if(persistedDay == todayIndex && GlobalVariableCheck(m_gvEquityKey))
           {
            m_currentDay     = todayIndex;
            m_dayStartEquity = GlobalVariableGet(m_gvEquityKey);
            return;
           }
        }

      // Nuevo día o sin datos persistidos: registrar equity actual
      m_currentDay     = todayIndex;
      m_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      GlobalVariableSet(m_gvDayKey,    (double)m_currentDay);
      GlobalVariableSet(m_gvEquityKey, m_dayStartEquity);
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

      long login = AccountInfoInteger(ACCOUNT_LOGIN);
      m_gvDayKey    = StringFormat("GTX_%d_%d_Day",    (int)login, (int)magic);
      m_gvEquityKey = StringFormat("GTX_%d_%d_Equity", (int)login, (int)magic);

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

      double lots    = riskMoney / lossPerLot;
      double minLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double maxLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double lotStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

      lots = MathFloor(lots / lotStep) * lotStep;

      // Si el lote calculado es menor al mínimo del broker, el riesgo real
      // superaría el % configurado — rechazar la entrada en lugar de sobreapalancar
      if(lots < minLot) return(0);

      lots = MathMin(maxLot, lots);

      // Precisión dinámica según step del broker (0.01 → 2 dec, 0.001 → 3 dec)
      int decimals;
      if(lotStep >= 1.0)       decimals = 0;
      else if(lotStep >= 0.1)  decimals = 1;
      else if(lotStep >= 0.01) decimals = 2;
      else                     decimals = 3;

      return(NormalizeDouble(lots, decimals));
     }

   //--- Control de drawdown diario
   bool IsDailyDrawdownExceeded()
     {
      UpdateDay();
      if(m_dayStartEquity <= 0) return(false);
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
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
