//+------------------------------------------------------------------+
//|                                           ConfidenceEngine.mqh  |
//|   Golden Trade X v2.60 — Puntaje de confianza por confluencia   |
//+------------------------------------------------------------------+
//  Combina todas las fuentes de señal en un score heurístico 0-100
//  (pesos por defecto, configurables desde v2.60):
//
//    Señal base EMA+RSI           0-25
//    Régimen de mercado           0-25
//    Smart Money Concepts (SMC)   0-30
//    Alineación HTF (H4)          0-15
//    Confluencia Fibonacci        0-5
//    ─────────────────────────────────
//    TOTAL                        0-100
//
//  IMPORTANTE: esto es un "confluence score" heurístico, NO un ensemble
//  estadístico calibrado. Los pesos fueron elegidos a mano, no ajustados
//  con datos — no existe evidencia de que 30 pts de SMC valgan el doble
//  que 15 de HTF, ni de que un score de 70 corresponda a una probabilidad
//  determinada de éxito. Los pesos son inputs del EA (InpConfWeight*)
//  precisamente para que puedan optimizarse con datos reales via
//  Strategy Tester una vez exista historial suficiente — no asumir que
//  los valores por defecto están calibrados.
//
//  Solo ejecutar operaciones cuando score >= InpMinConfidence.
//  Umbral recomendado: 55 (calidad media), 70 (alta calidad) — sin
//  validar empíricamente, ver scripts/walk_forward_optimizer.py.
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

   // v2.60: pesos configurables. Los sub-scores de cada motor tienen una
   // escala INTERNA fija (regimeScore 0-25, smcScore 0-30, htf 0/8/15,
   // fibScore/4 → 0-5) — el peso reescala proporcionalmente esa escala
   // interna, no la trunca. Con los defaults (25/25/30/15/5) el factor de
   // escala es 1.0 en todos los componentes → comportamiento idéntico a
   // versiones previas.
   int             m_wBase, m_wRegime, m_wSmc, m_wHtf, m_wFib;

   bool CopyOne(int handle, int bufIdx, int shift, double &val)
     {
      double buf[1];
      if(CopyBuffer(handle, bufIdx, shift, 1, buf) != 1) return false;
      val = buf[0];
      return true;
     }

public:
   bool Init(string symbol, ENUM_TIMEFRAMES tf,
             bool useHtf = true, int htfEmaPeriod = 50,
             int weightBase = 25, int weightRegime = 25, int weightSmc = 30,
             int weightHtf = 15, int weightFib = 5)
     {
      m_symbol  = symbol;
      m_tf      = tf;
      m_useHtf  = useHtf;
      m_hHtfEma = INVALID_HANDLE;
      m_wBase   = MathMax(0, weightBase);
      m_wRegime = MathMax(0, weightRegime);
      m_wSmc    = MathMax(0, weightSmc);
      m_wHtf    = MathMax(0, weightHtf);
      m_wFib    = MathMax(0, weightFib);

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

      // Componente 1: señal base (peso completo si hay señal)
      r.baseSignal = m_wBase;

      // Componente 2: régimen — escala interna fija 0-25, reescalada al peso
      r.regimeBonus = (int)MathRound(MathMin(regimeScore, 25) * (m_wRegime / 25.0));

      // Componente 3: SMC — escala interna fija 0-30, reescalada al peso
      r.smcBonus = (int)MathRound(MathMin(smcScore, 30) * (m_wSmc / 30.0));

      // Componente 4: alineación HTF H4 — escala interna fija 0-15
      // (v2.50: bonus graduado en vez de constante):
      //   15 = alineado Y la EMA H4 tiene pendiente en la dirección del trade
      //    8 = alineado pero la EMA H4 está plana o en contra (tendencia débil)
      //    0 = contra-tendencia H4
      double htfRaw = 0;
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
               htfRaw = 8;
               double htfEma5;
               if(CopyOne(m_hHtfEma, 0, 5, htfEma5))
                 {
                  bool slopeAligned = isBuySignal ? (htfEma1 > htfEma5)
                                                  : (htfEma1 < htfEma5);
                  if(slopeAligned) htfRaw = 15;
                 }
              }
           }
        }
      else
        {
         htfRaw = 8;  // sin filtro HTF: puntuación neutra
        }
      r.htfBonus = (int)MathRound(htfRaw * (m_wHtf / 15.0));

      // Componente 5: confluencia Fibonacci — escala interna fija 0-5
      // (FibScore 0-20 → /4 → 0-5), reescalada al peso
      double fibRaw = MathMin(fibScore / 4, 5);
      r.fibBonus = (int)MathRound(fibRaw * (m_wFib / 5.0));

      r.total = r.baseSignal + r.regimeBonus + r.smcBonus + r.htfBonus + r.fibBonus;
      r.total = MathMin(r.total, 100);

      return r;
     }
  };
//+------------------------------------------------------------------+
