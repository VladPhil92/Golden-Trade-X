//+------------------------------------------------------------------+
//|                          GoldenTradeXOpportunityShadow.mq5       |
//| Golden Trade X v3.1 — research-only multi-symbol shadow EA      |
//+------------------------------------------------------------------+
#property copyright "CTG One Technology S.A.S."
#property strict
#property description "Research-only v3.1 opportunity scanner. Never sends orders."

#include <GoldenTradeX/MultiSymbolOpportunityScanner.mqh>
#include <GoldenTradeX/OpportunityTelemetry.mqh>

input group "=== v3.1 Shadow Research ==="
input bool   InpEnableOpportunityShadow = false;
input string InpOpportunitySymbols      = "XAUUSD,XAGUSD,EURUSD";
input ulong  InpOpportunityMagic        = 931100;
input bool   InpEnableOpportunityTelemetry = true;
input double InpOpportunityMinQuality   = 55.0;
input double InpOpportunityRiskPct      = 1.0;

input group "=== Setup A Baseline ==="
input int     InpEmaFast          = 21;
input int     InpEmaSlow          = 55;
input int     InpRsiPeriod        = 14;
input double  InpRsiUpper         = 70.0;
input double  InpRsiLower         = 30.0;
input double  InpRsiLongMin       = 45.0;
input double  InpRsiShortMax      = 55.0;
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_M15;
input int     InpAtrPeriod        = 14;
input double  InpAtrMinRatio      = 0.8;
input double  InpAtrMaxRatio      = 3.0;
input int     InpAdxPeriod        = 14;
input double  InpAdxMinLevel      = 25.0;
input int     InpMinTickVolume    = 10;
input bool    InpUseHtfFilter     = true;
input int     InpHtfEmaPeriod     = 50;
input bool    InpUseRegimeFilter  = true;
input bool    InpUseSmcFilter     = true;
input int     InpMinConfidence    = 55;
input int     InpConfWeightBase   = 25;
input int     InpConfWeightRegime = 25;
input int     InpConfWeightSmc    = 30;
input int     InpConfWeightHtf    = 15;
input int     InpConfWeightFib    = 5;

CMultiSymbolOpportunityScanner g_scanner;
COpportunityTelemetry g_opportunityTelemetry;
long g_lastBucket = -1;

SSetupAConfig BuildSetupAConfig()
  {
   SSetupAConfig cfg;
   ZeroMemory(cfg);
   cfg.timeframe = InpTimeframe;
   cfg.emaFast = InpEmaFast;
   cfg.emaSlow = InpEmaSlow;
   cfg.rsiPeriod = InpRsiPeriod;
   cfg.rsiUpper = InpRsiUpper;
   cfg.rsiLower = InpRsiLower;
   cfg.rsiLongMin = InpRsiLongMin;
   cfg.rsiShortMax = InpRsiShortMax;
   cfg.atrPeriod = InpAtrPeriod;
   cfg.atrMinRatio = InpAtrMinRatio;
   cfg.atrMaxRatio = InpAtrMaxRatio;
   cfg.adxPeriod = InpAdxPeriod;
   cfg.adxMinLevel = InpAdxMinLevel;
   cfg.minTickVolume = InpMinTickVolume;
   cfg.useHtfFilter = InpUseHtfFilter;
   cfg.htfEmaPeriod = InpHtfEmaPeriod;
   cfg.useRegimeFilter = InpUseRegimeFilter;
   cfg.useSmcFilter = InpUseSmcFilter;
   cfg.weightBase = InpConfWeightBase;
   cfg.weightRegime = InpConfWeightRegime;
   cfg.weightSmc = InpConfWeightSmc;
   cfg.weightHtf = InpConfWeightHtf;
   cfg.weightFib = InpConfWeightFib;
   cfg.proposedRiskPct = InpOpportunityRiskPct;
   return cfg;
  }

int OnInit()
  {
   if(!InpEnableOpportunityShadow)
     {
      Print("GoldenTradeX v3.1 shadow scanner is disabled. No trading path is altered.");
      return INIT_SUCCEEDED;
     }
   if(InpEmaFast >= InpEmaSlow || InpMinConfidence < 0 || InpMinConfidence > 100 ||
      InpOpportunityRiskPct <= 0.0 || InpOpportunityRiskPct > 1.0)
      return INIT_PARAMETERS_INCORRECT;

   SSetupAConfig cfg = BuildSetupAConfig();
   string reason = "";
   if(!g_scanner.Init(InpOpportunitySymbols, cfg,
                      InpMinConfidence, InpOpportunityMinQuality,
                      InpOpportunityRiskPct, reason))
     {
      Print("GoldenTradeX v3.1 shadow init failed: ", reason);
      return INIT_FAILED;
     }

   g_opportunityTelemetry.Init(InpEnableOpportunityTelemetry, InpOpportunityMagic);
   EventSetTimer(1);
   Print("GoldenTradeX v3.1 shadow scanner initialized. symbols=", g_scanner.Count(),
         " research-only; order execution disabled by design.");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   g_scanner.Release();
  }

void OnTimer()
  {
   if(!InpEnableOpportunityShadow || !g_scanner.IsInitialized()) return;
   const int seconds = PeriodSeconds(InpTimeframe);
   if(seconds <= 0) return;
   datetime now = TimeCurrent();
   if(now <= 0) return;
   const long bucket = ((long)now) / seconds;
   if(bucket == g_lastBucket) return;
   g_lastBucket = bucket;

   string reason = "";
   const int selected = g_scanner.Scan(reason);
   for(int i = 0; i < g_scanner.Count(); i++)
     {
      SSetupAEvaluation evaluation = g_scanner.Evaluation(i);
      if(!g_opportunityTelemetry.Log(evaluation, i == selected, reason))
         Print("GoldenTradeX v3.1 shadow telemetry write failed for ", evaluation.candidate.symbol);
     }

   if(selected >= 0)
     {
      SSetupAEvaluation best = g_scanner.Evaluation(selected);
      Print("GTX_SHADOW_SELECTED symbol=", best.candidate.symbol,
            " direction=", best.candidate.direction,
            " confidence=", best.candidate.confidence,
            " setup=A risk_pct=", DoubleToString(best.candidate.proposedRiskPct, 2),
            " — NO ORDER SENT");
     }
   else
      Print("GTX_SHADOW_NO_OPPORTUNITY reason=", reason, " — NO ORDER SENT");
  }
