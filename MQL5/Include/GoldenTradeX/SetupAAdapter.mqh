//+------------------------------------------------------------------+
//|                                           SetupAAdapter.mqh      |
//| Golden Trade X v3.1 — baseline Setup A adapter                  |
//+------------------------------------------------------------------+
#property strict

#ifndef GOLDENTRADEX_SETUP_A_ADAPTER_MQH
#define GOLDENTRADEX_SETUP_A_ADAPTER_MQH

#include <GoldenTradeX/SignalEngine.mqh>
#include <GoldenTradeX/MarketRegimeEngine.mqh>
#include <GoldenTradeX/SmartMoneyEngine.mqh>
#include <GoldenTradeX/ConfidenceEngine.mqh>
#include <GoldenTradeX/FibonacciEngine.mqh>
#include <GoldenTradeX/OpportunityRanker.mqh>

struct SSetupAConfig
  {
   ENUM_TIMEFRAMES timeframe;
   int emaFast;
   int emaSlow;
   int rsiPeriod;
   double rsiUpper;
   double rsiLower;
   double rsiLongMin;
   double rsiShortMax;
   int atrPeriod;
   double atrMinRatio;
   double atrMaxRatio;
   int adxPeriod;
   double adxMinLevel;
   long minTickVolume;
   bool useHtfFilter;
   int htfEmaPeriod;
   bool useRegimeFilter;
   bool useSmcFilter;
   int weightBase;
   int weightRegime;
   int weightSmc;
   int weightHtf;
   int weightFib;
   double proposedRiskPct;
  };

struct SSetupAEvaluation
  {
   SOpportunityCandidate candidate;
   ENUM_MARKET_REGIME regime;
   int baseSignalScore;
   int regimeScore;
   int smcScore;
   int htfScore;
   int fibScore;
   double atr;
   datetime barTime;
  };

class CSetupAAdapter
  {
private:
   string m_symbol;
   SSetupAConfig m_cfg;
   CSignalEngine m_signal;
   CMarketRegimeEngine m_regime;
   CSmartMoneyEngine m_smc;
   CConfidenceEngine m_confidence;
   CFibonacciEngine m_fib;
   bool m_initialized;

public:
   CSetupAAdapter()
     {
      m_symbol = "";
      m_initialized = false;
      ZeroMemory(m_cfg);
     }

   bool Init(const string symbol, const SSetupAConfig &cfg)
     {
      Release();
      if(StringLen(symbol) == 0) return false;
      if(!SymbolSelect(symbol, true)) return false;

      m_symbol = symbol;
      m_cfg = cfg;

      if(!m_signal.Init(symbol, cfg.timeframe,
                        cfg.emaFast, cfg.emaSlow,
                        cfg.rsiPeriod, cfg.rsiUpper, cfg.rsiLower,
                        cfg.rsiLongMin, cfg.rsiShortMax,
                        cfg.atrPeriod, cfg.atrMinRatio,
                        cfg.adxMinLevel, cfg.atrMaxRatio,
                        cfg.useHtfFilter, cfg.htfEmaPeriod,
                        cfg.minTickVolume, cfg.adxPeriod))
         return false;

      if(cfg.useRegimeFilter &&
         !m_regime.Init(symbol, cfg.timeframe, cfg.emaFast, cfg.emaSlow,
                        25.0, 20.0, 2.0, 0.70, cfg.atrPeriod, cfg.adxPeriod))
        {
         m_signal.Release();
         return false;
        }

      if(cfg.useSmcFilter &&
         !m_smc.Init(symbol, cfg.timeframe, 50, 20, 40, 1.0, cfg.atrPeriod))
        {
         m_signal.Release();
         if(cfg.useRegimeFilter) m_regime.Release();
         return false;
        }

      if(!m_confidence.Init(symbol, cfg.timeframe,
                            cfg.useHtfFilter, cfg.htfEmaPeriod,
                            cfg.weightBase, cfg.weightRegime, cfg.weightSmc,
                            cfg.weightHtf, cfg.weightFib))
        {
         m_signal.Release();
         if(cfg.useRegimeFilter) m_regime.Release();
         if(cfg.useSmcFilter) m_smc.Release();
         return false;
        }

      if(!m_fib.Init(symbol, cfg.timeframe, 100, 0.5, cfg.atrPeriod))
        {
         m_signal.Release();
         if(cfg.useRegimeFilter) m_regime.Release();
         if(cfg.useSmcFilter) m_smc.Release();
         m_confidence.Release();
         return false;
        }

      m_initialized = true;
      return true;
     }

   void Release()
     {
      if(m_initialized)
        {
         m_signal.Release();
         if(m_cfg.useRegimeFilter) m_regime.Release();
         if(m_cfg.useSmcFilter) m_smc.Release();
         m_confidence.Release();
         m_fib.Release();
        }
      m_initialized = false;
      m_symbol = "";
     }

   bool IsInitialized() const { return m_initialized; }
   string Symbol() const { return m_symbol; }

   bool Evaluate(SSetupAEvaluation &out)
     {
      ZeroMemory(out);
      out.candidate.symbol = m_symbol;
      out.candidate.setupClass = GTX_SETUP_A_HIGH_CONVICTION;
      out.candidate.proposedRiskPct = m_cfg.proposedRiskPct;
      out.candidate.sourceValid = false;
      out.candidate.sourceReason = "NOT_INITIALIZED";

      if(!m_initialized) return false;

      out.barTime = iTime(m_symbol, m_cfg.timeframe, 0);
      if(out.barTime <= 0)
        {
         out.candidate.sourceReason = "BAR_TIME_UNAVAILABLE";
         return false;
        }

      ENUM_MARKET_REGIME regime = REGIME_UNKNOWN;
      if(m_cfg.useRegimeFilter)
        {
         regime = m_regime.Detect();
         if(regime == REGIME_VOLATILE)
           {
            out.regime = regime;
            out.candidate.sourceReason = "REGIME_VOLATILE";
            return false;
           }
        }
      out.regime = regime;

      ENUM_SIGNAL signal = m_signal.GetSignal();
      if(signal == SIGNAL_NONE)
        {
         out.candidate.sourceReason = "SIGNAL_NONE";
         return false;
        }

      const bool isBuy = signal == SIGNAL_BUY;
      out.candidate.direction = isBuy ? 1 : -1;
      const int regScore = m_cfg.useRegimeFilter ? m_regime.RegimeScore(isBuy) : 15;
      int smcScore = 0;
      if(m_cfg.useSmcFilter)
        {
         SSmcContext smcCtx = m_smc.Analyze();
         smcScore = m_smc.SmcScore(smcCtx, isBuy);
        }
      SFibContext fibCtx = m_fib.Analyze();
      const int fibScore = m_fib.FibScore(fibCtx, isBuy);
      SConfidenceResult conf = m_confidence.Compute(true, isBuy, regScore, smcScore, fibScore);

      out.baseSignalScore = conf.baseSignal;
      out.regimeScore = conf.regimeBonus;
      out.smcScore = conf.smcBonus;
      out.htfScore = conf.htfBonus;
      out.fibScore = conf.fibBonus;
      out.atr = m_signal.GetATR();
      out.candidate.confidence = conf.total;
      out.candidate.qualityScore = (double)conf.total;
      out.candidate.sourceValid = out.atr > 0.0;
      out.candidate.sourceReason = out.candidate.sourceValid ? "" : "ATR_INVALID";
      return out.candidate.sourceValid;
     }
  };

#endif // GOLDENTRADEX_SETUP_A_ADAPTER_MQH
