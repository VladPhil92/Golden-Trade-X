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

int CsvFieldCount(string line)
  {
   if(StringLen(line) == 0) return 0;
   int fields = 1;
   for(int i = 0; i < StringLen(line); i++)
      if(StringGetCharacter(line, i) == ',') fields++;
   return fields;
  }

bool ReadTwoLines(string file, string &header, string &row)
  {
   int handle = FileOpen(file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE) return false;
   header = FileReadString(handle);
   row = FileReadString(handle);
   FileClose(handle);
   return true;
  }

bool ReadLastLine(string file, string &last)
  {
   int handle = FileOpen(file, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE) return false;
   last = "";
   while(!FileIsEnding(handle))
     {
      string line = FileReadString(handle);
      if(StringLen(line) > 0) last = line;
     }
   FileClose(handle);
   return StringLen(last) > 0;
  }

void DeleteIfExists(string file)
  {
   if(FileIsExist(file, FILE_COMMON))
      FileDelete(file, FILE_COMMON);
  }

void OnStart()
  {
   Print("=== TestResearchTelemetry BEGIN ===");

   const ulong testMagic = 992700;
   CResearchTelemetry telemetry;
   telemetry.Init(true, testMagic, _Symbol, PERIOD_M1);

   datetime now = TimeCurrent();
   if(now <= 0) now = StringToTime("2026.08.28 12:00:00");

   string sessionFile = telemetry.SessionFileName(now);
   string signalFile = telemetry.SignalFileName(now);
   string executionFile = telemetry.ExecutionFileName(now);
   string outcomeFile = telemetry.OutcomeFileName(now);
   DeleteIfExists(sessionFile);
   DeleteIfExists(signalFile);
   DeleteIfExists(executionFile);
   DeleteIfExists(outcomeFile);

   bool sessionWrote = telemetry.StartSession(
      "gtx-test-candidate",
      "build-test-123",
      "InpMagicNumber=992700|InpEmaFast=21|InpRiskPercent=1.00000000"
   );
   AssertTrue(sessionWrote, "Synthetic session START writes successfully");
   AssertTrue(FileIsExist(sessionFile, FILE_COMMON), "Session ledger file exists in Common Files");

   string header = "", row = "";
   bool readSession = ReadTwoLines(sessionFile, header, row);
   AssertTrue(readSession, "Session ledger can be reopened for verification");
   if(readSession)
     {
      AssertTrue(StringFind(header, "EventID,ServerTime,UtcTime") == 0,
                 "Session ledger carries server and UTC time");
      AssertTrue(StringFind(row, "gtx-test-candidate") >= 0,
                 "Session row contains candidate identity");
      AssertTrue(StringFind(row, "build-test-123") >= 0,
                 "Session row contains build identity");
      AssertTrue(StringFind(row, "InpEmaFast=21") >= 0,
                 "Session row contains canonical runtime config snapshot");
      AssertTrue(CsvFieldCount(header) == 15 && CsvFieldCount(row) == 15,
                 "Session header and row both contain 15 fields");
     }

   bool endWrote = telemetry.EndSession(42);
   AssertTrue(endWrote, "Synthetic session END writes successfully");
   string lastSession = "";
   bool readEnd = ReadLastLine(sessionFile, lastSession);
   AssertTrue(readEnd, "Session END can be reopened for verification");
   if(readEnd)
     {
      AssertTrue(StringFind(lastSession, ",END,") >= 0,
                 "Final session row is END");
      AssertTrue(StringFind(lastSession, "build-test-123") >= 0,
                 "END preserves exact build identity");
      AssertTrue(StringFind(lastSession, "deinit=") < 0,
                 "Deinit reason is not mixed into BuildID");
      AssertTrue(CsvFieldCount(lastSession) == 15,
                 "Session END preserves the 15-field contract");
     }

   bool signalWrote = telemetry.LogSignal(
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

   AssertTrue(signalWrote, "Synthetic signal row writes successfully");
   AssertTrue(FileIsExist(signalFile, FILE_COMMON), "Signal ledger file exists in Common Files");

   header = "";
   row = "";
   bool readSignal = ReadTwoLines(signalFile, header, row);
   AssertTrue(readSignal, "Signal ledger can be reopened for verification");
   if(readSignal)
     {
      AssertTrue(StringFind(header, "EventID,EventTime,BarTime") == 0,
                 "Signal ledger header is versioned/structured");
      AssertTrue(StringFind(row, "TEST_STAGE") >= 0,
                 "Signal ledger row contains stage");
      AssertTrue(StringFind(row, "comma;value must be sanitized") >= 0,
                 "CSV-breaking comma is sanitized");
      AssertTrue(CsvFieldCount(header) == 30 && CsvFieldCount(row) == 30,
                 "Signal header and row both contain 30 fields");
     }

   bool executionWrote = telemetry.LogOrderResult(
      "OPEN", "SERVER_CONFIRMED", "BUY",
      100.0, 95.0, 110.0, 0.10,
      10009, 0,
      100.1, 0.10, 1.0,
      2001, 3001, 4001, 5001,
      "broker,comment"
   );
   AssertTrue(executionWrote, "Synthetic execution row writes successfully");

   header = "";
   row = "";
   bool readExecution = ReadTwoLines(executionFile, header, row);
   AssertTrue(readExecution, "Execution ledger can be reopened for verification");
   if(readExecution)
     {
      AssertTrue(StringFind(header, "EventID,EventTime,Account") == 0,
                 "Execution ledger header is structured");
      AssertTrue(StringFind(row, "broker;comment") >= 0,
                 "Execution comment comma is sanitized");
      AssertTrue(CsvFieldCount(header) == 28 && CsvFieldCount(row) == 28,
                 "Execution header and request/result row both contain 28 fields");
     }

   bool outcomeWrote = telemetry.LogPositionOutcome(
      now,
      _Symbol,
      4001,
      "BUY",
      now - 3600,
      100.1,
      95.0,
      110.0,
      5.1,
      51.0,
      0.10,
      72,
      1,
      1.8,
      109.28,
      now - 900,
      0.35,
      98.315,
      now - 2700,
      40.8,
      0.8,
      104.18
   );
   AssertTrue(outcomeWrote, "Synthetic position outcome writes successfully");

   header = "";
   row = "";
   bool readOutcome = ReadTwoLines(outcomeFile, header, row);
   AssertTrue(readOutcome, "Outcome ledger can be reopened for verification");
   if(readOutcome)
     {
      AssertTrue(StringFind(header, "EventID,CloseTime,Account") == 0,
                 "Outcome ledger header is structured");
      AssertTrue(CsvFieldCount(header) == 25 && CsvFieldCount(row) == 25,
                 "Outcome header and row both contain 25 fields");
     }

   DeleteIfExists(sessionFile);
   DeleteIfExists(signalFile);
   DeleteIfExists(executionFile);
   DeleteIfExists(outcomeFile);

   Print("=== TestResearchTelemetry END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
