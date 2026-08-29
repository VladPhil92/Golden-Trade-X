//+------------------------------------------------------------------+
//|                                              HealthMonitor.mqh   |
//|   Golden Trade X v2.30 — Monitor de salud periódico (OnTimer)    |
//+------------------------------------------------------------------+
//  Llamado desde OnTimer() cada ~60 segundos. Realiza:
//    1. Detección de posiciones huérfanas (SL=0) → SL de emergencia.
//    2. Verificación de conexión al broker.
//    3. Verificación de nivel de margen: alerta si margin_level < umbral.
//    4. Escritura de archivo de estado CSV para el monitor Python.
//
//  El archivo de estado se escribe en Common\Files (FILE_COMMON), la misma
//  carpeta que usa TradeLogger — así scripts/live_monitor.py encuentra
//  ambos archivos en un único directorio:
//    GTX_{magic}_status.csv — leído por scripts/live_monitor.py.
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

class CHealthMonitor
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_tf;
   ulong           m_magic;
   string          m_statusFile;
   double          m_minMarginLevel;
   double          m_emergencyAtrMult;
   datetime        m_lastCheck;
   int             m_checkIntervalSec;
   int             m_orphanFixCount;
   int             m_hAtr;

   void WriteStatusFile(bool connected, double equityPct, int openPos, string alert)
     {
      int fh = FileOpen(m_statusFile, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
      if(fh == INVALID_HANDLE) return;

      FileWrite(fh, "timestamp",    "connected", "equity_pct_today",
                    "open_positions", "margin_level_pct", "alert");
      FileWrite(fh,
                TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS),
                connected ? "1" : "0",
                DoubleToString(equityPct, 2),
                IntegerToString(openPos),
                DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_LEVEL), 1),
                alert);
      FileClose(fh);
     }

   double GetCurrentATR()
     {
      double atr = 0.0;
      double buf[1];
      if(m_hAtr != INVALID_HANDLE && CopyBuffer(m_hAtr, 0, 1, 1, buf) == 1)
         atr = buf[0];
      if(atr <= 0)
        {
         atr = SymbolInfoDouble(m_symbol, SYMBOL_POINT) * 200;
         Print("HealthMonitor: ATR no disponible — usando fallback ", atr);
        }
      return atr;
     }

   void FixOrphanSL(CTrade &tradeObj)
     {
      double atr    = GetCurrentATR();
      int    digits = (int)SymbolInfoInteger(m_symbol, SYMBOL_DIGITS);

      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0) continue;
         if(PositionGetString(POSITION_SYMBOL) != m_symbol) continue;
         if(PositionGetInteger(POSITION_MAGIC)  != (long)m_magic) continue;

         double sl = PositionGetDouble(POSITION_SL);
         if(sl != 0) continue;

         double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
         double tp        = PositionGetDouble(POSITION_TP);
         long   posType   = PositionGetInteger(POSITION_TYPE);
         double emergSL   = (posType == POSITION_TYPE_BUY)
                            ? openPrice - atr * m_emergencyAtrMult
                            : openPrice + atr * m_emergencyAtrMult;

         if(tradeObj.PositionModify(ticket, NormalizeDouble(emergSL, digits), tp))
            Print("HealthMonitor: ORPHAN SL fixed ticket=", ticket,
                  " emergencySL=", emergSL);
         else
            Print("HealthMonitor: FAILED to fix orphan SL ticket=", ticket);

         m_orphanFixCount++;
        }
     }

public:
   CHealthMonitor()
     {
      m_symbol = "";
      m_tf = PERIOD_CURRENT;
      m_magic = 0;
      m_statusFile = "";
      m_minMarginLevel = 200.0;
      m_emergencyAtrMult = 3.0;
      m_lastCheck = 0;
      m_checkIntervalSec = 60;
      m_orphanFixCount = 0;
      m_hAtr = INVALID_HANDLE;
     }

   bool Init(string symbol, ENUM_TIMEFRAMES tf, ulong magic,
             double minMarginLevel = 200.0,
             double emergencyAtrMult = 3.0,
             int checkIntervalSec = 60,
             int atrPeriod = 14)
     {
      m_symbol           = symbol;
      m_tf               = tf;
      m_magic            = magic;
      m_minMarginLevel   = minMarginLevel;
      m_emergencyAtrMult = emergencyAtrMult;
      m_checkIntervalSec = MathMax(1, checkIntervalSec);
      m_lastCheck        = 0;
      m_orphanFixCount   = 0;
      m_statusFile       = StringFormat("GTX_%d_status.csv", (int)magic);
      m_hAtr             = iATR(symbol, tf, atrPeriod);
      return (m_hAtr != INVALID_HANDLE);
     }

   void Release()
     {
      if(m_hAtr != INVALID_HANDLE) { IndicatorRelease(m_hAtr); m_hAtr = INVALID_HANDLE; }
     }

   // Pure deterministic seam used by Check() and lifecycle tests. It makes
   // disconnection/margin policy testable without requiring a broker outage.
   string BuildAlert(bool connected, double marginLevel) const
     {
      string alert = "";
      if(marginLevel > 0 && marginLevel < m_minMarginLevel)
         alert = StringFormat("MARGIN_LOW:%.0f%%", marginLevel);
      if(!connected)
         alert = (alert == "") ? "DISCONNECTED" : alert + "|DISCONNECTED";
      return alert;
     }

   bool IsCheckDueAt(datetime now) const
     {
      if(now < m_lastCheck) return true;
      return (now - m_lastCheck) >= m_checkIntervalSec;
     }

   bool Check(CTrade &tradeObj)
     {
      datetime now = TimeCurrent();
      if(!IsCheckDueAt(now)) return false;
      m_lastCheck = now;

      bool connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
      double marginLevel = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
      string alert = BuildAlert(connected, marginLevel);

      if(marginLevel > 0 && marginLevel < m_minMarginLevel)
        {
         Print("HealthMonitor: WARNING — Margin level=", marginLevel,
               "% < ", m_minMarginLevel, "% threshold");
        }
      if(!connected)
         Print("HealthMonitor: WARNING — Terminal disconnected from broker.");

      FixOrphanSL(tradeObj);

      double equity    = AccountInfoDouble(ACCOUNT_EQUITY);
      double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
      double equityPct = (balance > 0) ? equity / balance * 100.0 : 100.0;

      int openPos = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong t = PositionGetTicket(i);
         if(t == 0) continue;
         if(PositionGetString(POSITION_SYMBOL) == m_symbol &&
            PositionGetInteger(POSITION_MAGIC) == (long)m_magic)
            openPos++;
        }

      WriteStatusFile(connected, equityPct, openPos, alert);
      return true;
     }

   int GetOrphanFixCount() const { return m_orphanFixCount; }
  };
//+------------------------------------------------------------------+
