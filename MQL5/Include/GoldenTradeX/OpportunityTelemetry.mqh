//+------------------------------------------------------------------+
//|                                      OpportunityTelemetry.mqh    |
//| Golden Trade X v3.1 — shadow scanner telemetry                  |
//+------------------------------------------------------------------+
#property strict

#ifndef GOLDENTRADEX_OPPORTUNITY_TELEMETRY_MQH
#define GOLDENTRADEX_OPPORTUNITY_TELEMETRY_MQH

#include <GoldenTradeX/SetupAAdapter.mqh>

class COpportunityTelemetry
  {
private:
   bool m_enabled;
   ulong m_magic;

   string SetupText(const ENUM_GTX_SETUP_CLASS setup) const
     {
      if(setup == GTX_SETUP_A_HIGH_CONVICTION) return "A_HIGH_CONVICTION";
      if(setup == GTX_SETUP_B_STANDARD_INTRADAY) return "B_STANDARD_INTRADAY";
      if(setup == GTX_SETUP_C_TACTICAL) return "C_TACTICAL";
      return "NONE";
     }

   string DirectionText(const int direction) const
     {
      if(direction == 1) return "BUY";
      if(direction == -1) return "SELL";
      return "NONE";
     }

   string Sanitize(string value) const
     {
      StringReplace(value, ",", ";");
      StringReplace(value, "\r", " ");
      StringReplace(value, "\n", " ");
      return value;
     }

   bool OpenAppend(const string file, int &handle, bool &needsHeader)
     {
      needsHeader = !FileIsExist(file, FILE_COMMON);
      handle = FileOpen(file, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
      if(handle == INVALID_HANDLE) return false;
      if(!needsHeader && !FileSeek(handle, 0, SEEK_END))
        {
         FileClose(handle);
         handle = INVALID_HANDLE;
         return false;
        }
      return true;
     }

public:
   COpportunityTelemetry()
     {
      m_enabled = false;
      m_magic = 0;
     }

   void Init(const bool enabled, const ulong magic)
     {
      m_enabled = enabled;
      m_magic = magic;
     }

   string FileName(const datetime when) const
     {
      MqlDateTime dt;
      TimeToStruct(when, dt);
      return StringFormat("GoldenTradeX_opportunities_%I64u_%04d.csv", m_magic, dt.year);
     }

   bool Log(const SSetupAEvaluation &evaluation,
            const bool selected,
            const string scanReason)
     {
      if(!m_enabled) return true;
      datetime server = TimeCurrent();
      datetime utc = TimeGMT();
      if(server <= 0) server = utc;
      if(utc <= 0) utc = server;

      string file = FileName(utc);
      int handle = INVALID_HANDLE;
      bool needsHeader = false;
      if(!OpenAppend(file, handle, needsHeader)) return false;

      if(needsHeader)
        {
         FileWriteString(handle,
            "ServerTime,UtcTime,Magic,ScannedSymbol,Setup,Selected,Direction,Confidence,QualityScore,ProposedRiskPct,Regime,BaseScore,RegimeScore,SmcScore,HtfScore,FibScore,ATR,SourceValid,Reason\r\n");
        }

      string reason = evaluation.candidate.sourceValid
                      ? scanReason
                      : evaluation.candidate.sourceReason;
      string row = StringFormat(
         "%s,%s,%I64u,%s,%s,%d,%s,%d,%.8f,%.8f,%d,%d,%d,%d,%d,%d,%.8f,%d,%s\r\n",
         TimeToString(server, TIME_DATE | TIME_SECONDS),
         TimeToString(utc, TIME_DATE | TIME_SECONDS),
         m_magic,
         Sanitize(evaluation.candidate.symbol),
         SetupText(evaluation.candidate.setupClass),
         selected ? 1 : 0,
         DirectionText(evaluation.candidate.direction),
         evaluation.candidate.confidence,
         evaluation.candidate.qualityScore,
         evaluation.candidate.proposedRiskPct,
         (int)evaluation.regime,
         evaluation.baseSignalScore,
         evaluation.regimeScore,
         evaluation.smcScore,
         evaluation.htfScore,
         evaluation.fibScore,
         evaluation.atr,
         evaluation.candidate.sourceValid ? 1 : 0,
         Sanitize(reason));
      FileWriteString(handle, row);
      FileFlush(handle);
      FileClose(handle);
      return true;
     }
  };

#endif // GOLDENTRADEX_OPPORTUNITY_TELEMETRY_MQH
