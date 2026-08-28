//+------------------------------------------------------------------+
//|                                                  RiskManager.mqh |
//|   Golden Trade X v2.62 — Gestión de riesgo y capital             |
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

   double  m_maxMonthlyDD;
   double  m_monthStartEquity;
   int     m_currentMonth;
   string  m_gvMonthKey;
   string  m_gvMonthEquityKey;
   bool    m_killSwitch;
   string  m_gvKillSwitchKey;
   bool    m_capitalPreservation;
   double  m_cpThresholdPct;

   bool    m_useKelly;
   double  m_kellyFraction;
   int     m_kellyMinTrades;

   bool    m_usePortfolioCap;
   double  m_maxPortfolioRiskPct;
   string  m_gvPortfolioRiskKey;
   // v2.62: reservas indexadas por POSITION_IDENTIFIER (DEAL_POSITION_ID),
   // no por el ticket mutable de la posición.
   string  m_gvPortfolioPrefix;

   bool PositionIdentifierIsOpen(ulong positionId)
     {
      if(positionId == 0) return false;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0) continue;
         if((ulong)PositionGetInteger(POSITION_IDENTIFIER) == positionId)
            return true;
        }
      return false;
     }

   bool CalcWinRateAndR(double &winRate, double &avgR)
     {
      datetime from = TimeCurrent() - 90 * 24 * 3600;
      if(!HistorySelect(from, TimeCurrent())) return false;

      ulong  posIds[];
      double posNet[];
      int    nPos = 0;

      int total = HistoryDealsTotal();
      for(int i = 0; i < total; i++)
        {
         ulong ticket = HistoryDealGetTicket(i);
         if(ticket == 0) continue;
         if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != (long)m_magic) continue;
         long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
         if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT) continue;

         double net = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                    + HistoryDealGetDouble(ticket, DEAL_COMMISSION)
                    + HistoryDealGetDouble(ticket, DEAL_SWAP)
                    + HistoryDealGetDouble(ticket, DEAL_FEE);

         ulong pid = (ulong)HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
         int idx = -1;
         for(int j = 0; j < nPos; j++)
            if(posIds[j] == pid) { idx = j; break; }
         if(idx < 0)
           {
            ArrayResize(posIds, nPos + 1);
            ArrayResize(posNet, nPos + 1);
            posIds[nPos] = pid;
            posNet[nPos] = 0.0;
            idx = nPos;
            nPos++;
           }
         posNet[idx] += net;
        }

      double sumWins = 0, sumLosses = 0;
      int wins = 0, losses = 0;
      for(int j = 0; j < nPos; j++)
        {
         if(posNet[j] > 0) { sumWins += posNet[j]; wins++; }
         else if(posNet[j] < 0) { sumLosses += MathAbs(posNet[j]); losses++; }
        }

      if(wins + losses < m_kellyMinTrades) return false;
      if(wins == 0 || losses == 0) return false;

      winRate = (double)wins / (wins + losses);
      double avgW = sumWins / wins;
      double avgL = sumLosses / losses;
      if(avgL <= 0) return false;
      avgR = avgW / avgL;
      return (avgR > 0 && winRate > 0 && winRate < 1.0);
     }

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
      double capped = MathMin(kellyPct, m_riskPercent * 2.0);

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
      m_currentDay = todayIndex;
      m_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      GlobalVariableSet(m_gvDayKey, (double)m_currentDay);
      GlobalVariableSet(m_gvEquityKey, m_dayStartEquity);
     }

   void UpdateWeek()
     {
      int weekIndex = (int)((TimeCurrent() / 86400 + 4) / 7);
      if(weekIndex == m_currentWeek) return;
      if(GlobalVariableCheck(m_gvWeekKey))
        {
         int p = (int)GlobalVariableGet(m_gvWeekKey);
         if(p == weekIndex && GlobalVariableCheck(m_gvWeekEquityKey))
           {
            m_currentWeek = weekIndex;
            m_weekStartEquity = GlobalVariableGet(m_gvWeekEquityKey);
            m_consecutiveLosses = 0;
            return;
           }
        }
      m_currentWeek = weekIndex;
      m_weekStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      m_consecutiveLosses = 0;
      GlobalVariableSet(m_gvWeekKey, (double)m_currentWeek);
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
      m_currentMonth = monthIndex;
      m_monthStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      GlobalVariableSet(m_gvMonthKey, (double)m_currentMonth);
      GlobalVariableSet(m_gvMonthEquityKey, m_monthStartEquity);
     }

public:
   void Init(double riskPercent, double maxDailyDD, int maxPositions,
             double maxSpreadPoints, ulong magic,
             int maxConsecutiveLosses, double maxWeeklyDD,
             double maxMonthlyDD = 0.0,
             double cpThresholdPct = 8.0)
     {
      m_riskPercent = riskPercent;
      m_maxDailyDD = maxDailyDD;
      m_maxPositions = maxPositions;
      m_maxSpreadPoints = maxSpreadPoints;
      m_magic = magic;
      m_currentDay = -1;
      m_maxConsecutiveLosses = maxConsecutiveLosses;
      m_maxWeeklyDD = maxWeeklyDD;
      m_currentWeek = -1;
      m_weekStartEquity = 0;
      m_maxMonthlyDD = maxMonthlyDD;
      m_currentMonth = -1;
      m_monthStartEquity = 0;
      m_killSwitch = false;
      m_capitalPreservation = false;
      m_cpThresholdPct = cpThresholdPct;
      m_useKelly = false;
      m_kellyFraction = 0.25;
      m_kellyMinTrades = 30;
      m_usePortfolioCap = false;
      m_maxPortfolioRiskPct = 1.5;

      long login = AccountInfoInteger(ACCOUNT_LOGIN);
      m_gvPortfolioRiskKey = StringFormat("GTX_%d_PortfolioRiskPct", (int)login);
      m_gvPortfolioPrefix = StringFormat("GTX_%d_PR_PID_", (int)login);
      m_gvDayKey = StringFormat("GTX_%d_%d_Day", (int)login, (int)magic);
      m_gvEquityKey = StringFormat("GTX_%d_%d_Equity", (int)login, (int)magic);
      m_gvWeekKey = StringFormat("GTX_%d_%d_Week", (int)login, (int)magic);
      m_gvWeekEquityKey = StringFormat("GTX_%d_%d_WeekEquity", (int)login, (int)magic);
      m_gvConsecLossKey = StringFormat("GTX_%d_%d_ConsecLoss", (int)login, (int)magic);
      m_gvMonthKey = StringFormat("GTX_%d_%d_Month", (int)login, (int)magic);
      m_gvMonthEquityKey = StringFormat("GTX_%d_%d_MonthEquity", (int)login, (int)magic);
      m_gvKillSwitchKey = StringFormat("GTX_%d_%d_KillSwitch", (int)login, (int)magic);

      if(GlobalVariableCheck(m_gvConsecLossKey))
         m_consecutiveLosses = (int)GlobalVariableGet(m_gvConsecLossKey);
      else
         m_consecutiveLosses = 0;

      m_killSwitch = GlobalVariableCheck(m_gvKillSwitchKey) &&
                     GlobalVariableGet(m_gvKillSwitchKey) != 0.0;
      if(m_killSwitch)
         Print("RiskManager: Kill Switch estaba ACTIVO — restaurado desde GlobalVariable.");

      UpdateDay();
      UpdateWeek();
      UpdateMonth();
     }

   void InitKelly(bool useKelly, double fraction, int minTrades)
     {
      m_useKelly = useKelly;
      m_kellyFraction = MathMax(0.01, MathMin(fraction, 1.0));
      m_kellyMinTrades = MathMax(10, minTrades);
      if(m_useKelly)
         Print("RiskManager: Kelly Criterion ON — fracción=",
               DoubleToString(m_kellyFraction*100,0), "% minTrades=", m_kellyMinTrades);
     }

   void InitPortfolioCap(bool enabled, double maxPortfolioRiskPct)
     {
      m_usePortfolioCap = enabled;
      m_maxPortfolioRiskPct = MathMax(0.01, maxPortfolioRiskPct);
      if(m_usePortfolioCap)
        {
         ReconcilePortfolioRisk();
         Print("RiskManager: Portfolio Risk Cap ON — máximo ",
               DoubleToString(m_maxPortfolioRiskPct, 2),
               "% de riesgo agregado entre todas las instancias del EA.");
        }
     }

   void ReconcilePortfolioRisk()
     {
      double rebuiltTotal = 0.0;
      int released = 0;
      int prefixLen = StringLen(m_gvPortfolioPrefix);

      for(int i = GlobalVariablesTotal() - 1; i >= 0; i--)
        {
         string name = GlobalVariableName(i);
         if(StringSubstr(name, 0, prefixLen) != m_gvPortfolioPrefix) continue;

         ulong positionId = (ulong)StringToInteger(StringSubstr(name, prefixLen));
         if(PositionIdentifierIsOpen(positionId))
            rebuiltTotal += GlobalVariableGet(name);
         else
           {
            released++;
            Print("RiskManager: reserva huérfana liberada (position_id=", positionId,
                  " riesgo=", DoubleToString(GlobalVariableGet(name), 3), "%).");
            GlobalVariableDel(name);
           }
        }

      GlobalVariableSet(m_gvPortfolioRiskKey, rebuiltTotal);
      if(released > 0)
         Print("RiskManager: reconciliación — ", released,
               " reserva(s) huérfana(s) liberada(s). Riesgo comprometido real: ",
               DoubleToString(rebuiltTotal, 3), "%");
     }

   double GetPortfolioRiskUsed()
     {
      return GlobalVariableCheck(m_gvPortfolioRiskKey)
             ? GlobalVariableGet(m_gvPortfolioRiskKey) : 0.0;
     }

   double GetAvailablePortfolioRisk()
     { return MathMax(0.0, m_maxPortfolioRiskPct - GetPortfolioRiskUsed()); }

   void RegisterOpenRisk(ulong positionId, double riskPct)
     {
      if(!m_usePortfolioCap || positionId == 0 || riskPct <= 0) return;
      string key = m_gvPortfolioPrefix + IntegerToString(positionId);
      // Idempotencia: si ya existe, ajustar total por diferencia en lugar de duplicar.
      double previous = GlobalVariableCheck(key) ? GlobalVariableGet(key) : 0.0;
      double total = MathMax(0.0, GetPortfolioRiskUsed() - previous + riskPct);
      GlobalVariableSet(m_gvPortfolioRiskKey, total);
      GlobalVariableSet(key, riskPct);
     }

   void ReleaseOpenRisk(ulong positionId)
     {
      if(!m_usePortfolioCap || positionId == 0) return;
      string key = m_gvPortfolioPrefix + IntegerToString(positionId);
      if(!GlobalVariableCheck(key)) return;
      double riskPct = GlobalVariableGet(key);
      double total = MathMax(0.0, GetPortfolioRiskUsed() - riskPct);
      GlobalVariableSet(m_gvPortfolioRiskKey, total);
      GlobalVariableDel(key);
     }

   double CalculateLotSize(string symbol, double entryPrice, double slPrice)
     {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double baseRisk = m_useKelly ? CalcKellyRiskPct() : m_riskPercent;
      double effectiveRisk = m_capitalPreservation ? baseRisk * 0.25 : baseRisk;

      if(m_usePortfolioCap)
        {
         double available = GetAvailablePortfolioRisk();
         if(available <= 0)
           {
            Print("RiskManager: Portfolio Risk Cap alcanzado (",
                  DoubleToString(GetPortfolioRiskUsed(), 2), "% / ",
                  DoubleToString(m_maxPortfolioRiskPct, 2), "%) — trade omitido.");
            return 0;
           }
         if(effectiveRisk > available)
           {
            Print("RiskManager: riesgo reducido por Portfolio Cap ",
                  DoubleToString(effectiveRisk, 3), "% → ",
                  DoubleToString(available, 3), "%");
            effectiveRisk = available;
           }
        }

      double riskMoney = equity * effectiveRisk / 100.0;
      if(riskMoney <= 0 || MathAbs(entryPrice - slPrice) <= 0) return 0;

      ENUM_ORDER_TYPE ordType = (slPrice < entryPrice) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      double oneLotAtStop = 0.0;
      if(!OrderCalcProfit(ordType, symbol, 1.0, entryPrice, slPrice, oneLotAtStop) ||
         oneLotAtStop == 0.0)
        {
         Print("RiskManager: OrderCalcProfit falló al calcular riesgo por lote | symbol=",
               symbol, " error=", GetLastError());
         return 0;
        }
      double lossPerLot = MathAbs(oneLotAtStop);
      double lots = riskMoney / lossPerLot * GetPositionSizeMultiplier();

      double minLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double maxLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double lotStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      if(minLot <= 0 || maxLot <= 0 || lotStep <= 0) return 0;

      lots = MathFloor(lots / lotStep) * lotStep;
      if(lots < minLot) return 0;
      lots = MathMin(maxLot, lots);

      double marginReq = 0.0;
      if(OrderCalcMargin(ordType, symbol, lots, entryPrice, marginReq) && marginReq > 0)
        {
         double marginCap = AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.80;
         if(marginReq > marginCap)
           {
            double scaled = MathFloor(lots * marginCap / marginReq / lotStep) * lotStep;
            if(scaled < minLot)
              {
               Print("RiskManager: margen libre insuficiente (req=",
                     DoubleToString(marginReq, 2), " cap=",
                     DoubleToString(marginCap, 2), ") — trade omitido.");
               return 0;
              }
            Print("RiskManager: lote reducido por margen libre ",
                  DoubleToString(lots, 2), " → ", DoubleToString(scaled, 2));
            lots = scaled;
           }
        }

      int decimals;
      if(lotStep >= 1.0) decimals = 0;
      else if(lotStep >= 0.1) decimals = 1;
      else if(lotStep >= 0.01) decimals = 2;
      else decimals = 3;

      return NormalizeDouble(lots, decimals);
     }

   double CalcRiskPctForPosition(string symbol, double entryPrice, double slPrice, double lots)
     {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      if(equity <= 0 || lots <= 0 || MathAbs(entryPrice - slPrice) <= 0) return 0;
      ENUM_ORDER_TYPE ordType = (slPrice < entryPrice) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      double pnlAtStop = 0.0;
      if(!OrderCalcProfit(ordType, symbol, lots, entryPrice, slPrice, pnlAtStop)) return 0;
      double moneyAtRisk = MathAbs(pnlAtStop);
      return moneyAtRisk / equity * 100.0;
     }

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

   bool IsMonthlyCircuitBreakerTripped()
     {
      UpdateMonth();
      if(m_maxMonthlyDD <= 0 || m_monthStartEquity <= 0) return false;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      return ((m_monthStartEquity - equity) / m_monthStartEquity * 100.0) >= m_maxMonthlyDD;
     }

   bool IsCapitalPreservationActive()
     {
      UpdateDay();
      if(m_dayStartEquity <= 0) return false;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double dd = (m_dayStartEquity - equity) / m_dayStartEquity * 100.0;
      m_capitalPreservation = (dd >= m_cpThresholdPct);
      return m_capitalPreservation;
     }

   void SetKillSwitch(bool active)
     {
      m_killSwitch = active;
      GlobalVariableSet(m_gvKillSwitchKey, active ? 1.0 : 0.0);
      if(active)
         Print("RiskManager: KILL SWITCH activado. Sin operaciones hasta desactivar.");
      else
         Print("RiskManager: KILL SWITCH desactivado.");
     }
   bool IsKillSwitchActive() { return m_killSwitch; }

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
     { return SymbolInfoInteger(symbol, SYMBOL_SPREAD) <= (long)m_maxSpreadPoints; }

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

   void PrintStatus()
     {
      Print("RiskManager | ConsecLoss=", m_consecutiveLosses,
            " | KillSwitch=", m_killSwitch ? "ON" : "OFF",
            " | CapPreserv=", m_capitalPreservation ? "ON" : "OFF",
            " | CircuitBreaker=", IsMonthlyCircuitBreakerTripped() ? "TRIPPED" : "OK",
            " | PortfolioRisk=", m_usePortfolioCap
               ? StringFormat("%.2f%%/%.2f%%", GetPortfolioRiskUsed(), m_maxPortfolioRiskPct)
               : "OFF");
     }
  };
//+------------------------------------------------------------------+
