//+------------------------------------------------------------------+
//|                              PortfolioCorrelationGovernor.mqh    |
//| Golden Trade X v3.1 — deterministic exposure guard              |
//+------------------------------------------------------------------+
#property strict

#ifndef GOLDENTRADEX_PORTFOLIO_CORRELATION_GOVERNOR_MQH
#define GOLDENTRADEX_PORTFOLIO_CORRELATION_GOVERNOR_MQH

class CPortfolioCorrelationGovernor
  {
private:
   double m_maxPortfolioRiskPct;
   double m_maxAlignedCorrelation;

public:
   CPortfolioCorrelationGovernor()
     {
      m_maxPortfolioRiskPct = 1.5;
      m_maxAlignedCorrelation = 0.80;
     }

   void Init(const double maxPortfolioRiskPct,
             const double maxAlignedCorrelation)
     {
      m_maxPortfolioRiskPct = MathMax(0.0, maxPortfolioRiskPct);
      m_maxAlignedCorrelation = MathMax(0.0, MathMin(1.0, maxAlignedCorrelation));
     }

   double Pearson(const double &left[],
                  const double &right[],
                  const int count) const
     {
      const int n = MathMin(count, MathMin(ArraySize(left), ArraySize(right)));
      if(n < 3) return 0.0;

      double meanLeft = 0.0;
      double meanRight = 0.0;
      for(int i = 0; i < n; i++)
        {
         meanLeft += left[i];
         meanRight += right[i];
        }
      meanLeft /= n;
      meanRight /= n;

      double numerator = 0.0;
      double sumLeft = 0.0;
      double sumRight = 0.0;
      for(int i = 0; i < n; i++)
        {
         const double dl = left[i] - meanLeft;
         const double dr = right[i] - meanRight;
         numerator += dl * dr;
         sumLeft += dl * dl;
         sumRight += dr * dr;
        }

      if(sumLeft <= 0.0 || sumRight <= 0.0) return 0.0;
      return numerator / MathSqrt(sumLeft * sumRight);
     }

   double AlignedExposureCorrelation(const double correlation,
                                     const int candidateDirection,
                                     const int existingDirection) const
     {
      if((candidateDirection != 1 && candidateDirection != -1) ||
         (existingDirection != 1 && existingDirection != -1))
         return 1.0; // fail closed for invalid direction
      return correlation * candidateDirection * existingDirection;
     }

   bool AllowsRiskBudget(const double currentOpenRiskPct,
                         const double candidateRiskPct,
                         string &reason) const
     {
      reason = "";
      if(currentOpenRiskPct < 0.0 || candidateRiskPct <= 0.0)
        {
         reason = "RISK_INPUT_INVALID";
         return false;
        }
      if(currentOpenRiskPct + candidateRiskPct > m_maxPortfolioRiskPct + 1e-9)
        {
         reason = "PORTFOLIO_RISK_CAP";
         return false;
        }
      return true;
     }

   bool AllowsPairwiseExposure(const double correlation,
                               const int candidateDirection,
                               const int existingDirection,
                               string &reason) const
     {
      reason = "";
      if(correlation < -1.0 || correlation > 1.0)
        {
         reason = "CORRELATION_INVALID";
         return false;
        }

      const double aligned = AlignedExposureCorrelation(correlation,
                                                         candidateDirection,
                                                         existingDirection);
      if(aligned >= m_maxAlignedCorrelation - 1e-9)
        {
         reason = "ALIGNED_CORRELATION_LIMIT";
         return false;
        }
      return true;
     }
  };

#endif // GOLDENTRADEX_PORTFOLIO_CORRELATION_GOVERNOR_MQH
