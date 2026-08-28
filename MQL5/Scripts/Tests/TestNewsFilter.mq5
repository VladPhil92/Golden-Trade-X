//+------------------------------------------------------------------+
//|                                              TestNewsFilter.mq5  |
//|   Golden Trade X v2.63 — NewsFilter correctness tests           |
//+------------------------------------------------------------------+
#property script_show_inputs false
#include <GoldenTradeX/NewsFilter.mqh>

static int g_pass = 0;
static int g_fail = 0;

void AssertTrue(bool cond, string label)
  {
   if(cond) { g_pass++; Print("  PASS  ", label); }
   else     { g_fail++; Print("  FAIL  ", label); }
  }

void AssertFalse(bool cond, string label)
  { AssertTrue(!cond, label); }

datetime MakeTime(int year, int mon, int day, int hour, int min, int sec = 0)
  {
   MqlDateTime s;
   ZeroMemory(s);
   s.year = year; s.mon = mon; s.day = day;
   s.hour = hour; s.min = min; s.sec = sec;
   return StructToTime(s);
  }

void OnStart()
  {
   Print("=== TestNewsFilter v2.63 BEGIN ===");

   // Server UTC+2.
   CNewsFilter f;
   f.Init(true, 30, 90, NEWS_CALENDAR_WARN);
   f.SetServerOffset(2);

   // NFP proxy Jan 2026: EST, 08:30 ET = 13:30 UTC = 15:30 server.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,2,15,30)), "NFP EST exact event");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,2,15,10)), "NFP EST -20m");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,2,17, 0)), "NFP EST +90m");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,1,2,14,59)), "NFP before window");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,1,2,17, 1)), "NFP after window");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,1,9,15,30)), "Second Friday is not NFP proxy");

   // NFP proxy Apr 2026: EDT, 08:30 ET = 12:30 UTC = 14:30 server.
   // The configured +90m safety buffer intentionally remains active through
   // 16:00 server time. The historical fixed-UTC clock (15:30) is therefore
   // still blocked even though it is no longer the actual event timestamp.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,4,3,14,30)), "NFP EDT shifts one hour");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,4,3,15,31)), "NFP EDT old fixed-UTC clock remains inside +90m buffer");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,4,3,16, 1)), "NFP EDT after +90m buffer");

   // FOMC Jan 28 2026: EST, 14:00 ET = 19:00 UTC = 21:00 server.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,28,21, 0)), "FOMC Jan exact event");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,28,20,35)), "FOMC Jan -25m");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,28,22,30)), "FOMC Jan +90m");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,1,28,20,29)), "FOMC Jan before window");

   // Official corrected 2026 Oct 28: EDT => 18:00 UTC => 20:00 server.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,10,28,20,0)), "FOMC Oct 28 2026 official date");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,11,4,21,0)), "Old incorrect Nov 4 date removed");

   // Official published 2027 June 9: EDT => 18:00 UTC => 20:00 server.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2027,6,9,20,0)), "FOMC Jun 9 2027 official date");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2027,6,16,20,0)), "Old projected Jun 16 date removed");

   // CPI proxy Mar 10 2026 occurs after US DST starts: 12:30 UTC = 14:30 server.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,3,10,14,30)), "CPI proxy DST-aware time");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,2,16,15,30)), "CPI proxy day outside range");

   // Midnight crossing: Jan FOMC 19:00 UTC + UTC+5 => Jan 29 00:00 server.
   CNewsFilter fMid;
   fMid.Init(true, 30, 90, NEWS_CALENDAR_WARN);
   fMid.SetServerOffset(5);
   AssertTrue (fMid.IsNewsBlockedAt(MakeTime(2026,1,28,23,35)), "midnight FOMC -25m");
   AssertTrue (fMid.IsNewsBlockedAt(MakeTime(2026,1,29, 0,30)), "midnight FOMC +30m next day");
   AssertTrue (fMid.IsNewsBlockedAt(MakeTime(2026,1,29, 1,30)), "midnight FOMC +90m next day");
   AssertFalse(fMid.IsNewsBlockedAt(MakeTime(2026,1,29, 1,31)), "midnight FOMC outside +90m");

   // Coverage fail-safe.
   CNewsFilter failClosed;
   failClosed.Init(true, 30, 90, NEWS_CALENDAR_FAIL_CLOSED);
   failClosed.SetServerOffset(2);
   AssertTrue(failClosed.IsNewsBlockedAt(MakeTime(2028,2,20,12,0)),
              "Missing FOMC coverage FAIL_CLOSED blocks");

   CNewsFilter failOpen;
   failOpen.Init(true, 30, 90, NEWS_CALENDAR_FAIL_OPEN);
   failOpen.SetServerOffset(2);
   AssertFalse(failOpen.IsNewsBlockedAt(MakeTime(2028,2,20,12,0)),
               "Missing FOMC coverage FAIL_OPEN permits non-proxy time");

   CNewsFilter fOff;
   fOff.Init(false, 30, 90, NEWS_CALENDAR_FAIL_CLOSED);
   fOff.SetServerOffset(2);
   AssertFalse(fOff.IsNewsBlockedAt(MakeTime(2026,1,28,21,0)), "Disabled filter ignores FOMC");

   Print("=== TestNewsFilter END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
