//+------------------------------------------------------------------+
//|                         TestMultiSymbolOpportunityScanner.mq5    |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <GoldenTradeX/MultiSymbolOpportunityScanner.mqh>
#include <GoldenTradeX/OpportunityTelemetry.mqh>

int g_pass = 0;
int g_fail = 0;

void AssertTrue(bool condition, string label)
  {
   if(condition) { g_pass++; Print("  PASS  ", label); }
   else          { g_fail++; Print("  FAIL  ", label); }
  }

int LineCount(string file)
  {
   int handle = FileOpen(file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE) return 0;
   int count = 0;
   while(!FileIsEnding(handle))
     {
      string line = FileReadString(handle);
      if(StringLen(line) > 0) count++;
     }
   FileClose(handle);
   return count;
  }

void OnStart()
  {
   Print("=== TestMultiSymbolOpportunityScanner BEGIN ===");

   CMultiSymbolOpportunityScanner scanner;
   string symbols[];
   string reason = "";
   int count = scanner.ParseSymbolUniverse(" XAUUSD , XAGUSD,EURUSD ", symbols, reason);
   AssertTrue(count == 3, "Three-symbol universe parses deterministically");
   AssertTrue(ArraySize(symbols) == 3, "Parsed universe has exact size");
   if(ArraySize(symbols) == 3)
     {
      AssertTrue(symbols[0] == "XAUUSD", "Whitespace is trimmed from first symbol");
      AssertTrue(symbols[1] == "XAGUSD", "Second symbol order is preserved");
      AssertTrue(symbols[2] == "EURUSD", "Third symbol order is preserved");
     }

   count = scanner.ParseSymbolUniverse("XAUUSD,XAUUSD", symbols, reason);
   AssertTrue(count == 0 && reason == "SYMBOL_DUPLICATE", "Duplicate symbols fail closed");

   count = scanner.ParseSymbolUniverse("XAUUSD,,EURUSD", symbols, reason);
   AssertTrue(count == 0 && reason == "SYMBOL_EMPTY", "Empty symbol slot fails closed");

   count = scanner.ParseSymbolUniverse("A,B,C,D", symbols, reason);
   AssertTrue(count == 0 && reason == "SYMBOL_UNIVERSE_TOO_LARGE", "Universe above fixed capacity fails closed");

   const ulong magic = 993110;
   COpportunityTelemetry telemetry;
   telemetry.Init(true, magic);
   datetime now = TimeGMT();
   if(now <= 0) now = StringToTime("2026.08.29 12:00:00");
   string file = telemetry.FileName(now);
   if(FileIsExist(file, FILE_COMMON)) FileDelete(file, FILE_COMMON);

   SSetupAEvaluation evaluation;
   ZeroMemory(evaluation);
   evaluation.candidate.symbol = "XAUUSD";
   evaluation.candidate.setupClass = GTX_SETUP_A_HIGH_CONVICTION;
   evaluation.candidate.direction = 1;
   evaluation.candidate.confidence = 72;
   evaluation.candidate.qualityScore = 72.0;
   evaluation.candidate.proposedRiskPct = 1.0;
   evaluation.candidate.sourceValid = true;
   evaluation.regime = REGIME_TRENDING_BULL;
   evaluation.baseSignalScore = 25;
   evaluation.regimeScore = 25;
   evaluation.smcScore = 12;
   evaluation.htfScore = 8;
   evaluation.fibScore = 2;
   evaluation.atr = 12.5;

   AssertTrue(telemetry.Log(evaluation, true, "SELECTED_BY_PRE_REGISTERED_QUALITY"),
              "Shadow telemetry first row writes");
   AssertTrue(telemetry.Log(evaluation, false, "NOT_SELECTED"),
              "Shadow telemetry appends a second row");
   AssertTrue(LineCount(file) == 3, "Shadow ledger contains header plus two rows");

   if(FileIsExist(file, FILE_COMMON)) FileDelete(file, FILE_COMMON);
   Print("=== TestMultiSymbolOpportunityScanner END | PASS=", g_pass, " FAIL=", g_fail, " ===");
  }
