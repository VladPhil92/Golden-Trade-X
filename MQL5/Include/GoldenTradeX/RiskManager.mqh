//+------------------------------------------------------------------+
//|                                                  RiskManager.mqh |
//|   Golden Trade X v2.60 — Gestión de riesgo y capital             |
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

   // v2.60: Portfolio Risk Cap — riesgo agregado entre TODAS las instancias
   // del EA en la misma cuenta (p.ej. XAUUSD + XAGUSD). Sin esto, cada
   // instancia gestiona su drawdown de forma aislada aunque XAUUSD y XAGUSD
   // están altamente correlacionados (USD, tasas reales, riesgo geopolítico),
   // por lo que dos posiciones de 1% pueden significar ~2% de riesgo real
   // ante el mismo factor macro.
   bool    m_usePortfolioCap;
   double  m_maxPortfolioRiskPct;   // % máximo de equity en riesgo simultáneo, TODAS las instancias
   string  m_gvPortfolioRiskKey;    // GlobalVariable compartida por cuenta (no por magic number)
   string  m_gvPortfolioPrefix;     // prefijo para las claves per-ticket

   // Calcula W (win rate) y R (win/loss ratio) desde historial real del EA.
   // v2.50: agrega los deals por POSITION_ID — un trade con cierre parcial
   // genera varios deals DEAL_ENTRY_OUT pero cuenta como UN solo trade
   // (sumando el neto de todos sus cierres). Sin esto, los parciales
   // (ganadores por construcción) inflaban W sistemáticamente.
   bool CalcWinRateAndR(double &winRate, double &avgR)
     {
      datetime from = TimeCurrent() - 90 * 24 * 3600;   // ventana 90 días
      if(!HistorySelect(from, TimeCurrent())) return false;

      ulong  posIds[];
      double posNet[];
      int    nPos = 0;

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

         ulong pid = (ulong)HistoryDealGetInteger(ticket, DEAL_POSITION_ID);
         int   idx = -1;
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
      int    wins = 0, losses = 0;
      for(int j = 0; j < nPos; j++)
        {
         if(posNet[j] > 0) { sumWins   += posNet[j];          wins++;   }
         else              { sumLosses += MathAbs(posNet[j]); losses++; }
        }

      if(wins + losses < m_kellyMinTrades) return false;
      // Sin pérdidas (o sin ganancias) no hay estimación válida de R:
      // caer al riesgo fijo en lugar de inventar un ratio.
      if(wins == 0 || losses == 0) return false;

      winRate     = (double)wins / (wins + losses);
      double avgW = sumWins   / wins;
      double avgL = sumLosses / losses;
      if(avgL <= 0) return false;
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
      // v2.50: semana absoluta desde epoch (época Unix), alineada a lunes.
      // La fórmula anterior (year*100 + day_of_year/7) partía la misma semana
      // operativa en dos al cruzar el año → reset espurio del DD semanal.
      // Epoch (1-ene-1970) fue jueves: +4 días alinea el corte al lunes 00:00.
      int weekIndex = (int)((TimeCurrent() / 86400 + 4) / 7);
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
      m_usePortfolioCap      = false;
      m_maxPortfolioRiskPct  = 1.5;

      long login = AccountInfoInteger(ACCOUNT_LOGIN);
      // v2.60: clave por CUENTA (no por magic number) — compartida entre
      // todas las instancias del EA (XAUUSD, XAGUSD, ...) en este login.
      m_gvPortfolioRiskKey = StringFormat("GTX_%d_PortfolioRiskPct", (int)login);
      m_gvPortfolioPrefix  = StringFormat("GTX_%d_PR_", (int)login);
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

   // v2.60: activar el Portfolio Risk Cap (riesgo agregado entre instancias)
   void InitPortfolioCap(bool enabled, double maxPortfolioRiskPct)
     {
      m_usePortfolioCap     = enabled;
      m_maxPortfolioRiskPct = MathMax(0.01, maxPortfolioRiskPct);
      if(m_usePortfolioCap)
        {
         ReconcilePortfolioRisk();   // v2.61: limpiar reservas huérfanas
         Print("RiskManager: Portfolio Risk Cap ON — máximo ",
               DoubleToString(m_maxPortfolioRiskPct, 2),
               "% de riesgo agregado entre todas las instancias del EA.");
        }
     }

   // v2.61: reconciliación del presupuesto de riesgo compartido.
   // Si una posición se cierra con el terminal APAGADO (SL/TP se ejecutan
   // en el servidor del broker), OnTradeTransaction nunca se dispara al
   // reiniciar → ReleaseOpenRisk() no se llama y la reserva queda escrita
   // en la GlobalVariable para siempre. Sin esta pasada, el presupuesto se
   // llena de posiciones fantasma y el cap termina bloqueando trades
   // legítimos. Aquí se enumeran todas las reservas GTX_<login>_PR_*,
   // se eliminan las de tickets que ya no existen, y se RECONSTRUYE el
   // total desde las reservas supervivientes (corrige cualquier deriva).
   void ReconcilePortfolioRisk()
     {
      double rebuiltTotal = 0.0;
      int    released     = 0;
      int    prefixLen    = StringLen(m_gvPortfolioPrefix);

      // Recorrer hacia atrás: GlobalVariableDel reindexa la lista
      for(int i = GlobalVariablesTotal() - 1; i >= 0; i--)
        {
         string name = GlobalVariableName(i);
         if(StringSubstr(name, 0, prefixLen) != m_gvPortfolioPrefix) continue;

         ulong ticket = (ulong)StringToInteger(StringSubstr(name, prefixLen));
         if(ticket > 0 && PositionSelectByTicket(ticket))
           {
            rebuiltTotal += GlobalVariableGet(name);   // posición viva: conservar
           }
         else
           {
            released++;
            Print("RiskManager: reserva huérfana liberada (ticket=", ticket,
                  " riesgo=", DoubleToString(GlobalVariableGet(name), 3),
                  "% — posición ya no existe).");
            GlobalVariableDel(name);
           }
        }

      GlobalVariableSet(m_gvPortfolioRiskKey, rebuiltTotal);
      if(released > 0)
         Print("RiskManager: reconciliación — ", released,
               " reserva(s) huérfana(s) liberada(s). Riesgo comprometido real: ",
               DoubleToString(rebuiltTotal, 3), "%");
     }

   // Riesgo % actualmente comprometido por TODAS las instancias del EA
   // (suma persistida en una GlobalVariable compartida por cuenta)
   double GetPortfolioRiskUsed()
     {
      return GlobalVariableCheck(m_gvPortfolioRiskKey)
             ? GlobalVariableGet(m_gvPortfolioRiskKey) : 0.0;
     }

   double GetAvailablePortfolioRisk()
     {
      return MathMax(0.0, m_maxPortfolioRiskPct - GetPortfolioRiskUsed());
     }

   // Registra el riesgo % de una posición recién abierta contra el
   // presupuesto compartido. Llamar UNA vez, justo tras confirmar la
   // apertura (con el SL/lote REALES, no el propuesto).
   void RegisterOpenRisk(ulong ticket, double riskPct)
     {
      if(!m_usePortfolioCap || riskPct <= 0) return;
      double total = GetPortfolioRiskUsed() + riskPct;
      GlobalVariableSet(m_gvPortfolioRiskKey, total);
      GlobalVariableSet(m_gvPortfolioPrefix + IntegerToString(ticket), riskPct);
     }

   // Libera el riesgo reservado al cerrar TOTALMENTE una posición.
   void ReleaseOpenRisk(ulong ticket)
     {
      if(!m_usePortfolioCap) return;
      string key = m_gvPortfolioPrefix + IntegerToString(ticket);
      if(!GlobalVariableCheck(key)) return;
      double riskPct = GlobalVariableGet(key);
      double total   = MathMax(0.0, GetPortfolioRiskUsed() - riskPct);
      GlobalVariableSet(m_gvPortfolioRiskKey, total);
      GlobalVariableDel(key);
     }

   //--- Lote con multiplicador de riesgo adaptativo (v2.40: soporte Kelly)
   double CalculateLotSize(string symbol, double entryPrice, double slPrice)
     {
      double equity       = AccountInfoDouble(ACCOUNT_EQUITY);
      double baseRisk     = m_useKelly ? CalcKellyRiskPct() : m_riskPercent;
      double effectiveRisk = m_capitalPreservation ? baseRisk * 0.25 : baseRisk;

      // v2.60: capar contra el presupuesto de riesgo agregado del portafolio
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

      // v2.51: verificar margen libre ANTES de enviar. Sin esto, una cuenta
      // justa de margen recibe 10019 NO_MONEY — clasificado como fatal —
      // y el Kill Switch detiene el EA. Se usa máx. 80% del margen libre;
      // si no alcanza, se reduce el lote (o se omite el trade con log).
      ENUM_ORDER_TYPE ordType = (slPrice < entryPrice) ? ORDER_TYPE_BUY
                                                       : ORDER_TYPE_SELL;
      double marginReq = 0.0;
      if(OrderCalcMargin(ordType, symbol, lots, entryPrice, marginReq) &&
         marginReq > 0)
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
      if(lotStep >= 1.0)       decimals = 0;
      else if(lotStep >= 0.1)  decimals = 1;
      else if(lotStep >= 0.01) decimals = 2;
      else                     decimals = 3;

      return NormalizeDouble(lots, decimals);
     }

   // v2.60: riesgo % real de una posición ya abierta, a partir de su
   // SL/lote REALES (puede diferir del propuesto por redondeo de lotes,
   // ajuste de stops_level, etc.) — usado para alimentar RegisterOpenRisk.
   double CalcRiskPctForPosition(string symbol, double entryPrice, double slPrice, double lots)
     {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      if(equity <= 0 || lots <= 0) return 0;
      double slDistance = MathAbs(entryPrice - slPrice);
      if(slDistance <= 0) return 0;
      double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tickValue <= 0 || tickSize <= 0) return 0;
      double moneyAtRisk = slDistance / tickSize * tickValue * lots;
      return moneyAtRisk / equity * 100.0;
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
            " | CircuitBreaker=", IsMonthlyCircuitBreakerTripped() ? "TRIPPED" : "OK",
            " | PortfolioRisk=", m_usePortfolioCap
               ? StringFormat("%.2f%%/%.2f%%", GetPortfolioRiskUsed(), m_maxPortfolioRiskPct)
               : "OFF");
     }
  };
//+------------------------------------------------------------------+
