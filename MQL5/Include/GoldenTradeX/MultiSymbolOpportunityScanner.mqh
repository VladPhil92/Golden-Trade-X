//+------------------------------------------------------------------+
//|                              MultiSymbolOpportunityScanner.mqh   |
//| Golden Trade X v3.1 — fixed-slot shadow opportunity scanner     |
//+------------------------------------------------------------------+
#property strict

#ifndef GOLDENTRADEX_MULTI_SYMBOL_OPPORTUNITY_SCANNER_MQH
#define GOLDENTRADEX_MULTI_SYMBOL_OPPORTUNITY_SCANNER_MQH

#include <GoldenTradeX/SetupAAdapter.mqh>
#include <GoldenTradeX/OpportunityRanker.mqh>

#define GTX_MAX_OPPORTUNITY_SYMBOLS 3

class CMultiSymbolOpportunityScanner
  {
private:
   CSetupAAdapter m_slot0;
   CSetupAAdapter m_slot1;
   CSetupAAdapter m_slot2;
   SSetupAEvaluation m_eval0;
   SSetupAEvaluation m_eval1;
   SSetupAEvaluation m_eval2;
   COpportunityRanker m_ranker;
   int m_count;
   bool m_initialized;

   string Trimmed(string value) const
     {
      StringTrimLeft(value);
      StringTrimRight(value);
      return value;
     }

   bool IsDuplicate(const string &symbols[], const int used, const string symbol) const
     {
      for(int i = 0; i < used; i++)
         if(symbols[i] == symbol) return true;
      return false;
     }

   bool InitSlot(const int index, const string symbol, const SSetupAConfig &cfg)
     {
      if(index == 0) return m_slot0.Init(symbol, cfg);
      if(index == 1) return m_slot1.Init(symbol, cfg);
      if(index == 2) return m_slot2.Init(symbol, cfg);
      return false;
     }

   bool EvaluateSlot(const int index, SSetupAEvaluation &evaluation)
     {
      if(index == 0) return m_slot0.Evaluate(evaluation);
      if(index == 1) return m_slot1.Evaluate(evaluation);
      if(index == 2) return m_slot2.Evaluate(evaluation);
      ZeroMemory(evaluation);
      return false;
     }

   void SaveEvaluation(const int index, const SSetupAEvaluation &evaluation)
     {
      if(index == 0) m_eval0 = evaluation;
      else if(index == 1) m_eval1 = evaluation;
      else if(index == 2) m_eval2 = evaluation;
     }

public:
   CMultiSymbolOpportunityScanner()
     {
      m_count = 0;
      m_initialized = false;
      ZeroMemory(m_eval0);
      ZeroMemory(m_eval1);
      ZeroMemory(m_eval2);
     }

   bool Init(const string symbolCsv,
             const SSetupAConfig &cfg,
             const int minConfidence,
             const double minQualityScore,
             const double maxCandidateRiskPct,
             string &reason)
     {
      Release();
      reason = "";

      string raw[];
      const ushort separator = (ushort)StringGetCharacter(",", 0);
      const int parts = StringSplit(symbolCsv, separator, raw);
      if(parts <= 0)
        {
         reason = "SYMBOL_UNIVERSE_EMPTY";
         return false;
        }
      if(parts > GTX_MAX_OPPORTUNITY_SYMBOLS)
        {
         reason = "SYMBOL_UNIVERSE_TOO_LARGE";
         return false;
        }

      string symbols[];
      ArrayResize(symbols, GTX_MAX_OPPORTUNITY_SYMBOLS);
      int used = 0;
      for(int i = 0; i < parts; i++)
        {
         string symbol = Trimmed(raw[i]);
         if(StringLen(symbol) == 0)
           {
            reason = "SYMBOL_EMPTY";
            return false;
           }
         if(IsDuplicate(symbols, used, symbol))
           {
            reason = "SYMBOL_DUPLICATE";
            return false;
           }
         symbols[used++] = symbol;
        }

      for(int i = 0; i < used; i++)
        {
         if(!InitSlot(i, symbols[i], cfg))
           {
            reason = "SYMBOL_INIT_FAILED:" + symbols[i];
            Release();
            return false;
           }
        }

      m_ranker.Init(minConfidence, minQualityScore, maxCandidateRiskPct);
      m_count = used;
      m_initialized = true;
      return true;
     }

   void Release()
     {
      m_slot0.Release();
      m_slot1.Release();
      m_slot2.Release();
      m_count = 0;
      m_initialized = false;
      ZeroMemory(m_eval0);
      ZeroMemory(m_eval1);
      ZeroMemory(m_eval2);
     }

   int Count() const { return m_count; }
   bool IsInitialized() const { return m_initialized; }

   SSetupAEvaluation Evaluation(const int index) const
     {
      if(index == 0) return m_eval0;
      if(index == 1) return m_eval1;
      if(index == 2) return m_eval2;
      SSetupAEvaluation empty;
      ZeroMemory(empty);
      return empty;
     }

   int Scan(string &reason)
     {
      reason = "SCANNER_NOT_INITIALIZED";
      if(!m_initialized || m_count <= 0) return -1;

      SOpportunityCandidate candidates[];
      ArrayResize(candidates, m_count);
      for(int i = 0; i < m_count; i++)
        {
         SSetupAEvaluation evaluation;
         ZeroMemory(evaluation);
         EvaluateSlot(i, evaluation);
         SaveEvaluation(i, evaluation);
         candidates[i] = evaluation.candidate;
        }

      return m_ranker.SelectBest(candidates, reason);
     }
  };

#endif // GOLDENTRADEX_MULTI_SYMBOL_OPPORTUNITY_SCANNER_MQH
