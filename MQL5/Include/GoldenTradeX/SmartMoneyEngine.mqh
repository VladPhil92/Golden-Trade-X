//+------------------------------------------------------------------+
//|                                           SmartMoneyEngine.mqh  |
//|   Golden Trade X v2.00 — Smart Money Concepts                   |
//+------------------------------------------------------------------+
//  Detecta:
//    BOS  — Break of Structure (ruptura de máximo/mínimo previo)
//    CHOCH — Change of Character (cambio de estructura de mercado)
//    FVG   — Fair Value Gap (brecha de valor justo, 3 velas)
//    OB    — Order Block (última vela contratendencia antes del BOS)
//    LS    — Liquidity Sweep (barrido de liquidez y reversión)
//
//  NO genera señales de entrada por sí solo.
//  Su output se integra en CConfidenceEngine para scoring.
//+------------------------------------------------------------------+
#property strict

enum ENUM_SMC_BIAS
  {
   SMC_NEUTRAL = 0,
   SMC_BULLISH = 1,
   SMC_BEARISH = -1
  };

struct SFvgZone
  {
   double high;
   double low;
   bool   active;
   int    bar;
  };

struct SOrderBlock
  {
   double high;
   double low;
   bool   active;
   int    bar;
   bool   isBullish;
  };

struct SSmcContext
  {
   ENUM_SMC_BIAS bos;          // BOS detectado en últimas lookback barras
   ENUM_SMC_BIAS choch;        // CHOCH (cambio de carácter estructural)
   bool          hasBullFvg;   // FVG alcista no mitigado próximo al precio
   bool          hasBearFvg;   // FVG bajista no mitigado próximo al precio
   bool          hasBullOb;    // Order Block alcista válido
   bool          hasBearOb;    // Order Block bajista válido
   bool          liquiditySweep; // Barrido de liquidez reciente
   double        bullFvgHigh;
   double        bullFvgLow;
   double        bearFvgHigh;
   double        bearFvgLow;
   double        bullObHigh;
   double        bullObLow;
   double        bearObHigh;
   double        bearObLow;
  };

class CSmartMoneyEngine
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_tf;
   int             m_swingLookback;  // barras para detectar swings (default 50)
   int             m_fvgLookback;    // barras hacia atrás para FVGs (default 20)
   int             m_obLookback;     // barras hacia atrás para OBs (default 40)
   double          m_proxPct;        // % del ATR para considerar "precio cerca" de FVG/OB

   // Swing de N barras: high[i] es máximo si supera a las N barras de cada lado
   bool IsSwingHigh(int bar, int n = 3)
     {
      double h = iHigh(m_symbol, m_tf, bar);
      for(int k = 1; k <= n; k++)
        {
         if(iHigh(m_symbol, m_tf, bar + k) >= h) return false;
         if(bar - k >= 0 && iHigh(m_symbol, m_tf, bar - k) >= h) return false;
        }
      return true;
     }

   bool IsSwingLow(int bar, int n = 3)
     {
      double l = iLow(m_symbol, m_tf, bar);
      for(int k = 1; k <= n; k++)
        {
         if(iLow(m_symbol, m_tf, bar + k) <= l) return false;
         if(bar - k >= 0 && iLow(m_symbol, m_tf, bar - k) <= l) return false;
        }
      return true;
     }

   // Encuentra el swing high/low más reciente dentro de [startBar, endBar]
   int LastSwingHigh(int startBar, int endBar)
     {
      for(int i = startBar; i <= endBar; i++)
         if(IsSwingHigh(i)) return i;
      return -1;
     }

   int LastSwingLow(int startBar, int endBar)
     {
      for(int i = startBar; i <= endBar; i++)
         if(IsSwingLow(i)) return i;
      return -1;
     }

   // BOS alcista: precio actual cierra sobre el swing high previo
   bool IsBullBos(int lookback)
     {
      double curClose = iClose(m_symbol, m_tf, 1);
      int swBar = LastSwingHigh(2, lookback);
      if(swBar < 0) return false;
      return curClose > iHigh(m_symbol, m_tf, swBar);
     }

   // BOS bajista: precio actual cierra bajo el swing low previo
   bool IsBearBos(int lookback)
     {
      double curClose = iClose(m_symbol, m_tf, 1);
      int swBar = LastSwingLow(2, lookback);
      if(swBar < 0) return false;
      return curClose < iLow(m_symbol, m_tf, swBar);
     }

   // FVG alcista: high[bar+2] < low[bar] (gap entre 3 velas)
   bool GetBullFvg(int lookback, SFvgZone &zone)
     {
      for(int i = 1; i <= lookback - 2; i++)
        {
         double h2 = iHigh(m_symbol, m_tf, i + 2);
         double l0 = iLow(m_symbol, m_tf,  i);
         if(h2 < l0)
           {
            zone.high   = l0;
            zone.low    = h2;
            zone.bar    = i;
            zone.active = true;
            return true;
           }
        }
      return false;
     }

   // FVG bajista: low[bar+2] > high[bar]
   bool GetBearFvg(int lookback, SFvgZone &zone)
     {
      for(int i = 1; i <= lookback - 2; i++)
        {
         double l2 = iLow(m_symbol,  m_tf, i + 2);
         double h0 = iHigh(m_symbol, m_tf, i);
         if(l2 > h0)
           {
            zone.high   = l2;
            zone.low    = h0;
            zone.bar    = i;
            zone.active = true;
            return true;
           }
        }
      return false;
     }

   // Order Block alcista: última vela bajista antes de un impulso alcista (BOS bull)
   bool GetBullOb(int lookback, SOrderBlock &ob)
     {
      if(!IsBullBos(lookback)) return false;
      // Busca la última vela bajista (close < open) en las últimas barras
      for(int i = 2; i <= lookback; i++)
        {
         if(iClose(m_symbol, m_tf, i) < iOpen(m_symbol, m_tf, i))
           {
            ob.high      = iHigh(m_symbol, m_tf, i);
            ob.low       = iLow(m_symbol,  m_tf, i);
            ob.bar       = i;
            ob.active    = true;
            ob.isBullish = true;
            return true;
           }
        }
      return false;
     }

   // Order Block bajista: última vela alcista antes de un impulso bajista (BOS bear)
   bool GetBearOb(int lookback, SOrderBlock &ob)
     {
      if(!IsBearBos(lookback)) return false;
      for(int i = 2; i <= lookback; i++)
        {
         if(iClose(m_symbol, m_tf, i) > iOpen(m_symbol, m_tf, i))
           {
            ob.high      = iHigh(m_symbol, m_tf, i);
            ob.low       = iLow(m_symbol,  m_tf, i);
            ob.bar       = i;
            ob.active    = true;
            ob.isBullish = false;
            return true;
           }
        }
      return false;
     }

   // Liquidity Sweep alcista: vela barre un swing low con wick y cierra arriba
   bool IsBullLiqSweep(int lookback)
     {
      int swBar = LastSwingLow(2, lookback);
      if(swBar < 0) return false;
      double swLow = iLow(m_symbol, m_tf, swBar);
      // Barra 1 tiene wick abajo que toca el swing y cierra arriba de él
      double bar1Low   = iLow(m_symbol,   m_tf, 1);
      double bar1Close = iClose(m_symbol, m_tf, 1);
      return (bar1Low < swLow && bar1Close > swLow);
     }

   bool IsBearLiqSweep(int lookback)
     {
      int swBar = LastSwingHigh(2, lookback);
      if(swBar < 0) return false;
      double swHigh  = iHigh(m_symbol,  m_tf, swBar);
      double bar1High  = iHigh(m_symbol,  m_tf, 1);
      double bar1Close = iClose(m_symbol, m_tf, 1);
      return (bar1High > swHigh && bar1Close < swHigh);
     }

   // ¿El precio actual está cerca de una zona (dentro de 1×ATR)?
   bool NearZone(double price, double zoneHigh, double zoneLow, double atr)
     {
      double proximity = atr * m_proxPct;
      return (price >= zoneLow - proximity && price <= zoneHigh + proximity);
     }

public:
   bool Init(string symbol, ENUM_TIMEFRAMES tf,
             int swingLookback = 50,
             int fvgLookback   = 20,
             int obLookback    = 40,
             double proxPct    = 1.0)
     {
      m_symbol       = symbol;
      m_tf           = tf;
      m_swingLookback = swingLookback;
      m_fvgLookback  = fvgLookback;
      m_obLookback   = obLookback;
      m_proxPct      = proxPct;
      return true;
     }

   SSmcContext Analyze()
     {
      SSmcContext ctx;
      ZeroMemory(ctx);

      double curPrice = iClose(m_symbol, m_tf, 1);
      double atr      = iATR(m_symbol, m_tf, 14, 1);
      if(atr <= 0) atr = curPrice * 0.001;

      // BOS
      bool bosB = IsBullBos(m_swingLookback);
      bool bosS = IsBearBos(m_swingLookback);
      ctx.bos = bosB ? SMC_BULLISH : (bosS ? SMC_BEARISH : SMC_NEUTRAL);

      // CHOCH: BOS contrario al bias previo de estructura
      // Simplificado: detectar si hay BOS alcista Y BOS bajista en el lookback
      bool prevBosB = IsBullBos(m_swingLookback * 2);
      bool prevBosS = IsBearBos(m_swingLookback * 2);
      if(bosB && prevBosS) ctx.choch = SMC_BULLISH;
      else if(bosS && prevBosB) ctx.choch = SMC_BEARISH;
      else ctx.choch = SMC_NEUTRAL;

      // FVGs
      SFvgZone bullFvg, bearFvg;
      ZeroMemory(bullFvg); ZeroMemory(bearFvg);
      if(GetBullFvg(m_fvgLookback, bullFvg) && NearZone(curPrice, bullFvg.high, bullFvg.low, atr))
        {
         ctx.hasBullFvg  = true;
         ctx.bullFvgHigh = bullFvg.high;
         ctx.bullFvgLow  = bullFvg.low;
        }
      if(GetBearFvg(m_fvgLookback, bearFvg) && NearZone(curPrice, bearFvg.high, bearFvg.low, atr))
        {
         ctx.hasBearFvg  = true;
         ctx.bearFvgHigh = bearFvg.high;
         ctx.bearFvgLow  = bearFvg.low;
        }

      // Order Blocks
      SOrderBlock bullOb, bearOb;
      ZeroMemory(bullOb); ZeroMemory(bearOb);
      if(GetBullOb(m_obLookback, bullOb) && NearZone(curPrice, bullOb.high, bullOb.low, atr))
        {
         ctx.hasBullOb  = true;
         ctx.bullObHigh = bullOb.high;
         ctx.bullObLow  = bullOb.low;
        }
      if(GetBearOb(m_obLookback, bearOb) && NearZone(curPrice, bearOb.high, bearOb.low, atr))
        {
         ctx.hasBearOb  = true;
         ctx.bearObHigh = bearOb.high;
         ctx.bearObLow  = bearOb.low;
        }

      // Liquidity Sweep
      ctx.liquiditySweep = IsBullLiqSweep(m_swingLookback) ||
                           IsBearLiqSweep(m_swingLookback);

      return ctx;
     }

   // Score SMC 0-30 según contexto y dirección de la operación prevista
   int SmcScore(const SSmcContext &ctx, bool isBuy)
     {
      int score = 0;

      // BOS alineado: +12
      if(isBuy  && ctx.bos == SMC_BULLISH) score += 12;
      if(!isBuy && ctx.bos == SMC_BEARISH) score += 12;

      // CHOCH (mayor calidad de señal): +5
      if(isBuy  && ctx.choch == SMC_BULLISH) score += 5;
      if(!isBuy && ctx.choch == SMC_BEARISH) score += 5;

      // FVG cercano alineado: +8
      if(isBuy  && ctx.hasBullFvg) score += 8;
      if(!isBuy && ctx.hasBearFvg) score += 8;

      // Order Block cercano alineado: +8
      if(isBuy  && ctx.hasBullOb) score += 8;
      if(!isBuy && ctx.hasBearOb) score += 8;

      // Liquidity sweep reciente (confirmación de reversión): +5
      if(ctx.liquiditySweep) score += 5;

      return MathMin(score, 30);
     }
  };
//+------------------------------------------------------------------+
