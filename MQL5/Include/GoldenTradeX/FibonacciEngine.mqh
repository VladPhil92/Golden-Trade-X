//+------------------------------------------------------------------+
//|                                            FibonacciEngine.mqh  |
//|   Golden Trade X — Niveles Fibonacci como confluencia           |
//+------------------------------------------------------------------+
//  Fibonacci NO genera señales de entrada de forma autónoma.
//  Su output es un score 0-20 que se añade al ConfidenceEngine.
//+------------------------------------------------------------------+
#property strict

struct SFibLevel
  {
   double ratio;
   double price;
   string label;
  };

struct SFibContext
  {
   double swingHigh;
   double swingLow;
   int    swingHighBar;
   int    swingLowBar;
   SFibLevel levels[7];
   int    levelCount;
   double nearestLevel;
   double nearestRatio;
   bool   inPremiumZone;
   bool   inDiscountZone;
  };

class CFibonacciEngine
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_tf;
   int             m_swingLookback;
   double          m_proxAtrMult;
   int             m_hAtr;

   static const double RATIOS[7];

   bool IsSwingHigh(int bar, int n = 3)
     {
      double h = iHigh(m_symbol, m_tf, bar);
      for(int k = 1; k <= n; k++)
        {
         if(bar + k < m_swingLookback && iHigh(m_symbol, m_tf, bar + k) >= h) return false;
         if(bar - k >= 1             && iHigh(m_symbol, m_tf, bar - k) >= h) return false;
        }
      return true;
     }

   bool IsSwingLow(int bar, int n = 3)
     {
      double l = iLow(m_symbol, m_tf, bar);
      for(int k = 1; k <= n; k++)
        {
         if(bar + k < m_swingLookback && iLow(m_symbol, m_tf, bar + k) <= l) return false;
         if(bar - k >= 1              && iLow(m_symbol, m_tf, bar - k) <= l) return false;
        }
      return true;
     }

   double GetAtr()
     {
      double buf[1];
      if(m_hAtr != INVALID_HANDLE && CopyBuffer(m_hAtr, 0, 1, 1, buf) == 1 && buf[0] > 0)
         return buf[0];
      return 0.0;
     }

   int FindSwingHigh()
     {
      for(int i = 1; i < m_swingLookback; i++)
         if(IsSwingHigh(i)) return i;
      return -1;
     }

   int FindSwingLow()
     {
      for(int i = 1; i < m_swingLookback; i++)
         if(IsSwingLow(i)) return i;
      return -1;
     }

public:
   CFibonacciEngine() { m_hAtr = INVALID_HANDLE; }

   bool Init(string symbol, ENUM_TIMEFRAMES tf,
             int swingLookback = 100, double proxAtrMult = 0.5,
             int atrPeriod = 14)
     {
      m_symbol        = symbol;
      m_tf            = tf;
      m_swingLookback = swingLookback;
      m_proxAtrMult   = proxAtrMult;
      m_hAtr          = iATR(symbol, tf, atrPeriod);
      return (m_hAtr != INVALID_HANDLE);
     }

   void Release()
     {
      if(m_hAtr != INVALID_HANDLE) { IndicatorRelease(m_hAtr); m_hAtr = INVALID_HANDLE; }
     }

   SFibContext Analyze()
     {
      SFibContext ctx;
      ZeroMemory(ctx);
      ctx.levelCount = 7;

      int shBar = FindSwingHigh();
      int slBar = FindSwingLow();
      if(shBar < 0 || slBar < 0) return ctx;

      ctx.swingHighBar = shBar;
      ctx.swingLowBar  = slBar;
      ctx.swingHigh    = iHigh(m_symbol, m_tf, shBar);
      ctx.swingLow     = iLow(m_symbol,  m_tf, slBar);

      double range = ctx.swingHigh - ctx.swingLow;
      if(range <= 0) return ctx;

      bool bullishStructure = (slBar > shBar);
      double ratios[7] = {0.236, 0.382, 0.500, 0.618, 0.786, 1.272, 1.618};
      string labels[7] = {"23.6%","38.2%","50.0%","61.8%","78.6%","127.2%","161.8%"};

      for(int i = 0; i < 7; i++)
        {
         ctx.levels[i].ratio = ratios[i];
         ctx.levels[i].label = labels[i];
         if(bullishStructure)
            ctx.levels[i].price = ctx.swingHigh - range * ratios[i];
         else
            ctx.levels[i].price = ctx.swingLow + range * ratios[i];
        }

      double curPrice = iClose(m_symbol, m_tf, 1);
      double mid = ctx.swingLow + range * 0.5;
      ctx.inPremiumZone  = (curPrice > mid);
      ctx.inDiscountZone = (curPrice < mid);

      double minDist = DBL_MAX;
      ctx.nearestLevel = 0;
      ctx.nearestRatio = 0;
      for(int i = 0; i < 7; i++)
        {
         double dist = MathAbs(curPrice - ctx.levels[i].price);
         if(dist < minDist)
           {
            minDist = dist;
            ctx.nearestLevel = ctx.levels[i].price;
            ctx.nearestRatio = ratios[i];
           }
        }
      return ctx;
     }

   // Pure production scoring seam. The market-dependent FibScore() handles
   // proximity; once a ratio is eligible, this is the only mapping used by
   // both live code and deterministic unit tests.
   int ScoreForRatio(double ratio, bool inPremiumZone,
                     bool inDiscountZone, bool isBuy)
     {
      int score = 0;
      if(MathAbs(ratio - 0.382) < 0.01 || MathAbs(ratio - 0.618) < 0.01)
         score = 20;
      else if(MathAbs(ratio - 0.500) < 0.01)
         score = 15;
      else if(MathAbs(ratio - 0.786) < 0.01 || MathAbs(ratio - 0.236) < 0.01)
         score = 10;
      else
         score = 5;

      if(isBuy  && inPremiumZone)  score = (int)(score * 0.5);
      if(!isBuy && inDiscountZone) score = (int)(score * 0.5);
      return MathMin(score, 20);
     }

   int FibScore(const SFibContext &ctx, bool isBuy)
     {
      if(ctx.swingHigh <= ctx.swingLow) return 0;

      double curPrice  = iClose(m_symbol, m_tf, 1);
      double atr       = GetAtr();
      if(atr <= 0) return 0;
      double proximity = atr * m_proxAtrMult;
      double dist      = MathAbs(curPrice - ctx.nearestLevel);
      if(dist > proximity) return 0;

      return ScoreForRatio(ctx.nearestRatio,
                           ctx.inPremiumZone,
                           ctx.inDiscountZone,
                           isBuy);
     }
  };

const double CFibonacciEngine::RATIOS[7] = {0.236, 0.382, 0.500, 0.618, 0.786, 1.272, 1.618};
//+------------------------------------------------------------------+
