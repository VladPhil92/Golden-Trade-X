//+------------------------------------------------------------------+
//|                                     TestOpportunityRanker.mq5    |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <GoldenTradeX/OpportunityRanker.mqh>

int g_pass = 0;
int g_fail = 0;

void AssertTrue(bool condition, string label)
  {
   if(condition) { g_pass++; Print("  PASS  ", label); }
   else          { g_fail++; Print("  FAIL  ", label); }
  }

SOpportunityCandidate Candidate(string symbol,
                                ENUM_GTX_SETUP_CLASS setupClass,
                                int direction,
                                int confidence,
                                double quality,
                                double riskPct,
                                bool valid=true)
  {
   SOpportunityCandidate c;
   c.symbol = symbol;
   c.setupClass = setupClass;
   c.direction = direction;
   c.confidence = confidence;
   c.qualityScore = quality;
   c.proposedRiskPct = riskPct;
   c.sourceValid = valid;
   c.sourceReason = valid ? "" : "SOURCE_INVALID_TEST";
   return c;
  }

void OnStart()
  {
   Print("=== TestOpportunityRanker BEGIN ===");

   COpportunityRanker ranker;
   ranker.Init(55, 60.0, 1.0);

   SOpportunityCandidate candidates[];
   ArrayResize(candidates, 3);
   candidates[0] = Candidate("XAUUSD", GTX_SETUP_A_HIGH_CONVICTION, 1, 70, 75.0, 1.0);
   candidates[1] = Candidate("EURUSD", GTX_SETUP_B_STANDARD_INTRADAY, -1, 72, 82.0, 0.5);
   candidates[2] = Candidate("GBPUSD", GTX_SETUP_C_TACTICAL, 1, 80, 58.0, 0.25);

   string reason = "";
   int best = ranker.SelectBest(candidates, reason);
   AssertTrue(best == 1, "Highest eligible quality score is selected");
   AssertTrue(reason == "SELECTED_BY_PRE_REGISTERED_QUALITY", "Selection reason is explicit");

   candidates[0].confidence = 20;
   candidates[1].confidence = 20;
   candidates[2].confidence = 20;
   best = ranker.SelectBest(candidates, reason);
   AssertTrue(best == -1, "No candidate means no trade instead of forced trade");
   AssertTrue(reason == "NO_ELIGIBLE_OPPORTUNITY", "No-trade state is explicit");

   SOpportunityCandidate invalidRisk = Candidate("XAGUSD", GTX_SETUP_B_STANDARD_INTRADAY, 1, 75, 80.0, 1.25);
   string rejection = "";
   AssertTrue(!ranker.IsEligible(invalidRisk, rejection), "Candidate above risk budget is rejected");
   AssertTrue(rejection == "RISK_OUT_OF_RANGE", "Risk rejection is attributable");

   SOpportunityCandidate a = Candidate("XAUUSD", GTX_SETUP_A_HIGH_CONVICTION, 1, 70, 80.0, 0.75);
   SOpportunityCandidate b = Candidate("EURUSD", GTX_SETUP_B_STANDARD_INTRADAY, 1, 70, 80.0, 0.50);
   AssertTrue(ranker.BetterThan(b, a), "Lower risk breaks an exact quality/confidence tie");

   SOpportunityCandidate invalidSource = Candidate("USDJPY", GTX_SETUP_A_HIGH_CONVICTION, -1, 90, 95.0, 0.5, false);
   AssertTrue(!ranker.IsEligible(invalidSource, rejection), "Invalid source never enters ranking");
   AssertTrue(rejection == "SOURCE_INVALID_TEST", "Source rejection reason is preserved");

   Print("=== TestOpportunityRanker END | PASS=", g_pass, " FAIL=", g_fail, " ===");
  }
