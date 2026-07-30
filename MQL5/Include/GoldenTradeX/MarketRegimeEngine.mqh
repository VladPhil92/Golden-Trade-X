//+------------------------------------------------------------------+
//|                                          MarketRegimeEngine.mqh  |
//|   Golden Trade X v2.00 — Detección automática de régimen         |
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
   bool Init(string symbol, ENUM_TIMEFRAMES tf,
             int emaFast      = 21,
             int emaSlow      = 55,
             double adxTrend  = 25.0,
             double adxRange  = 20.0,
             double atrVolat  = 2.0,
             double bbwSqz    = 0.70)
     {
      m_symbol          = symbol;
      m_tf              = tf;
      m_adxTrend        = adxTrend;
      m_adxRange        = adxRange;
      m_atrVolatile     = atrVolat;
      m_bbwSqueezeRatio = bbwSqz;
      m_lastRegime      = REGIME_UNKNOWN;

      m_hAdx     = iADX(symbol, tf, 14);
      m_hAtr     = iATR(symbol, tf, 14);
      m_hBb      = iBands(symbol, tf, 20, 0, 2.0, PRICE_CLOSE);
      m_hEmaFast = iMA(symbol, tf, emaFast, 0, MODE_EMA, PRICE_CLOSE);
      m_hEmaSlow = iMA(symbol, tf, emaSlow, 0, MODE_EMA, PRICE_CLOSE);

      return (m_hAdx != INVALID_HANDLE && m_hAtr != INVALID_HANDLE &&
              m_hBb  != INVALID_HANDLE && m_hEmaFast != INVALID_HANDLE &&
              m_hEmaSlow != INVALID_HANDLE);
     }

   void Release()
     {
      if(m_hAdx     != INVALID_HANDLE) IndicatorRelease(m_hAdx);
      if(m_hAtr     != INVALID_HANDLE) IndicatorRelease(m_hAtr);
      if(m_hBb      != INVALID_HANDLE) IndicatorRelease(m_hBb);
      if(m_hEmaFast != INVALID_HANDLE) IndicatorRelease(m_hEmaFast);
      if(m_hEmaSlow != INVALID_HANDLE) IndicatorRelease(m_hEmaSlow);
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

      // BBW actual y su media 20 barras
      double bbw    = CalcBbw(bbUpper, bbLower, bbMid);
      double bbwSma = 0;
        {
         double bbU[], bbL[], bbM[];
         ArraySetAsSeries(bbU, true); ArraySetAsSeries(bbL, true); ArraySetAsSeries(bbM, true);
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

      // ADX anterior para detectar decaimiento
      double adxPrev;
      if(!CopyOne(m_hAdx, 0, 5, adxPrev)) adxPrev = adx;
      bool adxDecaying = (adx < adxPrev);

      // ── Clasificación por prioridad ───────────────────────────────────
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

   ENUM_MARKET_REGIME GetLast()  { return m_lastRegime; }

   // Retorna un score de alineación 0-25 según régimen y dirección de operación
   int RegimeScore(bool isBuy)
     {
      switch(m_lastRegime)
        {
         case REGIME_TRENDING_BULL: return isBuy  ? 25 : 0;
         case REGIME_TRENDING_BEAR: return !isBuy ? 25 : 0;
         case REGIME_ACCUMULATION:  return 15;   // oportunidad pre-breakout en ambas dir
         case REGIME_RANGING:       return 5;    // señales de menor calidad en rangos
         case REGIME_VOLATILE:      return 0;    // bloqueo total
         case REGIME_DISTRIBUTION:  return 5;
         default:                   return 10;
        }
     }
  };
//+------------------------------------------------------------------+
