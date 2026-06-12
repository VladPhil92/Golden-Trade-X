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
   int             m_hAdx;      // ADX para filtro de régimen de tendencia
   int             m_hHtfEma;   // EMA en H4 para filtro de tendencia superior
   double          m_rsiUpper;
   double          m_rsiLower;
   double          m_rsiLongMin;   // RSI mínimo para longs (confirma momentum alcista)
   double          m_rsiShortMax;  // RSI máximo para shorts (confirma momentum bajista)
   double          m_atrMinRatio;  // ATR / ATR_SMA(20) debe superar este ratio
   double          m_adxMinLevel;  // ADX mínimo para operar (0 = desactivado)
   double          m_atrMaxRatio;  // ATR / ATR_SMA(20) máximo permitido (0 = desactivado)
   bool            m_useHtfFilter;

   // Caché del ATR: evita CopyBuffer en cada tick
   double          m_cachedAtr;
   datetime        m_cachedAtrBar;

   bool CopyOne(int handle, int shift, double &value)
     {
      double buf[1];
      if(CopyBuffer(handle, 0, shift, 1, buf) != 1) return(false);
      value = buf[0];
      return(true);
     }

   // Media simple de los últimos N valores de ATR (velas cerradas)
   double AtrSma(int period)
     {
      double buf[];
      ArraySetAsSeries(buf, true);
      if(CopyBuffer(m_hAtr, 0, 1, period, buf) != period) return(0);
      double sum = 0;
      for(int i = 0; i < period; i++) sum += buf[i];
      return(sum / period);
     }

public:
   bool Init(string symbol, ENUM_TIMEFRAMES tf,
             int emaFast, int emaSlow,
             int rsiPeriod, double rsiUpper, double rsiLower,
             double rsiLongMin, double rsiShortMax,
             int atrPeriod, double atrMinRatio,
             double adxMinLevel, double atrMaxRatio,
             bool useHtfFilter, int htfEmaPeriod)
     {
      m_symbol       = symbol;
      m_tf           = tf;
      m_rsiUpper     = rsiUpper;
      m_rsiLower     = rsiLower;
      m_rsiLongMin   = rsiLongMin;
      m_rsiShortMax  = rsiShortMax;
      m_atrMinRatio  = atrMinRatio;
      m_adxMinLevel  = adxMinLevel;
      m_atrMaxRatio  = atrMaxRatio;
      m_useHtfFilter = useHtfFilter;
      m_cachedAtr    = 0;
      m_cachedAtrBar = 0;
      m_hHtfEma      = INVALID_HANDLE;
      m_hAdx         = INVALID_HANDLE;

      m_hEmaFast = iMA(symbol, tf, emaFast, 0, MODE_EMA, PRICE_CLOSE);
      m_hEmaSlow = iMA(symbol, tf, emaSlow, 0, MODE_EMA, PRICE_CLOSE);
      m_hRsi     = iRSI(symbol, tf, rsiPeriod, PRICE_CLOSE);
      m_hAtr     = iATR(symbol, tf, atrPeriod);

      if(m_hEmaFast == INVALID_HANDLE || m_hEmaSlow == INVALID_HANDLE ||
         m_hRsi == INVALID_HANDLE || m_hAtr == INVALID_HANDLE)
         return(false);

      // Crear handle de ADX para filtro de régimen
      m_hAdx = iADX(symbol, tf, 14);
      if(m_hAdx == INVALID_HANDLE) return(false);

      if(m_useHtfFilter)
        {
         m_hHtfEma = iMA(symbol, PERIOD_H4, htfEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
         if(m_hHtfEma == INVALID_HANDLE) return(false);
        }

      return(true);
     }

   void Release()
     {
      if(m_hEmaFast != INVALID_HANDLE) IndicatorRelease(m_hEmaFast);
      if(m_hEmaSlow != INVALID_HANDLE) IndicatorRelease(m_hEmaSlow);
      if(m_hRsi     != INVALID_HANDLE) IndicatorRelease(m_hRsi);
      if(m_hAtr     != INVALID_HANDLE) IndicatorRelease(m_hAtr);
      if(m_hAdx     != INVALID_HANDLE) IndicatorRelease(m_hAdx);
      if(m_hHtfEma  != INVALID_HANDLE) IndicatorRelease(m_hHtfEma);
     }

   //--- Señal por cruce de EMAs con filtros en cadena
   ENUM_SIGNAL GetSignal()
     {
      // Leer EMAs en barras 0 (en curso), 1 (cerrada) y 2 (cerrada anterior)
      double fast0, fast1, fast2, slow0, slow1, slow2, rsi1;
      if(!CopyOne(m_hEmaFast, 0, fast0)) return(SIGNAL_NONE);
      if(!CopyOne(m_hEmaFast, 1, fast1)) return(SIGNAL_NONE);
      if(!CopyOne(m_hEmaFast, 2, fast2)) return(SIGNAL_NONE);
      if(!CopyOne(m_hEmaSlow, 0, slow0)) return(SIGNAL_NONE);
      if(!CopyOne(m_hEmaSlow, 1, slow1)) return(SIGNAL_NONE);
      if(!CopyOne(m_hEmaSlow, 2, slow2)) return(SIGNAL_NONE);
      if(!CopyOne(m_hRsi,     1, rsi1))  return(SIGNAL_NONE);

      // Filtro ATR mínimo: bloquear entradas en compresión lateral
      if(m_atrMinRatio > 0)
        {
         double atrNow = GetATR();
         double atrAvg = AtrSma(20);
         if(atrAvg > 0 && atrNow < atrAvg * m_atrMinRatio) return(SIGNAL_NONE);
        }

      // Filtro de régimen: solo operar en mercados tendenciales (ADX > umbral)
      if(m_adxMinLevel > 0)
        {
         double adxMain;
         if(!CopyOne(m_hAdx, 1, adxMain)) return(SIGNAL_NONE);
         if(adxMain < m_adxMinLevel) return(SIGNAL_NONE);
        }

      // Filtro ATR máximo: evitar entradas en picos de volatilidad (eventos de noticias)
      if(m_atrMaxRatio > 0)
        {
         double atrNow = GetATR();
         double atrAvg = AtrSma(20);
         if(atrAvg > 0 && atrNow > atrAvg * m_atrMaxRatio) return(SIGNAL_NONE);
        }

      // Cruce confirmado en barra cerrada [1 vs 2] + continuación en barra en curso [0]
      // RSI como confirmación de momentum: rsiLongMin..rsiUpper / rsiLower..rsiShortMax
      ENUM_SIGNAL candidate = SIGNAL_NONE;

      if(fast2 <= slow2 && fast1 > slow1 && fast0 > slow0 &&
         rsi1 >= m_rsiLongMin && rsi1 < m_rsiUpper)
         candidate = SIGNAL_BUY;
      else if(fast2 >= slow2 && fast1 < slow1 && fast0 < slow0 &&
              rsi1 <= m_rsiShortMax && rsi1 > m_rsiLower)
         candidate = SIGNAL_SELL;

      if(candidate == SIGNAL_NONE) return(SIGNAL_NONE);

      // Filtro HTF: operar solo a favor de la tendencia H4
      if(m_useHtfFilter && m_hHtfEma != INVALID_HANDLE)
        {
         double htfEma;
         if(!CopyOne(m_hHtfEma, 1, htfEma)) return(SIGNAL_NONE);
         double htfClose = iClose(m_symbol, PERIOD_H4, 1);
         if(htfClose <= 0) return(SIGNAL_NONE);
         if(candidate == SIGNAL_BUY  && htfClose < htfEma) return(SIGNAL_NONE);
         if(candidate == SIGNAL_SELL && htfClose > htfEma) return(SIGNAL_NONE);
        }

      return(candidate);
     }

   //--- ATR de la última vela cerrada, cacheado por barra para eficiencia en ticks
   double GetATR()
     {
      datetime barTime = iTime(m_symbol, m_tf, 1);
      if(barTime != 0 && barTime == m_cachedAtrBar && m_cachedAtr > 0)
         return(m_cachedAtr);
      double atr;
      if(!CopyOne(m_hAtr, 1, atr)) return(0);
      m_cachedAtr    = atr;
      m_cachedAtrBar = barTime;
      return(atr);
     }
  };
//+------------------------------------------------------------------+
