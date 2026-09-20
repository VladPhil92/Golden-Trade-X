//+------------------------------------------------------------------+
//|                                  AdaptiveAnalysisEngine.mqh      |
//| Golden Trade X v2.64 — Adaptive multi-asset analysis (research)  |
//+------------------------------------------------------------------+
// This engine is deliberately research-first. It produces a normalized,
// price-scale-independent quality assessment for GOLD/XAU and BTC symbols.
// The baseline EA behavior is unchanged unless InpUseAdaptiveAnalysisFilter
// is enabled. Scores are heuristic until calibrated with IS -> frozen OOS.
//+------------------------------------------------------------------+
#property strict

enum ENUM_GTX_ANALYSIS_PROFILE
  {
   GTX_ANALYSIS_AUTO    = 0,
   GTX_ANALYSIS_GENERIC = 1,
   GTX_ANALYSIS_GOLD    = 2,
   GTX_ANALYSIS_BTC     = 3
  };

string GtxAnalysisProfileToString(ENUM_GTX_ANALYSIS_PROFILE profile)
  {
   switch(profile)
     {
      case GTX_ANALYSIS_GOLD:    return "GOLD";
      case GTX_ANALYSIS_BTC:     return "BTC";
      case GTX_ANALYSIS_GENERIC: return "GENERIC";
      default:                   return "AUTO";
     }
  }

struct SAdaptiveMetrics
  {
   bool   valid;
   double trendSeparationAtr;
   double directionalSlopeAtr;
   double rsi;
   double adx;
   double candleEfficiency;
   double atrBps;
   double spreadBps;
   double volumeRatio;
   double rangePosition;
   bool   htfAligned;
  };

struct SAdaptiveAnalysisResult
  {
   bool   valid;
   bool   directionAligned;
   bool   passed;
   int    quality;
   int    trendScore;
   int    momentumScore;
   int    strengthScore;
   int    htfScore;
   int    structureScore;
   int    efficiencyScore;
   int    liquidityScore;
   double atrBps;
   double spreadBps;
   double volumeRatio;
   ENUM_GTX_ANALYSIS_PROFILE profile;
  };

double GtxClamp(double value, double low, double high)
  {
   if(value < low) return low;
   if(value > high) return high;
   return value;
  }

double GtxSpreadBps(double bid, double ask)
  {
   if(bid <= 0 || ask <= 0 || ask < bid) return DBL_MAX;
   double mid = (bid + ask) * 0.5;
   if(mid <= 0) return DBL_MAX;
   return ((ask - bid) / mid) * 10000.0;
  }

ENUM_GTX_ANALYSIS_PROFILE GtxResolveAnalysisProfile(string symbol,
                                                    ENUM_GTX_ANALYSIS_PROFILE requested)
  {
   if(requested != GTX_ANALYSIS_AUTO)
      return requested;

   string upper = symbol;
   StringToUpper(upper);
   if(StringFind(upper, "BTC") >= 0)
      return GTX_ANALYSIS_BTC;
   if(StringFind(upper, "GOLD") >= 0 || StringFind(upper, "XAU") >= 0)
      return GTX_ANALYSIS_GOLD;
   return GTX_ANALYSIS_GENERIC;
  }

double GtxDefaultSpreadBps(ENUM_GTX_ANALYSIS_PROFILE profile)
  {
   // Research defaults, not claims of optimal execution thresholds.
   if(profile == GTX_ANALYSIS_GOLD) return 6.0;
   if(profile == GTX_ANALYSIS_BTC)  return 12.0;
   return 8.0;
  }

SAdaptiveAnalysisResult GtxScoreAdaptiveMetrics(const SAdaptiveMetrics &m,
                                                bool isBuy,
                                                ENUM_GTX_ANALYSIS_PROFILE profile,
                                                int minQuality,
                                                double maxSpreadBps)
  {
   SAdaptiveAnalysisResult r;
   ZeroMemory(r);
   r.profile = profile;
   r.atrBps = m.atrBps;
   r.spreadBps = m.spreadBps;
   r.volumeRatio = m.volumeRatio;

   if(!m.valid || m.spreadBps == DBL_MAX)
      return r;

   r.valid = true;

   // Trend: EMA separation normalized by ATR (0-12) plus directional slope (0-8).
   double separationPart = GtxClamp(m.trendSeparationAtr / 0.50, 0.0, 1.0) * 12.0;
   bool slopeAligned = (m.directionalSlopeAtr > 0.0);
   double slopePart = slopeAligned
                      ? GtxClamp(m.directionalSlopeAtr / 0.35, 0.0, 1.0) * 8.0
                      : 0.0;
   r.trendScore = (int)MathRound(separationPart + slopePart);

   // Momentum: directional distance from RSI 50, saturated at 20 RSI points.
   double directionalMomentum = isBuy ? (m.rsi - 50.0) : (50.0 - m.rsi);
   r.momentumScore = (int)MathRound(
      GtxClamp(directionalMomentum / 20.0, 0.0, 1.0) * 15.0);

   // Trend strength: ADX 15..35 maps to 0..15.
   r.strengthScore = (int)MathRound(
      GtxClamp((m.adx - 15.0) / 20.0, 0.0, 1.0) * 15.0);

   r.htfScore = m.htfAligned ? 15 : 0;

   // Structure: closed-bar position inside 20-bar range, directionally normalized.
   double directionalRange = isBuy ? m.rangePosition : (1.0 - m.rangePosition);
   r.structureScore = (int)MathRound(
      GtxClamp((directionalRange - 0.45) / 0.45, 0.0, 1.0) * 15.0);

   // Candle efficiency: body / full range. 70%+ earns the full 10 points.
   r.efficiencyScore = (int)MathRound(
      GtxClamp(m.candleEfficiency / 0.70, 0.0, 1.0) * 10.0);

   // Liquidity: 6 points for spread quality + 4 points for relative tick activity.
   double spreadLimit = maxSpreadBps > 0
                        ? maxSpreadBps
                        : GtxDefaultSpreadBps(profile);
   double spreadScore = 0.0;
   if(spreadLimit > 0 && m.spreadBps <= spreadLimit)
      spreadScore = (1.0 - GtxClamp(m.spreadBps / spreadLimit, 0.0, 1.0)) * 6.0;

   double volumeScore = GtxClamp((m.volumeRatio - 0.50) / 0.75, 0.0, 1.0) * 4.0;
   r.liquidityScore = (int)MathRound(spreadScore + volumeScore);

   r.quality = r.trendScore +
               r.momentumScore +
               r.strengthScore +
               r.htfScore +
               r.structureScore +
               r.efficiencyScore +
               r.liquidityScore;
   r.quality = (int)GtxClamp((double)r.quality, 0.0, 100.0);

   // A quality score alone is not enough: direction must agree across slope,
   // HTF and broad range location. This avoids high-score contradictory setups.
   bool structureAligned = isBuy ? (m.rangePosition >= 0.50)
                                 : (m.rangePosition <= 0.50);
   r.directionAligned = slopeAligned && m.htfAligned && structureAligned;
   r.passed = r.directionAligned &&
              r.quality >= minQuality &&
              m.spreadBps <= spreadLimit;

   return r;
  }

class CAdaptiveAnalysisEngine
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_tf;
   ENUM_GTX_ANALYSIS_PROFILE m_profile;
   int             m_minQuality;
   double          m_maxSpreadBps;

   int m_hEmaFast;
   int m_hEmaSlow;
   int m_hRsi;
   int m_hAdx;
   int m_hAtr;
   int m_hHtfEma;

   bool CopyOne(int handle, int buffer, int shift, double &value)
     {
      double buf[1];
      if(CopyBuffer(handle, buffer, shift, 1, buf) != 1) return false;
      value = buf[0];
      return true;
     }

   double AverageTickVolume(int startShift, int period)
     {
      if(period <= 0) return 0.0;
      double sum = 0.0;
      int valid = 0;
      for(int i = startShift; i < startShift + period; i++)
        {
         long volume = iVolume(m_symbol, m_tf, i);
         if(volume <= 0) continue;
         sum += (double)volume;
         valid++;
        }
      return valid > 0 ? sum / valid : 0.0;
     }

   bool RollingRange(int startShift, int period, double &highest, double &lowest)
     {
      highest = -DBL_MAX;
      lowest = DBL_MAX;
      int valid = 0;
      for(int i = startShift; i < startShift + period; i++)
        {
         double high = iHigh(m_symbol, m_tf, i);
         double low = iLow(m_symbol, m_tf, i);
         if(high <= 0 || low <= 0 || high < low) continue;
         if(high > highest) highest = high;
         if(low < lowest) lowest = low;
         valid++;
        }
      return valid == period && highest > lowest;
     }

public:
   CAdaptiveAnalysisEngine()
     {
      m_hEmaFast = INVALID_HANDLE;
      m_hEmaSlow = INVALID_HANDLE;
      m_hRsi = INVALID_HANDLE;
      m_hAdx = INVALID_HANDLE;
      m_hAtr = INVALID_HANDLE;
      m_hHtfEma = INVALID_HANDLE;
      m_profile = GTX_ANALYSIS_GENERIC;
      m_minQuality = 55;
      m_maxSpreadBps = 0.0;
     }

   bool Init(string symbol,
             ENUM_TIMEFRAMES tf,
             int emaFast,
             int emaSlow,
             int rsiPeriod,
             int adxPeriod,
             int atrPeriod,
             int htfEmaPeriod,
             ENUM_GTX_ANALYSIS_PROFILE requestedProfile,
             int minQuality,
             double maxSpreadBps)
     {
      m_symbol = symbol;
      m_tf = tf;
      m_profile = GtxResolveAnalysisProfile(symbol, requestedProfile);
      m_minQuality = MathMax(0, MathMin(minQuality, 100));
      m_maxSpreadBps = MathMax(0.0, maxSpreadBps);

      m_hEmaFast = iMA(symbol, tf, emaFast, 0, MODE_EMA, PRICE_CLOSE);
      m_hEmaSlow = iMA(symbol, tf, emaSlow, 0, MODE_EMA, PRICE_CLOSE);
      m_hRsi = iRSI(symbol, tf, rsiPeriod, PRICE_CLOSE);
      m_hAdx = iADX(symbol, tf, adxPeriod);
      m_hAtr = iATR(symbol, tf, atrPeriod);
      m_hHtfEma = iMA(symbol, PERIOD_H4, htfEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);

      return m_hEmaFast != INVALID_HANDLE &&
             m_hEmaSlow != INVALID_HANDLE &&
             m_hRsi != INVALID_HANDLE &&
             m_hAdx != INVALID_HANDLE &&
             m_hAtr != INVALID_HANDLE &&
             m_hHtfEma != INVALID_HANDLE;
     }

   void Release()
     {
      if(m_hEmaFast != INVALID_HANDLE) { IndicatorRelease(m_hEmaFast); m_hEmaFast = INVALID_HANDLE; }
      if(m_hEmaSlow != INVALID_HANDLE) { IndicatorRelease(m_hEmaSlow); m_hEmaSlow = INVALID_HANDLE; }
      if(m_hRsi != INVALID_HANDLE)     { IndicatorRelease(m_hRsi);     m_hRsi = INVALID_HANDLE; }
      if(m_hAdx != INVALID_HANDLE)     { IndicatorRelease(m_hAdx);     m_hAdx = INVALID_HANDLE; }
      if(m_hAtr != INVALID_HANDLE)     { IndicatorRelease(m_hAtr);     m_hAtr = INVALID_HANDLE; }
      if(m_hHtfEma != INVALID_HANDLE)  { IndicatorRelease(m_hHtfEma);  m_hHtfEma = INVALID_HANDLE; }
     }

   ENUM_GTX_ANALYSIS_PROFILE GetProfile() const
     { return m_profile; }

   SAdaptiveAnalysisResult Analyze(bool isBuy)
     {
      SAdaptiveMetrics m;
      ZeroMemory(m);

      double fast1, fast5, slow1, rsi1, adx1, atr1, htf1, htf5;
      if(!CopyOne(m_hEmaFast, 0, 1, fast1)) return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);
      if(!CopyOne(m_hEmaFast, 0, 5, fast5)) return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);
      if(!CopyOne(m_hEmaSlow, 0, 1, slow1)) return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);
      if(!CopyOne(m_hRsi, 0, 1, rsi1))      return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);
      if(!CopyOne(m_hAdx, 0, 1, adx1))      return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);
      if(!CopyOne(m_hAtr, 0, 1, atr1))      return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);
      if(!CopyOne(m_hHtfEma, 0, 1, htf1))  return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);
      if(!CopyOne(m_hHtfEma, 0, 5, htf5))  htf5 = htf1;

      double open1 = iOpen(m_symbol, m_tf, 1);
      double high1 = iHigh(m_symbol, m_tf, 1);
      double low1 = iLow(m_symbol, m_tf, 1);
      double close1 = iClose(m_symbol, m_tf, 1);
      if(open1 <= 0 || high1 <= 0 || low1 <= 0 || close1 <= 0 || high1 <= low1 || atr1 <= 0)
         return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);

      double rangeHigh, rangeLow;
      if(!RollingRange(1, 20, rangeHigh, rangeLow))
         return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);

      double avgVolume = AverageTickVolume(2, 20);
      long volume1 = iVolume(m_symbol, m_tf, 1);
      if(avgVolume <= 0 || volume1 <= 0)
         return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);

      double htfClose1 = iClose(m_symbol, PERIOD_H4, 1);
      if(htfClose1 <= 0)
         return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);

      double bid = SymbolInfoDouble(m_symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(m_symbol, SYMBOL_ASK);
      double spreadBps = GtxSpreadBps(bid, ask);
      if(spreadBps == DBL_MAX)
         return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);

      double directionalSlope = isBuy ? (fast1 - fast5) : (fast5 - fast1);
      bool htfPriceAligned = isBuy ? (htfClose1 > htf1) : (htfClose1 < htf1);
      bool htfSlopeAligned = isBuy ? (htf1 > htf5) : (htf1 < htf5);

      m.valid = true;
      m.trendSeparationAtr = MathAbs(fast1 - slow1) / atr1;
      m.directionalSlopeAtr = directionalSlope / atr1;
      m.rsi = rsi1;
      m.adx = adx1;
      m.candleEfficiency = MathAbs(close1 - open1) / (high1 - low1);
      m.atrBps = (atr1 / close1) * 10000.0;
      m.spreadBps = spreadBps;
      m.volumeRatio = (double)volume1 / avgVolume;
      m.rangePosition = GtxClamp((close1 - rangeLow) / (rangeHigh - rangeLow), 0.0, 1.0);
      m.htfAligned = htfPriceAligned && htfSlopeAligned;

      return GtxScoreAdaptiveMetrics(m, isBuy, m_profile, m_minQuality, m_maxSpreadBps);
     }
  };
//+------------------------------------------------------------------+
