//+------------------------------------------------------------------+
//|                                    TestResearchTelemetry.mq5     |
//| Golden Trade X — deterministic research telemetry smoke test    |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <GoldenTradeX/ResearchTelemetry.mqh>

int g_pass = 0;
int g_fail = 0;

void AssertTrue(bool condition, string label)
  {
   if(condition) { g_pass++; Print("  PASS  ", label); }
   else          { g_fail++; Print("  FAIL  ", label); }
  }

void OnStart()
  {
   Print("=== TestResearchTelemetry BEGIN ===");

   const ulong testMagic = 992700;
   CResearchTelemetry telemetry;
   telemetry.Init(true, testMagic, _Symbol, PERIOD_M1);

   datetime now = TimeCurrent();
   if(now <= 0) now = StringToTime("2026.08.28 12:00:00");
   string file = telemetry.SignalFileName(now);
   if(FileIsExist(file, FILE_COMMON))
      FileDelete(file, FILE_COMMON);

   bool wrote = telemetry.LogSignal(
      now,
      "TEST_STAGE",
      "TEST_DECISION",
      "comma,value must be sanitized",
      "BUY",
      72,
      1,
      25,
      20,
      15,
      10,
      2,
      1.25,
      100.0,
      95.0,
      110.0,
      2.0,
      0.10
   );

   AssertTrue(wrote, "Synthetic signal row writes successfully");
   AssertTrue(FileIsExist(file, FILE_COMMON), "Signal ledger file exists in Common Files");

   int handle = FileOpen(file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   AssertTrue(handle != INVALID_HANDLE, "Signal ledger can be reopened for verification");
   if(handle != INVALID_HANDLE)
     {
      string header = FileReadString(handle);
      string row = FileReadString(handle);
      AssertTrue(StringFind(header, "EventID,EventTime,BarTime") == 0,
                 "Signal ledger header is versioned/structured");
      AssertTrue(StringFind(row, "TEST_STAGE") >= 0,
                 "Signal ledger row contains stage");
      AssertTrue(StringFind(row, "comma;value must be sanitized") >= 0,
                 "CSV-breaking comma is sanitized");
      FileClose(handle);
     }

   if(FileIsExist(file, FILE_COMMON))
      FileDelete(file, FILE_COMMON);

   Print("=== TestResearchTelemetry END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
