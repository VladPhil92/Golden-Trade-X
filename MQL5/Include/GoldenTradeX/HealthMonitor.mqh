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
//  El archivo de estado se escribe en la carpeta Files del terminal:
//    GTX_{magic}_status.csv — leído por scripts/live_monitor.py.
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

class CHealthMonitor
  {
private:
   string   m_symbol;
   ulong    m_magic;
   string   m_statusFile;
   double   m_minMarginLevel;    // % mínimo de nivel de margen (default 200%)
   double   m_emergencyAtrMult;  // multiplicador ATR para SL de emergencia
   datetime m_lastCheck;
   int      m_checkIntervalSec;
   int      m_orphanFixCount;

   void WriteStatusFile(bool connected, double equityPct, int openPos, string alert)
     {
      int fh = FileOpen(m_statusFile, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
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

   void FixOrphanSL(CTrade &trade)
     {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0) continue;
         if(PositionGetString(POSITION_SYMBOL) != m_symbol) continue;
         if(PositionGetInteger(POSITION_MAGIC)  != (long)m_magic) continue;

         double sl = PositionGetDouble(POSITION_SL);
         if(sl != 0) continue;

         double atr  = iATR(m_symbol, PERIOD_M15, 14, 1);
         if(atr <= 0) atr = SymbolInfoDouble(m_symbol, SYMBOL_POINT) * 200;

         double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
         double tp        = PositionGetDouble(POSITION_TP);
         long   posType   = PositionGetInteger(POSITION_TYPE);
         double emergSL   = (posType == POSITION_TYPE_BUY)
                            ? openPrice - atr * m_emergencyAtrMult
                            : openPrice + atr * m_emergencyAtrMult;

         if(trade.PositionModify(ticket, NormalizeDouble(emergSL, _Digits), tp))
            Print("HealthMonitor: ORPHAN SL fixed ticket=", ticket,
                  " emergencySL=", emergSL);
         else
            Print("HealthMonitor: FAILED to fix orphan SL ticket=", ticket);

         m_orphanFixCount++;
        }
     }

public:
   void Init(string symbol, ulong magic,
             double minMarginLevel = 200.0,
             double emergencyAtrMult = 3.0,
             int checkIntervalSec = 60)
     {
      m_symbol          = symbol;
      m_magic           = magic;
      m_minMarginLevel  = minMarginLevel;
      m_emergencyAtrMult = emergencyAtrMult;
      m_checkIntervalSec = checkIntervalSec;
      m_lastCheck        = 0;
      m_orphanFixCount   = 0;
      m_statusFile       = StringFormat("GTX_%d_status.csv", (int)magic);
     }

   // Llamar desde OnTimer(). Retorna true si se ejecutó el check.
   bool Check(CTrade &trade)
     {
      datetime now = TimeCurrent();
      if(now - m_lastCheck < m_checkIntervalSec) return false;
      m_lastCheck = now;

      bool connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
      string alert   = "";

      // ── 1. Margen ────────────────────────────────────────────────────
      double marginLevel = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
      if(marginLevel > 0 && marginLevel < m_minMarginLevel)
        {
         alert = StringFormat("MARGIN_LOW:%.0f%%", marginLevel);
         Print("HealthMonitor: WARNING — Margin level=", marginLevel,
               "% < ", m_minMarginLevel, "% threshold");
        }

      // ── 2. Conexión ─────────────────────────────────────────────────
      if(!connected)
        {
         alert = (alert == "") ? "DISCONNECTED" : alert + "|DISCONNECTED";
         Print("HealthMonitor: WARNING — Terminal disconnected from broker.");
        }

      // ── 3. Orphan SL ─────────────────────────────────────────────────
      FixOrphanSL(trade);

      // ── 4. Equity hoy ────────────────────────────────────────────────
      double equity     = AccountInfoDouble(ACCOUNT_EQUITY);
      double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
      double equityPct  = (balance > 0) ? equity / balance * 100.0 : 100.0;

      // ── 5. Escribir estado ───────────────────────────────────────────
      int openPos = 0;
      for(int i = PositionsTotal()-1; i >= 0; i--)
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
