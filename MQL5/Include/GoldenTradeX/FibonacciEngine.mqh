//+------------------------------------------------------------------+
//|                                            FibonacciEngine.mqh  |
//|   Golden Trade X v2.00 — Niveles Fibonacci como confluencia      |
//+------------------------------------------------------------------+
//  Fibonacci NO genera señales de entrada de forma autónoma.
//  Su output es un score 0-20 que se añade al ConfidenceEngine.
//
//  Funcionalidad:
//    - Detecta el swing high y swing low más recientes (lookback=100)
//    - Calcula retrocesos 23.6%, 38.2%, 50%, 61.8%, 78.6%
//    - Calcula extensiones 127.2%, 161.8%
//    - Retorna FibScore(isBuy): 0-20 según proximidad del precio
//      actual a un nivel de alta confluencia
//    - Identifica la zona Premium (>61.8%) y Discount (<38.2%)
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
   SFibLevel levels[7];  // 23.6, 38.2, 50.0, 61.8, 78.6, 127.2, 161.8
   int    levelCount;
   double nearestLevel;
   double nearestRatio;
   bool   inPremiumZone;   // precio > 50% del rango (zona cara para compras)
   bool   inDiscountZone;  // precio < 50% del rango (zona barata para compras)
  };

class CFibonacciEngine
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_tf;
   int             m_swingLookback;
   double          m_proxAtrMult;  // multiplicador ATR para "cerca de nivel"
   int             m_hAtr;         // v2.50: handle ATR cacheado (creado en Init)

   static const double RATIOS[7];

   // v2.50: la barra 0 (en formación) se excluye de la detección de swings —
   // incluirla hacía que los niveles Fib cambiaran intra-barra.
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

   // ATR de la última vela cerrada desde el handle cacheado
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
             int swingLookback = 100, double proxAtrMult = 0.5)
     {
      m_symbol        = symbol;
      m_tf            = tf;
      m_swingLookback = swingLookback;
      m_proxAtrMult   = proxAtrMult;
      m_hAtr          = iATR(symbol, tf, 14);
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

      // Bearish structure (SH before SL): retrocesos desde arriba
      // Bullish structure (SL before SH): retrocesos desde abajo
      bool bullishStructure = (slBar > shBar);  // SL is older (higher bar index)

      double ratios[7] = {0.236, 0.382, 0.500, 0.618, 0.786, 1.272, 1.618};
      string labels[7] = {"23.6%","38.2%","50.0%","61.8%","78.6%","127.2%","161.8%"};

      for(int i = 0; i < 7; i++)
        {
         ctx.levels[i].ratio = ratios[i];
         ctx.levels[i].label = labels[i];
         if(bullishStructure)
            ctx.levels[i].price = ctx.swingHigh - range * ratios[i];
         else
            ctx.levels[i].price = ctx.swingLow  + range * ratios[i];
        }

      // Zona Premium/Discount (siempre relativo a la dirección de la estructura)
      double curPrice = iClose(m_symbol, m_tf, 1);
      double mid      = ctx.swingLow + range * 0.5;
      ctx.inPremiumZone  = (curPrice > mid);
      ctx.inDiscountZone = (curPrice < mid);

      // Nivel más cercano al precio actual
      double minDist  = DBL_MAX;
      ctx.nearestLevel = 0;
      ctx.nearestRatio = 0;

      for(int i = 0; i < 7; i++)
        {
         double dist = MathAbs(curPrice - ctx.levels[i].price);
         if(dist < minDist)
           { minDist = dist; ctx.nearestLevel = ctx.levels[i].price; ctx.nearestRatio = ratios[i]; }
        }

      return ctx;
     }

   // Score 0-20 según confluencia Fibonacci con la dirección de la operación
   int FibScore(const SFibContext &ctx, bool isBuy)
     {
      if(ctx.swingHigh <= ctx.swingLow) return 0;

      double curPrice  = iClose(m_symbol, m_tf, 1);
      double atr       = GetAtr();
      if(atr <= 0) return 0;   // sin ATR fiable no hay medida de proximidad
      double proximity = atr * m_proxAtrMult;
      double dist      = MathAbs(curPrice - ctx.nearestLevel);

      // Precio no está cerca de ningún nivel: sin bonus
      if(dist > proximity) return 0;

      double ratio = ctx.nearestRatio;
      int score = 0;

      // Los niveles 38.2%, 61.8% y 50% son los más significativos
      if(MathAbs(ratio - 0.382) < 0.01 || MathAbs(ratio - 0.618) < 0.01)
         score = 20;
      else if(MathAbs(ratio - 0.500) < 0.01)
         score = 15;
      else if(MathAbs(ratio - 0.786) < 0.01 || MathAbs(ratio - 0.236) < 0.01)
         score = 10;
      else
         score = 5;  // extensiones 127.2% / 161.8%

      // Descuento por zona desfavorable: BUY en Premium o SELL en Discount
      if(isBuy  && ctx.inPremiumZone)  score = (int)(score * 0.5);
      if(!isBuy && ctx.inDiscountZone) score = (int)(score * 0.5);

      return MathMin(score, 20);
     }
  };

const double CFibonacciEngine::RATIOS[7] = {0.236, 0.382, 0.500, 0.618, 0.786, 1.272, 1.618};
//+------------------------------------------------------------------+
