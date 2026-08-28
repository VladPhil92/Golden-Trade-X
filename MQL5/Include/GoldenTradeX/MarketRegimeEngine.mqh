//+------------------------------------------------------------------+
//|                                          MarketRegimeEngine.mqh  |
//|   Golden Trade X — Detección automática de régimen              |
//+------------------------------------------------------------------+
//  Regímenes:
//    REGIME_TRENDING_BULL  — ADX > umbral, EMA slope y precio alcistas
//    REGIME_TRENDING_BEAR  — ADX > umbral, EMA slope y precio bajistas
//    REGIME_RANGING        — ADX < umbral bajo, mercado lateral
//    REGIME_VOLATILE       — ATR_ratio > 2× promedio (spike/noticia)
//    REGIME_ACCUMULATION   — BB squeeze (BBW < 70% del promedio 20 barras)
//    REGIME_DISTRIBUTION   — BB expansión post-tendencia + ADX decayendo
//    REGIME_UNKNOWN        — datos insuficientes para clasificar
//+------------------------------------------------------------------+
#property strict

enum ENUM_MARKET_REGIME
  {
   REGIME_TRENDING_BULL = 0,
   REGIME_TRENDING_BEAR = 1,
   REGIME_RANGING       = 2,
   REGIME_VOLATILE      = 3,
   REGIME_ACCUMULATION  = 4,
   REGIME_DISTRIBUTION  = 5,
   REGIME_UNKNOWN       = 6
  };

string RegimeToString(ENUM_MARKET_REGIME r)
  {
   switch(r)
     {
      case REGIME_TRENDING_BULL: return("TRENDING_BULL");
      case REGIME_TRENDING_BEAR: return("TRENDING_BEAR");
      case REGIME_RANGING:       return("RANGING");
      case REGIME_VOLATILE:      return("VOLATILE");
      case REGIME_ACCUMULATION:  return("ACCUMULATION");
      case REGIME_DISTRIBUTION:  return("DISTRIBUTION");
      default:                   return("UNKNOWN");
     }
  }

class CMarketRegimeEngine
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_tf;
   int             m_hAdx;
   int             m_hAtr;
   int             m_hBb;
   int             m_hEmaFast;
   int             m_hEmaSlow;
   double          m_adxTrend;
   double          m_adxRange;
   double          m_atrVolatile;
   double          m_bbwSqueezeRatio;
   ENUM_MARKET_REGIME m_lastRegime;

   bool CopyOne(int handle, int bufIdx, int shift, double &val)
     {
      double buf[1];
      if(CopyBuffer(handle, bufIdx, shift, 1, buf) != 1) return false;
      val = buf[0];
      return true;
     }

   double BufSma(int handle, int bufIdx, int period, int startShift)
     {
      double buf[];
      ArraySetAsSeries(buf, true);
      if(CopyBuffer(handle, bufIdx, startShift, period, buf) != period) return 0;
      double s = 0;
      for(int i = 0; i < period; i++) s += buf[i];
      return s / period;
     }

   double CalcBbw(double upper, double lower, double mid)
     {
      return (mid > 0) ? (upper - lower) / mid * 100.0 : 0.0;
     }

public:
   CMarketRegimeEngine()
     {
      m_hAdx = INVALID_HANDLE;
      m_hAtr = INVALID_HANDLE;
      m_hBb = INVALID_HANDLE;
      m_hEmaFast = INVALID_HANDLE;
      m_hEmaSlow = INVALID_HANDLE;
      m_lastRegime = REGIME_UNKNOWN;
     }

   bool Init(string symbol, ENUM_TIMEFRAMES tf,
             int emaFast      = 21,
             int emaSlow      = 55,
             double adxTrend  = 25.0,
             double adxRange  = 20.0,
             double atrVolat  = 2.0,
             double bbwSqz    = 0.70,
             int atrPeriod    = 14,
             int adxPeriod    = 14)
     {
      m_symbol          = symbol;
      m_tf              = tf;
      m_adxTrend        = adxTrend;
      m_adxRange        = adxRange;
      m_atrVolatile     = atrVolat;
      m_bbwSqueezeRatio = bbwSqz;
      m_lastRegime      = REGIME_UNKNOWN;

      m_hAdx     = iADX(symbol, tf, adxPeriod);
      m_hAtr     = iATR(symbol, tf, atrPeriod);
      m_hBb      = iBands(symbol, tf, 20, 0, 2.0, PRICE_CLOSE);
      m_hEmaFast = iMA(symbol, tf, emaFast, 0, MODE_EMA, PRICE_CLOSE);
      m_hEmaSlow = iMA(symbol, tf, emaSlow, 0, MODE_EMA, PRICE_CLOSE);

      return (m_hAdx != INVALID_HANDLE && m_hAtr != INVALID_HANDLE &&
              m_hBb  != INVALID_HANDLE && m_hEmaFast != INVALID_HANDLE &&
              m_hEmaSlow != INVALID_HANDLE);
     }

   void Release()
     {
      if(m_hAdx     != INVALID_HANDLE) { IndicatorRelease(m_hAdx);     m_hAdx = INVALID_HANDLE; }
      if(m_hAtr     != INVALID_HANDLE) { IndicatorRelease(m_hAtr);     m_hAtr = INVALID_HANDLE; }
      if(m_hBb      != INVALID_HANDLE) { IndicatorRelease(m_hBb);      m_hBb = INVALID_HANDLE; }
      if(m_hEmaFast != INVALID_HANDLE) { IndicatorRelease(m_hEmaFast); m_hEmaFast = INVALID_HANDLE; }
      if(m_hEmaSlow != INVALID_HANDLE) { IndicatorRelease(m_hEmaSlow); m_hEmaSlow = INVALID_HANDLE; }
     }

   ENUM_MARKET_REGIME Detect()
     {
      double adx, atr, bbUpper, bbLower, bbMid, emaFast1, emaSlow1, emaFast5;

      if(!CopyOne(m_hAdx,     0, 1, adx))      return REGIME_UNKNOWN;
      if(!CopyOne(m_hAtr,     0, 1, atr))      return REGIME_UNKNOWN;
      if(!CopyOne(m_hBb,      1, 1, bbUpper))  return REGIME_UNKNOWN;
      if(!CopyOne(m_hBb,      2, 1, bbLower))  return REGIME_UNKNOWN;
      if(!CopyOne(m_hBb,      0, 1, bbMid))    return REGIME_UNKNOWN;
      if(!CopyOne(m_hEmaFast, 0, 1, emaFast1)) return REGIME_UNKNOWN;
      if(!CopyOne(m_hEmaSlow, 0, 1, emaSlow1)) return REGIME_UNKNOWN;
      if(!CopyOne(m_hEmaFast, 0, 5, emaFast5)) emaFast5 = emaFast1;

      double atrSma = BufSma(m_hAtr, 0, 20, 1);
      if(atrSma <= 0) return REGIME_UNKNOWN;
      double atrRatio = atr / atrSma;

      double bbw    = CalcBbw(bbUpper, bbLower, bbMid);
      double bbwSma = 0;
        {
         double bbU[], bbL[], bbM[];
         ArraySetAsSeries(bbU, true);
         ArraySetAsSeries(bbL, true);
         ArraySetAsSeries(bbM, true);
         if(CopyBuffer(m_hBb, 1, 1, 20, bbU) == 20 &&
            CopyBuffer(m_hBb, 2, 1, 20, bbL) == 20 &&
            CopyBuffer(m_hBb, 0, 1, 20, bbM) == 20)
           {
            double s = 0;
            for(int i = 0; i < 20; i++)
               if(bbM[i] > 0) s += CalcBbw(bbU[i], bbL[i], bbM[i]);
            bbwSma = s / 20.0;
           }
        }

      bool slopeUp   = (emaFast1 > emaFast5);
      bool slopeDown = (emaFast1 < emaFast5);
      bool emaBull   = (emaFast1 > emaSlow1);

      double adxPrev;
      if(!CopyOne(m_hAdx, 0, 5, adxPrev)) adxPrev = adx;
      bool adxDecaying = (adx < adxPrev);

      if(atrRatio >= m_atrVolatile)
         return m_lastRegime = REGIME_VOLATILE;

      if(adx >= m_adxTrend)
        {
         if(slopeUp   &&  emaBull) return m_lastRegime = REGIME_TRENDING_BULL;
         if(slopeDown && !emaBull) return m_lastRegime = REGIME_TRENDING_BEAR;
        }

      if(bbwSma > 0 && bbw < bbwSma * m_bbwSqueezeRatio)
         return m_lastRegime = REGIME_ACCUMULATION;

      if(bbwSma > 0 && bbw > bbwSma * 1.5 && adxDecaying)
         return m_lastRegime = REGIME_DISTRIBUTION;

      if(adx < m_adxRange)
         return m_lastRegime = REGIME_RANGING;

      return m_lastRegime = REGIME_UNKNOWN;
     }

   ENUM_MARKET_REGIME GetLast() { return m_lastRegime; }

   // Deterministic scoring seam. It contains the production mapping and has
   // no symbol/history dependency, so L2 tests do not need a broker session.
   int ScoreForRegime(ENUM_MARKET_REGIME regime, bool isBuy)
     {
      switch(regime)
        {
         case REGIME_TRENDING_BULL: return isBuy  ? 25 : 0;
         case REGIME_TRENDING_BEAR: return !isBuy ? 25 : 0;
         case REGIME_ACCUMULATION:  return 15;
         case REGIME_RANGING:       return 5;
         case REGIME_VOLATILE:      return 0;
         case REGIME_DISTRIBUTION:  return 5;
         default:                   return 10;
        }
     }

   int RegimeScore(bool isBuy)
     {
      return ScoreForRegime(m_lastRegime, isBuy);
     }
  };
//+------------------------------------------------------------------+
