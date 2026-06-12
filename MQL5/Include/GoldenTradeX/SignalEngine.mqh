//+------------------------------------------------------------------+
//|                                                 SignalEngine.mqh |
//|   Golden Trade X — Motor de señales (EMA cross + RSI + ATR)      |
//+------------------------------------------------------------------+
#property strict

enum ENUM_SIGNAL
  {
   SIGNAL_NONE = 0,
   SIGNAL_BUY  = 1,
   SIGNAL_SELL = -1
  };

class CSignalEngine
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_tf;
   int             m_hEmaFast;
   int             m_hEmaSlow;
   int             m_hRsi;
   int             m_hAtr;
   double          m_rsiUpper;
   double          m_rsiLower;

   bool CopyOne(int handle, int shift, double &value)
     {
      double buf[1];
      if(CopyBuffer(handle, 0, shift, 1, buf) != 1) return(false);
      value = buf[0];
      return(true);
     }

public:
   bool Init(string symbol, ENUM_TIMEFRAMES tf, int emaFast, int emaSlow,
             int rsiPeriod, double rsiUpper, double rsiLower, int atrPeriod)
     {
      m_symbol   = symbol;
      m_tf       = tf;
      m_rsiUpper = rsiUpper;
      m_rsiLower = rsiLower;

      m_hEmaFast = iMA(symbol, tf, emaFast, 0, MODE_EMA, PRICE_CLOSE);
      m_hEmaSlow = iMA(symbol, tf, emaSlow, 0, MODE_EMA, PRICE_CLOSE);
      m_hRsi     = iRSI(symbol, tf, rsiPeriod, PRICE_CLOSE);
      m_hAtr     = iATR(symbol, tf, atrPeriod);

      return(m_hEmaFast != INVALID_HANDLE && m_hEmaSlow != INVALID_HANDLE &&
             m_hRsi != INVALID_HANDLE && m_hAtr != INVALID_HANDLE);
     }

   void Release()
     {
      if(m_hEmaFast != INVALID_HANDLE) IndicatorRelease(m_hEmaFast);
      if(m_hEmaSlow != INVALID_HANDLE) IndicatorRelease(m_hEmaSlow);
      if(m_hRsi     != INVALID_HANDLE) IndicatorRelease(m_hRsi);
      if(m_hAtr     != INVALID_HANDLE) IndicatorRelease(m_hAtr);
     }

   //--- Señal por cruce de EMAs confirmado en vela cerrada + filtro RSI
   ENUM_SIGNAL GetSignal()
     {
      double fast1, fast2, slow1, slow2, rsi1;
      if(!CopyOne(m_hEmaFast, 1, fast1)) return(SIGNAL_NONE);
      if(!CopyOne(m_hEmaFast, 2, fast2)) return(SIGNAL_NONE);
      if(!CopyOne(m_hEmaSlow, 1, slow1)) return(SIGNAL_NONE);
      if(!CopyOne(m_hEmaSlow, 2, slow2)) return(SIGNAL_NONE);
      if(!CopyOne(m_hRsi,     1, rsi1))  return(SIGNAL_NONE);

      //--- Cruce alcista: la rápida cruza por encima de la lenta
      if(fast2 <= slow2 && fast1 > slow1 && rsi1 < m_rsiUpper)
         return(SIGNAL_BUY);

      //--- Cruce bajista: la rápida cruza por debajo de la lenta
      if(fast2 >= slow2 && fast1 < slow1 && rsi1 > m_rsiLower)
         return(SIGNAL_SELL);

      return(SIGNAL_NONE);
     }

   //--- ATR de la última vela cerrada
   double GetATR()
     {
      double atr;
      if(!CopyOne(m_hAtr, 1, atr)) return(0);
      return(atr);
     }
  };
//+------------------------------------------------------------------+
