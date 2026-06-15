//+------------------------------------------------------------------+
//|                                           ConfidenceEngine.mqh  |
//|   Golden Trade X v2.00 — Motor de confianza (Ensemble Score)    |
//+------------------------------------------------------------------+
//  Combina todas las fuentes de señal en un score 0-100:
//
//    Señal base EMA+RSI           0-25
//    Régimen de mercado           0-25
//    Smart Money Concepts (SMC)   0-30
//    Alineación HTF (H4)          0-15
//    Calidad ATR                  0-5
//    ─────────────────────────────────
//    TOTAL                        0-100
//
//  Solo ejecutar operaciones cuando score >= InpMinConfidence.
//  Umbral recomendado: 55 (calidad media), 70 (alta calidad).
//+------------------------------------------------------------------+
#property strict

struct SConfidenceResult
  {
   int   total;        // 0-100
   int   baseSignal;   // componente EMA+RSI
   int   regimeBonus;  // alineación de régimen
   int   smcBonus;     // Smart Money
   int   htfBonus;     // H4 alignment
   int   atrBonus;     // calidad de volatilidad
   bool  isBuy;        // dirección neta
   bool  isSell;
  };

class CConfidenceEngine
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_tf;
   int             m_hHtfEma;  // EMA H4 para bonus HTF
   int             m_hAtr;
   bool            m_useHtf;

   bool CopyOne(int handle, int bufIdx, int shift, double &val)
     {
      double buf[1];
      if(CopyBuffer(handle, bufIdx, shift, 1, buf) != 1) return false;
      val = buf[0];
      return true;
     }

   // Calidad del ATR: penaliza compresión y spikes extremos
   int AtrQualityScore(double atr, double atrSma)
     {
      if(atrSma <= 0) return 2;
      double r = atr / atrSma;
      if(r >= 0.8 && r <= 1.5) return 5;   // volatilidad normal
      if(r >= 0.5 && r <  0.8) return 2;   // compresión leve
      if(r >  1.5 && r <= 2.0) return 3;   // expansión moderada
      return 0;                              // compresión severa o spike
     }

public:
   bool Init(string symbol, ENUM_TIMEFRAMES tf,
             bool useHtf = true, int htfEmaPeriod = 50,
             int atrPeriod = 14)
     {
      m_symbol = symbol;
      m_tf     = tf;
      m_useHtf = useHtf;
      m_hHtfEma = INVALID_HANDLE;

      m_hAtr = iATR(symbol, tf, atrPeriod);
      if(m_hAtr == INVALID_HANDLE) return false;

      if(m_useHtf)
        {
         m_hHtfEma = iMA(symbol, PERIOD_H4, htfEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
         if(m_hHtfEma == INVALID_HANDLE) return false;
        }
      return true;
     }

   void Release()
     {
      if(m_hAtr    != INVALID_HANDLE) IndicatorRelease(m_hAtr);
      if(m_hHtfEma != INVALID_HANDLE) IndicatorRelease(m_hHtfEma);
     }

   // ──────────────────────────────────────────────────────────────────
   // Compute: calcula el score completo
   // Parámetros:
   //   hasBaseSignal  — el motor de señal EMA+RSI emitió señal
   //   isBuySignal    — dirección de la señal base
   //   regimeScore    — CMarketRegimeEngine.RegimeScore(isBuy)
   //   smcScore       — CSmartMoneyEngine.SmcScore(ctx, isBuy)
   // ──────────────────────────────────────────────────────────────────
   SConfidenceResult Compute(bool hasBaseSignal, bool isBuySignal,
                             int regimeScore, int smcScore)
     {
      SConfidenceResult r;
      ZeroMemory(r);

      if(!hasBaseSignal) return r;   // sin señal base → score 0

      r.isBuy  = isBuySignal;
      r.isSell = !isBuySignal;

      // Componente 1: señal base (25 pts máx)
      r.baseSignal = 25;

      // Componente 2: régimen (0-25, ya calculado externamente)
      r.regimeBonus = MathMin(regimeScore, 25);

      // Componente 3: SMC (0-30, ya calculado externamente)
      r.smcBonus = MathMin(smcScore, 30);

      // Componente 4: alineación HTF H4 (0-15)
      r.htfBonus = 0;
      if(m_useHtf && m_hHtfEma != INVALID_HANDLE)
        {
         double htfEma;
         double htfClose = iClose(m_symbol, PERIOD_H4, 1);
         if(CopyOne(m_hHtfEma, 0, 1, htfEma) && htfClose > 0)
           {
            bool htfBull = (htfClose > htfEma);
            if((isBuySignal && htfBull) || (!isBuySignal && !htfBull))
               r.htfBonus = 15;
            // Contra-tendencia HTF: penalización total (bonus = 0)
           }
        }
      else
        {
         r.htfBonus = 8;  // sin filtro HTF: puntuación neutra
        }

      // Componente 5: calidad ATR (0-5)
      double atr, atrSma = 0;
        {
         if(CopyOne(m_hAtr, 0, 1, atr))
           {
            double buf[];
            ArraySetAsSeries(buf, true);
            if(CopyBuffer(m_hAtr, 0, 1, 20, buf) == 20)
              {
               double s = 0;
               for(int i = 0; i < 20; i++) s += buf[i];
               atrSma = s / 20.0;
              }
            r.atrBonus = AtrQualityScore(atr, atrSma);
           }
        }

      r.total = r.baseSignal + r.regimeBonus + r.smcBonus + r.htfBonus + r.atrBonus;
      r.total = MathMin(r.total, 100);

      return r;
     }
  };
//+------------------------------------------------------------------+
