//+------------------------------------------------------------------+
//|                                               OrderManager.mqh   |
//|   Golden Trade X v2.62 — Gestor de ejecución server-confirmed   |
//+------------------------------------------------------------------+
//  Envuelve CTrade con:
//    1. Confirmación server-side por ResultRetcode/ResultDeal.
//    2. Identidad separada: order, deal, POSITION_IDENTIFIER y ticket.
//    3. Retry automático para errores temporales.
//    4. Clasificación explícita de resultados.
//    5. Validación de SL/TP y stops_level del broker.
//    6. Telemetría básica de slippage e intentos.
//
//  IMPORTANTE: el bool retornado por CTrade solo indica que las estructuras
//  básicas pasaron la comprobación local. NUNCA se usa por sí solo como
//  evidencia de ejecución. El éxito depende del retcode del servidor y,
//  para ejecuciones de mercado, de un deal confirmado.
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

#define OM_RETCODE_PLACED          10008
#define OM_RETCODE_DONE            10009
#define OM_RETCODE_DONE_PARTIAL    10010
#define OM_RETCODE_TIMEOUT         10012
#define OM_RETCODE_REQUOTE         10004
#define OM_RETCODE_PRICE_CHANGED   10020
#define OM_RETCODE_PRICE_OFF       10021
#define OM_RETCODE_TOO_MANY_REQ    10024
#define OM_RETCODE_NO_CHANGES      10025
#define OM_RETCODE_SERVER_AT_OFF   10026
#define OM_RETCODE_CLIENT_AT_OFF   10027
#define OM_RETCODE_LOCKED          10028
#define OM_RETCODE_CONNECTION      10031
#define OM_RETCODE_NO_MONEY        10019
#define OM_RETCODE_TRADE_DISABLED  10017
#define OM_RETCODE_FROZEN          10029
#define OM_RETCODE_MARKET_CLOSED   10018
#define OM_RETCODE_INVALID_STOPS   10016

enum ENUM_OM_RESULT_CLASS
  {
   OM_RESULT_SUCCESS = 0,
   OM_RESULT_PARTIAL_SUCCESS,
   OM_RESULT_RETRYABLE,
   OM_RESULT_REJECTED,
   OM_RESULT_FATAL,
   OM_RESULT_UNKNOWN
  };

class COrderManager
  {
private:
   CTrade*    m_trade;
   int        m_maxRetries;
   int        m_retryDelayMs;
   double     m_lastSlippage;
   double     m_totalSlippage;
   int        m_totalAttempts;
   int        m_successCount;
   int        m_failCount;

   ulong      m_lastOrderTicket;
   ulong      m_lastDealTicket;
   ulong      m_lastPositionId;
   ulong      m_lastPositionTicket;
   ENUM_OM_RESULT_CLASS m_lastResultClass;

   bool IsRetryable(uint code)
     {
      return code == OM_RETCODE_REQUOTE       ||
             code == OM_RETCODE_PRICE_CHANGED ||
             code == OM_RETCODE_PRICE_OFF     ||
             code == OM_RETCODE_TOO_MANY_REQ  ||
             code == OM_RETCODE_CONNECTION    ||
             code == OM_RETCODE_TIMEOUT       ||
             code == OM_RETCODE_LOCKED;
     }

   bool IsFatal(uint code)
     {
      return code == OM_RETCODE_NO_MONEY       ||
             code == OM_RETCODE_TRADE_DISABLED ||
             code == OM_RETCODE_SERVER_AT_OFF  ||
             code == OM_RETCODE_CLIENT_AT_OFF;
     }

   bool IsDealExecutionCode(uint code)
     {
      return code == OM_RETCODE_DONE || code == OM_RETCODE_DONE_PARTIAL;
     }

   double StopsDistance(string symbol)
     {
      long lvl = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
      return lvl * SymbolInfoDouble(symbol, SYMBOL_POINT);
     }

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

   void LogAttempt(const string &op, int attempt, bool basicOk, uint code)
     {
      Print("OrderManager [", TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS), "] ",
            op, " attempt=", attempt,
            " basic_ok=", basicOk ? "true" : "false",
            " retcode=", code, " class=", (int)ClassifyRetcode(code),
            " comment=", m_trade.ResultComment());
     }

   void ResetLastOpenIdentity()
     {
      m_lastOrderTicket    = 0;
      m_lastDealTicket     = 0;
      m_lastPositionId     = 0;
      m_lastPositionTicket = 0;
     }

   ulong FindPositionTicketByIdentifier(ulong positionId, string symbol = "")
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

   bool CaptureOpenIdentity(string symbol)
     {
      m_lastDealTicket  = m_trade.ResultDeal();
      m_lastOrderTicket = m_trade.ResultOrder();
      if(m_lastDealTicket == 0) return false;

      if(!HistoryDealSelect(m_lastDealTicket))
        {
         HistorySelect(TimeCurrent() - 86400, TimeCurrent() + 60);
         if(!HistoryDealSelect(m_lastDealTicket)) return false;
        }

      m_lastPositionId = (ulong)HistoryDealGetInteger(m_lastDealTicket, DEAL_POSITION_ID);
      if(m_lastPositionId == 0) return false;

      m_lastPositionTicket = FindPositionTicketByIdentifier(m_lastPositionId, symbol);
      return true;
     }

   bool IsOpenServerConfirmed(uint code, string symbol)
     {
      if(!IsDealExecutionCode(code)) return false;
      if(m_trade.ResultDeal() == 0 || m_trade.ResultVolume() <= 0) return false;
      return CaptureOpenIdentity(symbol);
     }

   bool IsModifyServerConfirmed(uint code)
     {
      return code == OM_RETCODE_DONE || code == OM_RETCODE_NO_CHANGES;
     }

   bool IsCloseServerConfirmed(uint code)
     {
      return IsDealExecutionCode(code) && m_trade.ResultDeal() != 0;
     }

public:
   void Init(CTrade* tradePtr, int maxRetries = 3, int retryDelayMs = 500)
     {
      m_trade          = tradePtr;
      m_maxRetries     = maxRetries;
      m_retryDelayMs   = retryDelayMs;
      m_lastSlippage   = 0;
      m_totalSlippage  = 0;
      m_totalAttempts  = 0;
      m_successCount   = 0;
      m_failCount      = 0;
      m_lastResultClass = OM_RESULT_UNKNOWN;
      ResetLastOpenIdentity();
     }

   ENUM_OM_RESULT_CLASS ClassifyRetcode(uint code)
     {
      if(code == OM_RETCODE_DONE)         return OM_RESULT_SUCCESS;
      if(code == OM_RETCODE_DONE_PARTIAL) return OM_RESULT_PARTIAL_SUCCESS;
      if(IsRetryable(code))                return OM_RESULT_RETRYABLE;
      if(IsFatal(code))                    return OM_RESULT_FATAL;
      if(code == OM_RETCODE_INVALID_STOPS || code == OM_RETCODE_MARKET_CLOSED ||
         code == OM_RETCODE_FROZEN || code == OM_RETCODE_PLACED ||
         code == OM_RETCODE_NO_CHANGES)
         return OM_RESULT_REJECTED;
      return OM_RESULT_UNKNOWN;
     }

   bool IsRetryableCode(uint code) { return IsRetryable(code); }
   bool IsFatalCode(uint code)     { return IsFatal(code); }

   // Pure pre-trade geometry guard used by production OpenPosition() and
   // deterministic tests. Broker stops_level enforcement is a separate step.
   bool ValidateInitialStops(ENUM_ORDER_TYPE type, double price,
                             double sl, double tp)
     {
      if(price <= 0 || sl == 0 || tp == 0) return false;
      if(type == ORDER_TYPE_BUY)
         return sl < price && tp > price;
      if(type == ORDER_TYPE_SELL)
         return sl > price && tp < price;
      return false;
     }

   bool OpenPosition(string symbol, ENUM_ORDER_TYPE type, double lots,
                     double price, double sl, double tp, string comment = "")
     {
      ResetLastOpenIdentity();
      m_lastResultClass = OM_RESULT_UNKNOWN;

      if(!ValidateInitialStops(type, price, sl, tp))
        {
         Print("OrderManager: REJECTED — geometría inicial SL/TP inválida.");
         return false;
        }

      EnforceStopsLevel(symbol, type, sl, tp);
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      for(int attempt = 1; attempt <= m_maxRetries + 1; attempt++)
        {
         if(attempt > 1) Sleep(m_retryDelayMs * (attempt - 1));

         m_totalAttempts++;
         bool basicOk = m_trade.PositionOpen(symbol, type, lots, price,
                                             NormalizeDouble(sl, digits),
                                             NormalizeDouble(tp, digits),
                                             comment);
         uint code = m_trade.ResultRetcode();
         m_lastResultClass = ClassifyRetcode(code);
         LogAttempt("OPEN", attempt, basicOk, code);

         if(IsOpenServerConfirmed(code, symbol))
           {
            double execPrice = m_trade.ResultPrice();
            m_lastSlippage = (execPrice > 0)
                             ? MathAbs(execPrice - price) / SymbolInfoDouble(symbol, SYMBOL_POINT)
                             : 0;
            m_totalSlippage += m_lastSlippage;
            m_successCount++;
            Print("OrderManager: OPEN SERVER-CONFIRMED order=", m_lastOrderTicket,
                  " deal=", m_lastDealTicket,
                  " position_id=", m_lastPositionId,
                  " position_ticket=", m_lastPositionTicket,
                  " exec=", execPrice, " slip=", m_lastSlippage, "pts");
            return true;
           }

         if(IsFatal(code))
           {
            Print("OrderManager: FATAL retcode=", code, " — caller debe activar Kill Switch.");
            m_failCount++;
            return false;
           }

         if(!IsRetryable(code) || attempt == m_maxRetries + 1)
           {
            Print("OrderManager: FAILED server not confirmed retcode=", code,
                  " basic_ok=", basicOk ? "true" : "false");
            m_failCount++;
            return false;
           }

         Print("OrderManager: retrying (", attempt, "/", m_maxRetries, ")...");
        }

      m_failCount++;
      return false;
     }

   bool ModifyPosition(ulong ticket, double newSL, double newTP)
     {
      if(!PositionSelectByTicket(ticket)) return false;
      string symbol = PositionGetString(POSITION_SYMBOL);
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      long posType = PositionGetInteger(POSITION_TYPE);
      EnforceStopsLevel(symbol,
                        (posType == POSITION_TYPE_BUY) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL,
                        newSL, newTP);

      for(int attempt = 1; attempt <= m_maxRetries + 1; attempt++)
        {
         if(attempt > 1) Sleep(m_retryDelayMs);

         m_totalAttempts++;
         bool basicOk = m_trade.PositionModify(ticket,
                                               NormalizeDouble(newSL, digits),
                                               NormalizeDouble(newTP, digits));
         uint code = m_trade.ResultRetcode();
         m_lastResultClass = ClassifyRetcode(code);
         LogAttempt("MODIFY", attempt, basicOk, code);

         if(IsModifyServerConfirmed(code))
           { m_successCount++; return true; }
         if(IsFatal(code) || !IsRetryable(code) || attempt == m_maxRetries + 1)
           { m_failCount++; return false; }
        }
      m_failCount++;
      return false;
     }

   bool ClosePosition(ulong ticket)
     {
      for(int attempt = 1; attempt <= m_maxRetries + 1; attempt++)
        {
         if(attempt > 1) Sleep(m_retryDelayMs);

         m_totalAttempts++;
         bool basicOk = m_trade.PositionClose(ticket);
         uint code = m_trade.ResultRetcode();
         m_lastResultClass = ClassifyRetcode(code);
         LogAttempt("CLOSE", attempt, basicOk, code);

         if(IsCloseServerConfirmed(code))
           { m_successCount++; return true; }
         if(IsFatal(code) || !IsRetryable(code) || attempt == m_maxRetries + 1)
           { m_failCount++; return false; }
        }
      m_failCount++;
      return false;
     }

   bool ClosePartial(ulong ticket, double lots)
     {
      for(int attempt = 1; attempt <= m_maxRetries + 1; attempt++)
        {
         if(attempt > 1) Sleep(m_retryDelayMs);

         m_totalAttempts++;
         bool basicOk = m_trade.PositionClosePartial(ticket, lots);
         uint code = m_trade.ResultRetcode();
         m_lastResultClass = ClassifyRetcode(code);
         LogAttempt("CLOSE_PARTIAL", attempt, basicOk, code);

         if(IsCloseServerConfirmed(code))
           { m_successCount++; return true; }
         if(IsFatal(code) || !IsRetryable(code) || attempt == m_maxRetries + 1)
           { m_failCount++; return false; }
        }
      m_failCount++;
      return false;
     }

   bool LastErrorIsFatal()
     { return IsFatal(m_trade.ResultRetcode()); }

   ulong GetLastOrderTicket()        const { return m_lastOrderTicket; }
   ulong GetLastDealTicket()         const { return m_lastDealTicket; }
   ulong GetLastPositionIdentifier() const { return m_lastPositionId; }
   ulong GetLastPositionTicket()     const { return m_lastPositionTicket; }
   ENUM_OM_RESULT_CLASS GetLastResultClass() const { return m_lastResultClass; }

   ulong ResolveLastPositionTicket(string symbol = "")
     {
      if(m_lastPositionId == 0) return 0;
      m_lastPositionTicket = FindPositionTicketByIdentifier(m_lastPositionId, symbol);
      return m_lastPositionTicket;
     }

   double GetLastSlippage() const { return m_lastSlippage; }
   double GetAvgSlippage() const
     { return m_successCount > 0 ? m_totalSlippage / m_successCount : 0; }
   int GetSuccessCount() const { return m_successCount; }
   int GetFailCount() const    { return m_failCount; }

   void PrintStats()
     {
      Print("OrderManager stats | attempts=", m_totalAttempts,
            " ok=", m_successCount,
            " fail=", m_failCount,
            " avg_slip=", DoubleToString(GetAvgSlippage(), 1), "pts");
     }
  };
//+------------------------------------------------------------------+
