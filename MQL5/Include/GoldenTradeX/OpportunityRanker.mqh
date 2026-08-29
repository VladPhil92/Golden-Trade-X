//+------------------------------------------------------------------+
//|                                      OpportunityRanker.mqh       |
//| Golden Trade X v3.1 — research-first opportunity ranking        |
//+------------------------------------------------------------------+
#property strict

#ifndef GOLDENTRADEX_OPPORTUNITY_RANKER_MQH
#define GOLDENTRADEX_OPPORTUNITY_RANKER_MQH

enum ENUM_GTX_SETUP_CLASS
  {
   GTX_SETUP_NONE = 0,
   GTX_SETUP_A_HIGH_CONVICTION = 1,
   GTX_SETUP_B_STANDARD_INTRADAY = 2,
   GTX_SETUP_C_TACTICAL = 3
  };

struct SOpportunityCandidate
  {
   string               symbol;
   ENUM_GTX_SETUP_CLASS setupClass;
   int                  direction;      // +1 BUY, -1 SELL
   int                  confidence;     // 0..100
   double               qualityScore;   // ex-ante score from setup engine
   double               proposedRiskPct;
   bool                 sourceValid;
   string               sourceReason;
  };

class COpportunityRanker
  {
private:
   int    m_minConfidence;
   double m_minQualityScore;
   double m_maxCandidateRiskPct;

public:
   COpportunityRanker()
     {
      m_minConfidence = 0;
      m_minQualityScore = 0.0;
      m_maxCandidateRiskPct = 1.0;
     }

   void Init(const int minConfidence,
             const double minQualityScore,
             const double maxCandidateRiskPct)
     {
      m_minConfidence = MathMax(0, MathMin(100, minConfidence));
      m_minQualityScore = minQualityScore;
      m_maxCandidateRiskPct = MathMax(0.0, maxCandidateRiskPct);
     }

   bool IsEligible(const SOpportunityCandidate &candidate,
                   string &reason) const
     {
      reason = "";
      if(!candidate.sourceValid)
        {
         reason = StringLen(candidate.sourceReason) > 0 ? candidate.sourceReason : "SOURCE_INVALID";
         return false;
        }
      if(StringLen(candidate.symbol) == 0)
        {
         reason = "SYMBOL_EMPTY";
         return false;
        }
      if(candidate.direction != 1 && candidate.direction != -1)
        {
         reason = "DIRECTION_INVALID";
         return false;
        }
      if(candidate.setupClass == GTX_SETUP_NONE)
        {
         reason = "SETUP_NONE";
         return false;
        }
      if(candidate.confidence < m_minConfidence)
        {
         reason = "CONFIDENCE_TOO_LOW";
         return false;
        }
      if(candidate.qualityScore < m_minQualityScore)
        {
         reason = "QUALITY_TOO_LOW";
         return false;
        }
      if(candidate.proposedRiskPct <= 0.0 || candidate.proposedRiskPct > m_maxCandidateRiskPct)
        {
         reason = "RISK_OUT_OF_RANGE";
         return false;
        }
      return true;
     }

   bool BetterThan(const SOpportunityCandidate &left,
                   const SOpportunityCandidate &right) const
     {
      const double eps = 1e-9;
      if(left.qualityScore > right.qualityScore + eps) return true;
      if(right.qualityScore > left.qualityScore + eps) return false;

      if(left.confidence > right.confidence) return true;
      if(right.confidence > left.confidence) return false;

      if(left.proposedRiskPct < right.proposedRiskPct - eps) return true;
      if(right.proposedRiskPct < left.proposedRiskPct - eps) return false;

      if((int)left.setupClass < (int)right.setupClass) return true;
      if((int)right.setupClass < (int)left.setupClass) return false;

      return StringCompare(left.symbol, right.symbol) < 0;
     }

   int SelectBest(SOpportunityCandidate &candidates[],
                  string &reason) const
     {
      reason = "NO_ELIGIBLE_OPPORTUNITY";
      int best = -1;
      const int total = ArraySize(candidates);
      for(int i = 0; i < total; i++)
        {
         string candidateReason = "";
         if(!IsEligible(candidates[i], candidateReason))
            continue;
         if(best < 0 || BetterThan(candidates[i], candidates[best]))
            best = i;
        }

      if(best >= 0)
         reason = "SELECTED_BY_PRE_REGISTERED_QUALITY";
      return best;
     }
  };

#endif // GOLDENTRADEX_OPPORTUNITY_RANKER_MQH
