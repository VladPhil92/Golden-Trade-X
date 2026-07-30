//+------------------------------------------------------------------+
//|                                           ConfidenceEngine.mqh  |
//|   Golden Trade X v2.10 — Motor de confianza (Ensemble Score)    |
//+------------------------------------------------------------------+
//  Combina todas las fuentes de señal en un score 0-100:
//
//    Señal base EMA+RSI           0-25
//    Régimen de mercado           0-25
//    Smart Money Concepts (SMC)   0-30
//    Alineación HTF (H4)          0-15
//    Confluencia Fibonacci        0-5
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
   int   fibBonus;     // confluencia Fibonacci (reemplaza atrBonus v2.10)
   bool  isBuy;        // dirección neta
   bool  isSell;
  };

class CConfidenceEngine
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_tf;
   int             m_hHtfEma;  // EMA H4 para bonus HTF
   bool            m_useHtf;

   bool CopyOne(int handle, int bufIdx, int shift, double &val)
     {
      double buf[1];
      if(CopyBuffer(handle, bufIdx, shift, 1, buf) != 1) return false;
      val = buf[0];
      return true;
     }

public:
   bool Init(string symbol, ENUM_TIMEFRAMES tf,
             bool useHtf = true, int htfEmaPeriod = 50)
     {
      m_symbol  = symbol;
      m_tf      = tf;
      m_useHtf  = useHtf;
      m_hHtfEma = INVALID_HANDLE;

      if(m_useHtf)
        {
         m_hHtfEma = iMA(symbol, PERIOD_H4, htfEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
         if(m_hHtfEma == INVALID_HANDLE) return false;
        }
      return true;
     }

   void Release()
     {
      if(m_hHtfEma != INVALID_HANDLE) IndicatorRelease(m_hHtfEma);
     }

   // ──────────────────────────────────────────────────────────────────
   // Compute: calcula el score completo
   // Parámetros:
   //   hasBaseSignal  — el motor de señal EMA+RSI emitió señal
   //   isBuySignal    — dirección de la señal base
   //   regimeScore    — CMarketRegimeEngine.RegimeScore(isBuy)
   //   smcScore       — CSmartMoneyEngine.SmcScore(ctx, isBuy)
   //   fibScore       — CFibonacciEngine.FibScore(ctx, isBuy)  [0-20]
   // ──────────────────────────────────────────────────────────────────
   SConfidenceResult Compute(bool hasBaseSignal, bool isBuySignal,
                             int regimeScore, int smcScore, int fibScore = 0)
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

      // Componente 4: alineación HTF H4 (0-15).
      // v2.50: bonus GRADUADO. Con el filtro HTF duro activo en SignalEngine,
      // toda señal que llega aquí ya está alineada con H4 — un bonus fijo de
      // 15 era una constante sin poder discriminante. Ahora:
      //   15 = alineado Y la EMA H4 tiene pendiente en la dirección del trade
      //    8 = alineado pero la EMA H4 está plana o en contra (tendencia débil)
      //    0 = contra-tendencia H4
      r.htfBonus = 0;
      if(m_useHtf && m_hHtfEma != INVALID_HANDLE)
        {
         double htfEma1;
         double htfClose = iClose(m_symbol, PERIOD_H4, 1);
         if(CopyOne(m_hHtfEma, 0, 1, htfEma1) && htfClose > 0)
           {
            bool htfBull  = (htfClose > htfEma1);
            bool aligned  = (isBuySignal && htfBull) || (!isBuySignal && !htfBull);
            if(aligned)
              {
               r.htfBonus = 8;
               double htfEma5;
               if(CopyOne(m_hHtfEma, 0, 5, htfEma5))
                 {
                  bool slopeAligned = isBuySignal ? (htfEma1 > htfEma5)
                                                  : (htfEma1 < htfEma5);
                  if(slopeAligned) r.htfBonus = 15;
                 }
              }
           }
        }
      else
        {
         r.htfBonus = 8;  // sin filtro HTF: puntuación neutra
        }

      // Componente 5: confluencia Fibonacci (0-5)
      // FibScore 0-20 → fibBonus 0-5 (escala: /4, máx 5)
      r.fibBonus = MathMin(fibScore / 4, 5);

      r.total = r.baseSignal + r.regimeBonus + r.smcBonus + r.htfBonus + r.fibBonus;
      r.total = MathMin(r.total, 100);

      return r;
     }
  };
//+------------------------------------------------------------------+
