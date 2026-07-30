//+------------------------------------------------------------------+
//|                                                  RiskManager.mqh |
//|   Golden Trade X v2.40 — Gestión de riesgo y capital             |
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
   int     m_currentDay;
   string  m_gvDayKey;
   string  m_gvEquityKey;

   int     m_consecutiveLosses;
   int     m_maxConsecutiveLosses;
   double  m_maxWeeklyDD;
   double  m_weekStartEquity;
   int     m_currentWeek;
   string  m_gvWeekKey;
   string  m_gvWeekEquityKey;
   string  m_gvConsecLossKey;

   // v2.00: circuit breaker y capital preservation
   double  m_maxMonthlyDD;
   double  m_monthStartEquity;
   int     m_currentMonth;
   string  m_gvMonthKey;
   string  m_gvMonthEquityKey;
   bool    m_killSwitch;
   string  m_gvKillSwitchKey;       // v2.20: persiste kill switch entre reinicios
   bool    m_capitalPreservation;
   double  m_cpThresholdPct;

   // v2.40: Kelly Criterion fraccional
   bool    m_useKelly;
   double  m_kellyFraction;         // 0.25 = Quarter-Kelly (recomendado)
   int     m_kellyMinTrades;        // trades mínimos antes de activar Kelly

   // Calcula W (win rate) y R (win/loss ratio) desde historial real del EA
   bool CalcWinRateAndR(double &winRate, double &avgR)
     {
      datetime from = TimeCurrent() - 90 * 24 * 3600;   // ventana 90 días
      if(!HistorySelect(from, TimeCurrent())) return false;

      double sumWins = 0, sumLosses = 0;
      int    wins = 0, losses = 0;

      int total = HistoryDealsTotal();
      for(int i = 0; i < total; i++)
        {
         ulong ticket = HistoryDealGetTicket(i);
         if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != (long)m_magic) continue;
         long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
         if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT) continue;

         double net = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                    + HistoryDealGetDouble(ticket, DEAL_COMMISSION)
                    + HistoryDealGetDouble(ticket, DEAL_SWAP);

         if(net > 0) { sumWins   += net;         wins++;   }
         else        { sumLosses += MathAbs(net); losses++; }
        }

      if(wins + losses < m_kellyMinTrades) return false;

      winRate     = (double)wins / (wins + losses);
      double avgW = wins    > 0 ? sumWins   / wins    : 0;
      double avgL = losses  > 0 ? sumLosses / losses  : 1;
      avgR        = avgW / avgL;

      return (avgR > 0 && winRate > 0 && winRate < 1.0);
     }

   // Retorna el % de riesgo óptimo según Kelly (ya aplicado m_kellyFraction)
   // Formula: f* = W - (1-W)/R  → fraccionada × 100 para obtener %
   double CalcKellyRiskPct()
     {
      double winRate, avgR;
      if(!CalcWinRateAndR(winRate, avgR))
        {
         Print("Kelly: historial insuficiente — usando riesgo fijo ", m_riskPercent, "%");
         return m_riskPercent;
        }

      double kellyFull = winRate - (1.0 - winRate) / avgR;
      if(kellyFull <= 0)
        {
         Print("Kelly: sin edge detectado (f*=", DoubleToString(kellyFull,4),
               ") — reduciendo riesgo al 50%");
         return m_riskPercent * 0.5;
        }

      double kellyPct = kellyFull * m_kellyFraction * 100.0;
      double capped   = MathMin(kellyPct, m_riskPercent * 2.0);  // techo = 2× riesgo fijo

      Print("Kelly f*=", DoubleToString(kellyFull*100,2), "% → ",
            DoubleToString(m_kellyFraction*100,0), "% fracción → ",
            DoubleToString(capped,3), "% riesgo efectivo",
            " (W=", DoubleToString(winRate*100,1), "% R=", DoubleToString(avgR,2), ")");

      return capped;
     }

   void UpdateDay()
     {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      int todayIndex = dt.year * 10000 + dt.mon * 100 + dt.day;
      if(todayIndex == m_currentDay) return;
      if(GlobalVariableCheck(m_gvDayKey))
        {
         int p = (int)GlobalVariableGet(m_gvDayKey);
         if(p == todayIndex && GlobalVariableCheck(m_gvEquityKey))
           { m_currentDay = todayIndex; m_dayStartEquity = GlobalVariableGet(m_gvEquityKey); return; }
        }
      m_currentDay     = todayIndex;
      m_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      GlobalVariableSet(m_gvDayKey,    (double)m_currentDay);
      GlobalVariableSet(m_gvEquityKey, m_dayStartEquity);
     }

   void UpdateWeek()
     {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      int weekIndex = dt.year * 100 + (dt.day_of_year + 1) / 7;
      if(weekIndex == m_currentWeek) return;
      if(GlobalVariableCheck(m_gvWeekKey))
        {
         int p = (int)GlobalVariableGet(m_gvWeekKey);
         if(p == weekIndex && GlobalVariableCheck(m_gvWeekEquityKey))
           {
            m_currentWeek     = weekIndex;
            m_weekStartEquity = GlobalVariableGet(m_gvWeekEquityKey);
            m_consecutiveLosses = 0;
            return;
           }
        }
      m_currentWeek     = weekIndex;
      m_weekStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      m_consecutiveLosses = 0;
      GlobalVariableSet(m_gvWeekKey,       (double)m_currentWeek);
      GlobalVariableSet(m_gvWeekEquityKey, m_weekStartEquity);
     }

   void UpdateMonth()
     {
      if(m_maxMonthlyDD <= 0) return;
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      int monthIndex = dt.year * 100 + dt.mon;
      if(monthIndex == m_currentMonth) return;
      if(GlobalVariableCheck(m_gvMonthKey))
        {
         int p = (int)GlobalVariableGet(m_gvMonthKey);
         if(p == monthIndex && GlobalVariableCheck(m_gvMonthEquityKey))
           { m_currentMonth = monthIndex; m_monthStartEquity = GlobalVariableGet(m_gvMonthEquityKey); return; }
        }
      m_currentMonth     = monthIndex;
      m_monthStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      GlobalVariableSet(m_gvMonthKey,       (double)m_currentMonth);
      GlobalVariableSet(m_gvMonthEquityKey, m_monthStartEquity);
     }

public:
   void Init(double riskPercent, double maxDailyDD, int maxPositions,
             double maxSpreadPoints, ulong magic,
             int maxConsecutiveLosses, double maxWeeklyDD,
             double maxMonthlyDD = 0.0,
             double cpThresholdPct = 8.0)
     {
      m_riskPercent          = riskPercent;
      m_maxDailyDD           = maxDailyDD;
      m_maxPositions         = maxPositions;
      m_maxSpreadPoints      = maxSpreadPoints;
      m_magic                = magic;
      m_currentDay           = -1;
      m_maxConsecutiveLosses = maxConsecutiveLosses;
      m_maxWeeklyDD          = maxWeeklyDD;
      m_currentWeek          = -1;
      m_weekStartEquity      = 0;
      m_maxMonthlyDD         = maxMonthlyDD;
      m_currentMonth         = -1;
      m_monthStartEquity     = 0;
      m_killSwitch           = false;
      m_capitalPreservation  = false;
      m_cpThresholdPct       = cpThresholdPct;
      m_useKelly             = false;
      m_kellyFraction        = 0.25;
      m_kellyMinTrades       = 30;

      long login = AccountInfoInteger(ACCOUNT_LOGIN);
      m_gvDayKey         = StringFormat("GTX_%d_%d_Day",         (int)login, (int)magic);
      m_gvEquityKey      = StringFormat("GTX_%d_%d_Equity",      (int)login, (int)magic);
      m_gvWeekKey        = StringFormat("GTX_%d_%d_Week",        (int)login, (int)magic);
      m_gvWeekEquityKey  = StringFormat("GTX_%d_%d_WeekEquity",  (int)login, (int)magic);
      m_gvConsecLossKey  = StringFormat("GTX_%d_%d_ConsecLoss",  (int)login, (int)magic);
      m_gvMonthKey       = StringFormat("GTX_%d_%d_Month",       (int)login, (int)magic);
      m_gvMonthEquityKey = StringFormat("GTX_%d_%d_MonthEquity", (int)login, (int)magic);
      m_gvKillSwitchKey  = StringFormat("GTX_%d_%d_KillSwitch",  (int)login, (int)magic);

      if(GlobalVariableCheck(m_gvConsecLossKey))
         m_consecutiveLosses = (int)GlobalVariableGet(m_gvConsecLossKey);
      else
         m_consecutiveLosses = 0;

      // v2.20: restaurar kill switch desde GlobalVariable (sobrevive reinicios)
      m_killSwitch = GlobalVariableCheck(m_gvKillSwitchKey) &&
                     GlobalVariableGet(m_gvKillSwitchKey) != 0.0;
      if(m_killSwitch)
         Print("RiskManager: Kill Switch estaba ACTIVO — restaurado desde GlobalVariable.");

      UpdateDay();
      UpdateWeek();
      UpdateMonth();
     }

   // v2.40: activar Kelly Criterion
   void InitKelly(bool useKelly, double fraction, int minTrades)
     {
      m_useKelly       = useKelly;
      m_kellyFraction  = MathMax(0.01, MathMin(fraction, 1.0));
      m_kellyMinTrades = MathMax(10, minTrades);
      if(m_useKelly)
         Print("RiskManager: Kelly Criterion ON — fracción=",
               DoubleToString(m_kellyFraction*100,0), "% minTrades=", m_kellyMinTrades);
     }

   //--- Lote con multiplicador de riesgo adaptativo (v2.40: soporte Kelly)
   double CalculateLotSize(string symbol, double entryPrice, double slPrice)
     {
      double equity       = AccountInfoDouble(ACCOUNT_EQUITY);
      double baseRisk     = m_useKelly ? CalcKellyRiskPct() : m_riskPercent;
      double effectiveRisk = m_capitalPreservation ? baseRisk * 0.25 : baseRisk;
      double riskMoney  = equity * effectiveRisk / 100.0;
      double slDistance = MathAbs(entryPrice - slPrice);
      if(slDistance <= 0) return 0;

      double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tickValue <= 0 || tickSize <= 0) return 0;

      double lossPerLot = slDistance / tickSize * tickValue;
      if(lossPerLot <= 0) return 0;

      double lots = riskMoney / lossPerLot * GetPositionSizeMultiplier();

      double minLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double maxLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double lotStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

      lots = MathFloor(lots / lotStep) * lotStep;
      if(lots < minLot) return 0;
      lots = MathMin(maxLot, lots);

      int decimals;
      if(lotStep >= 1.0)       decimals = 0;
      else if(lotStep >= 0.1)  decimals = 1;
      else if(lotStep >= 0.01) decimals = 2;
      else                     decimals = 3;

      return NormalizeDouble(lots, decimals);
     }

   //--- Drawdown checks
   bool IsDailyDrawdownExceeded()
     {
      UpdateDay();
      if(m_dayStartEquity <= 0) return false;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      return ((m_dayStartEquity - equity) / m_dayStartEquity * 100.0) >= m_maxDailyDD;
     }

   bool IsWeeklyDrawdownExceeded()
     {
      UpdateWeek();
      if(m_weekStartEquity <= 0 || m_maxWeeklyDD <= 0) return false;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      return ((m_weekStartEquity - equity) / m_weekStartEquity * 100.0) >= m_maxWeeklyDD;
     }

   // Circuit Breaker mensual
   bool IsMonthlyCircuitBreakerTripped()
     {
      UpdateMonth();
      if(m_maxMonthlyDD <= 0 || m_monthStartEquity <= 0) return false;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      return ((m_monthStartEquity - equity) / m_monthStartEquity * 100.0) >= m_maxMonthlyDD;
     }

   //--- Capital Preservation Mode: se activa automáticamente si el DD diario supera umbral
   bool IsCapitalPreservationActive()
     {
      UpdateDay();
      if(m_dayStartEquity <= 0) return false;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double dd = (m_dayStartEquity - equity) / m_dayStartEquity * 100.0;
      m_capitalPreservation = (dd >= m_cpThresholdPct);
      return m_capitalPreservation;
     }

   //--- Kill Switch de emergencia (parada total, persiste hasta reset manual)
   void SetKillSwitch(bool active)
     {
      m_killSwitch = active;
      GlobalVariableSet(m_gvKillSwitchKey, active ? 1.0 : 0.0);  // v2.20: persistir
      if(active)
         Print("RiskManager: KILL SWITCH activado. Sin operaciones hasta desactivar.");
      else
         Print("RiskManager: KILL SWITCH desactivado.");
     }
   bool IsKillSwitchActive() { return m_killSwitch; }

   //--- Tracking de pérdidas consecutivas
   void RegisterTradeResult(double profitLoss)
     {
      m_consecutiveLosses = (profitLoss < 0) ? m_consecutiveLosses + 1 : 0;
      GlobalVariableSet(m_gvConsecLossKey, (double)m_consecutiveLosses);
     }

   bool IsConsecutiveLossLimitReached()
     {
      if(m_maxConsecutiveLosses <= 0) return false;
      return m_consecutiveLosses >= m_maxConsecutiveLosses;
     }

   double GetPositionSizeMultiplier()
     {
      if(m_consecutiveLosses >= 2) return 0.75;
      return 1.0;
     }

   bool IsSpreadAcceptable(string symbol)
     {
      return SymbolInfoInteger(symbol, SYMBOL_SPREAD) <= (long)m_maxSpreadPoints;
     }

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
      return count;
     }

   // Resumen del estado de riesgo para el Journal
   void PrintStatus()
     {
      Print("RiskManager | ConsecLoss=", m_consecutiveLosses,
            " | KillSwitch=", m_killSwitch ? "ON" : "OFF",
            " | CapPreserv=", m_capitalPreservation ? "ON" : "OFF",
            " | CircuitBreaker=", IsMonthlyCircuitBreakerTripped() ? "TRIPPED" : "OK");
     }
  };
//+------------------------------------------------------------------+
