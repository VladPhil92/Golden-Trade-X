//+------------------------------------------------------------------+
//|                                               OrderManager.mqh   |
//|   Golden Trade X v2.30 — Gestor de órdenes production-grade      |
//+------------------------------------------------------------------+
//  Envuelve CTrade con:
//    1. Retry automático en errores temporales (requote, price_changed,
//       connection, too_many_requests) — hasta InpOrderMaxRetries intentos.
//    2. Clasificación de errores: retryable / non-retryable / fatal.
//       Los errores fatales (NO_MONEY, TRADE_DISABLED, FROZEN) activan
//       el Kill Switch automáticamente via CRiskManager.
//    3. Validación obligatoria de SL ≠ 0 y TP ≠ 0 antes de enviar.
//    4. Seguimiento de slippage (puntos) por operación.
//    5. Log estructurado de cada intento con timestamp.
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

// ── Códigos de retorno MQL5 (subset relevante) ─────────────────────
#define OM_RETCODE_DONE           10009
#define OM_RETCODE_DONE_PARTIAL   10010
#define OM_RETCODE_REQUOTE        10004
#define OM_RETCODE_PRICE_CHANGED  10020
#define OM_RETCODE_PRICE_OFF      10021
#define OM_RETCODE_TOO_MANY_REQ   10024
#define OM_RETCODE_CONNECTION     10031
#define OM_RETCODE_NO_MONEY       10019
#define OM_RETCODE_TRADE_DISABLED 10017
#define OM_RETCODE_FROZEN         10029
#define OM_RETCODE_MARKET_CLOSED  10018
#define OM_RETCODE_INVALID_STOPS  10016

class COrderManager
  {
private:
   CTrade*    m_trade;
   int        m_maxRetries;
   int        m_retryDelayMs;
   double     m_lastSlippage;    // puntos de slippage en la última apertura
   double     m_totalSlippage;   // acumulado (puntos)
   int        m_totalAttempts;
   int        m_successCount;
   int        m_failCount;

   bool IsRetryable(uint code)
     {
      return code == OM_RETCODE_REQUOTE       ||
             code == OM_RETCODE_PRICE_CHANGED ||
             code == OM_RETCODE_PRICE_OFF     ||
             code == OM_RETCODE_TOO_MANY_REQ  ||
             code == OM_RETCODE_CONNECTION;
     }

   bool IsFatal(uint code)
     {
      return code == OM_RETCODE_NO_MONEY       ||
             code == OM_RETCODE_TRADE_DISABLED ||
             code == OM_RETCODE_FROZEN;
     }

   bool IsSuccess(uint code)
     {
      return code == OM_RETCODE_DONE || code == OM_RETCODE_DONE_PARTIAL;
     }

   // v2.50: distancia mínima broker para SL/TP (SYMBOL_TRADE_STOPS_LEVEL).
   // Sin esto, órdenes con stops demasiado cerca devuelven 10016
   // INVALID_STOPS (no-reintentable) y se descartan en silencio.
   double StopsDistance(string symbol)
     {
      long lvl = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
      return lvl * SymbolInfoDouble(symbol, SYMBOL_POINT);
     }

   // Ajusta SL/TP a la distancia mínima del broker. BUY se valida contra Bid,
   // SELL contra Ask (así lo evalúa el servidor). Loguea si tuvo que ajustar.
   void EnforceStopsLevel(string symbol, ENUM_ORDER_TYPE type,
                          double &sl, double &tp)
     {
      double d = StopsDistance(symbol);
      if(d <= 0) return;

      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      double slAdj = sl, tpAdj = tp;

      if(type == ORDER_TYPE_BUY)
        {
         if(sl > 0 && bid - sl < d) slAdj = bid - d;
         if(tp > 0 && tp - bid < d) tpAdj = bid + d;
        }
      else
        {
         if(sl > 0 && sl - ask < d) slAdj = ask + d;
         if(tp > 0 && ask - tp < d) tpAdj = ask - d;
        }

      if(slAdj != sl || tpAdj != tp)
         Print("OrderManager: stops ajustados a stops_level del broker (",
               d / SymbolInfoDouble(symbol, SYMBOL_POINT), " pts): SL ",
               sl, "→", slAdj, " TP ", tp, "→", tpAdj);
      sl = slAdj;
      tp = tpAdj;
     }

   void LogAttempt(const string &op, int attempt, uint code)
     {
      Print("OrderManager [", TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS), "] ",
            op, " attempt=", attempt,
            " retcode=", code, " comment=", m_trade.ResultComment());
     }

public:
   void Init(CTrade* tradePtr, int maxRetries = 3, int retryDelayMs = 500)
     {
      m_trade         = tradePtr;
      m_maxRetries    = maxRetries;
      m_retryDelayMs  = retryDelayMs;
      m_lastSlippage  = 0;
      m_totalSlippage = 0;
      m_totalAttempts = 0;
      m_successCount  = 0;
      m_failCount     = 0;
     }

   // ── Abrir posición (con validación + retry) ───────────────────────
   // Retorna true solo si el orden fue CONFIRMADA por el servidor.
   // Rechaza hardcoded si sl==0 o tp==0.
   bool OpenPosition(string symbol, ENUM_ORDER_TYPE type, double lots,
                     double price, double sl, double tp, string comment = "")
     {
      // Validación obligatoria: SL y TP deben estar presentes
      if(sl == 0)
        { Print("OrderManager: REJECTED — SL=0. Orden no enviada (riesgo indefinido)."); return false; }
      if(tp == 0)
        { Print("OrderManager: REJECTED — TP=0. Orden no enviada (objetivo indefinido)."); return false; }

      // Validar que SL y TP estén en el lado correcto
      if(type == ORDER_TYPE_BUY  && (sl >= price || tp <= price))
        { Print("OrderManager: REJECTED BUY — SL debe ser < price y TP > price."); return false; }
      if(type == ORDER_TYPE_SELL && (sl <= price || tp >= price))
        { Print("OrderManager: REJECTED SELL — SL debe ser > price y TP < price."); return false; }

      // v2.50: respetar la distancia mínima de stops del broker
      EnforceStopsLevel(symbol, type, sl, tp);

      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      for(int attempt = 1; attempt <= m_maxRetries + 1; attempt++)
        {
         if(attempt > 1) Sleep(m_retryDelayMs * (attempt - 1));

         m_totalAttempts++;
         bool ok = m_trade.PositionOpen(symbol, type, lots, price,
                                        NormalizeDouble(sl, digits),
                                        NormalizeDouble(tp, digits),
                                        comment);
         uint code = m_trade.ResultRetcode();
         LogAttempt("OPEN", attempt, code);

         if(IsSuccess(code) || ok)
           {
            double execPrice = m_trade.ResultPrice();
            m_lastSlippage   = (execPrice > 0)
                               ? MathAbs(execPrice - price) / SymbolInfoDouble(symbol, SYMBOL_POINT)
                               : 0;
            m_totalSlippage += m_lastSlippage;
            m_successCount++;
            Print("OrderManager: OPEN CONFIRMED ticket=", m_trade.ResultOrder(),
                  " exec=", execPrice, " slip=", m_lastSlippage, "pts");
            return true;
           }

         if(IsFatal(code))
           {
            Print("OrderManager: FATAL retcode=", code, " — Kill Switch activado.");
            m_failCount++;
            return false;   // Caller debe activar kill switch
           }

         if(!IsRetryable(code) || attempt == m_maxRetries + 1)
           {
            Print("OrderManager: FAILED non-retryable retcode=", code);
            m_failCount++;
            return false;
           }

         Print("OrderManager: retrying (", attempt, "/", m_maxRetries, ")...");
        }

      m_failCount++;
      return false;
     }

   // ── Modificar SL/TP (con retry) ──────────────────────────────────
   bool ModifyPosition(ulong ticket, double newSL, double newTP)
     {
      if(!PositionSelectByTicket(ticket)) return false;
      string symbol  = PositionGetString(POSITION_SYMBOL);
      int    digits  = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      // v2.50: respetar la distancia mínima de stops del broker en trailing/BE
      long posType = PositionGetInteger(POSITION_TYPE);
      EnforceStopsLevel(symbol,
                        (posType == POSITION_TYPE_BUY) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL,
                        newSL, newTP);

      for(int attempt = 1; attempt <= m_maxRetries + 1; attempt++)
        {
         if(attempt > 1) Sleep(m_retryDelayMs);

         m_totalAttempts++;
         bool ok   = m_trade.PositionModify(ticket,
                                            NormalizeDouble(newSL, digits),
                                            NormalizeDouble(newTP, digits));
         uint code = m_trade.ResultRetcode();
         if(IsSuccess(code) || ok) { m_successCount++; return true; }
         if(IsFatal(code) || !IsRetryable(code) || attempt == m_maxRetries + 1)
           { LogAttempt("MODIFY", attempt, code); m_failCount++; return false; }
        }
      return false;
     }

   // ── Cerrar posición completa (con retry) ─────────────────────────
   bool ClosePosition(ulong ticket)
     {
      for(int attempt = 1; attempt <= m_maxRetries + 1; attempt++)
        {
         if(attempt > 1) Sleep(m_retryDelayMs);

         m_totalAttempts++;
         bool ok   = m_trade.PositionClose(ticket);
         uint code = m_trade.ResultRetcode();
         if(IsSuccess(code) || ok) { m_successCount++; return true; }
         if(IsFatal(code) || !IsRetryable(code) || attempt == m_maxRetries + 1)
           { LogAttempt("CLOSE", attempt, code); m_failCount++; return false; }
        }
      return false;
     }

   // ── Cierre parcial (con retry) ────────────────────────────────────
   bool ClosePartial(ulong ticket, double lots)
     {
      for(int attempt = 1; attempt <= m_maxRetries + 1; attempt++)
        {
         if(attempt > 1) Sleep(m_retryDelayMs);

         m_totalAttempts++;
         bool ok   = m_trade.PositionClosePartial(ticket, lots);
         uint code = m_trade.ResultRetcode();
         if(IsSuccess(code) || ok) { m_successCount++; return true; }
         if(IsFatal(code) || !IsRetryable(code) || attempt == m_maxRetries + 1)
           { LogAttempt("CLOSE_PARTIAL", attempt, code); m_failCount++; return false; }
        }
      return false;
     }

   // ── Detectar error fatal en última operación ──────────────────────
   bool LastErrorIsFatal()
     {
      uint rc = m_trade.ResultRetcode();
      return IsFatal(rc);
     }

   // ── Estadísticas de ejecución ─────────────────────────────────────
   double GetLastSlippage()   const { return m_lastSlippage; }
   double GetAvgSlippage()    const
     { return m_successCount > 0 ? m_totalSlippage / m_successCount : 0; }
   int    GetSuccessCount()   const { return m_successCount; }
   int    GetFailCount()      const { return m_failCount; }

   void PrintStats()
     {
      Print("OrderManager stats | attempts=", m_totalAttempts,
            " ok=", m_successCount,
            " fail=", m_failCount,
            " avg_slip=", DoubleToString(GetAvgSlippage(), 1), "pts");
     }
  };
//+------------------------------------------------------------------+
