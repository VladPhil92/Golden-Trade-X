//+------------------------------------------------------------------+
//|                                              TestNewsFilter.mq5  |
//|   Golden Trade X — approved NewsFilter correctness tests        |
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
   Print("=== TestNewsFilter APPROVED CALENDAR BEGIN ===");

   // Canonical approved calendar currently covers 2021-01-01..2025-12-31.
   AssertTrue(GTX_ECONOMIC_CALENDAR_APPROVED, "Canonical economic calendar is approved");

   // Server UTC+2.
   CNewsFilter f;
   f.Init(true, 30, 90, NEWS_CALENDAR_WARN);
   f.SetServerOffset(2);

   // Exact NFP Jan 10 2025: EST, 08:30 ET = 13:30 UTC = 15:30 server.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,1,10,15,30)), "NFP EST exact event");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,1,10,15,10)), "NFP EST -20m");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,1,10,17, 0)), "NFP EST +90m");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2025,1,10,14,59)), "NFP before window");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2025,1,10,17, 1)), "NFP after window");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2025,1,17,15,30)), "Non-release Friday is not NFP");

   // Exact NFP Apr 4 2025: EDT, 08:30 ET = 12:30 UTC = 14:30 server.
   // The +90m safety buffer remains active through 16:00 server time.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,4,4,14,30)), "NFP EDT shifts one hour");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,4,4,15,31)), "NFP EDT old fixed-UTC clock remains inside +90m buffer");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2025,4,4,16, 1)), "NFP EDT after +90m buffer");

   // Exact FOMC Jan 29 2025: EST, 14:00 ET = 19:00 UTC = 21:00 server.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,1,29,21, 0)), "FOMC Jan exact event");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,1,29,20,35)), "FOMC Jan -25m");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,1,29,22,30)), "FOMC Jan +90m");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2025,1,29,20,29)), "FOMC Jan before window");

   // Exact FOMC Oct 29 2025: EDT => 18:00 UTC => 20:00 server.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,10,29,20,0)), "FOMC Oct exact approved date");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2025,11,5,21,0)), "Non-FOMC November date is not blocked");

   // Exact CPI Mar 12 2025 occurs after US DST starts: 12:30 UTC = 14:30 server.
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,3,12,14,30)), "CPI exact DST-aware time");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2025,2,16,15,30)), "CPI non-release date remains open");

   // Midnight crossing: Jan FOMC 19:00 UTC + UTC+5 => Jan 30 00:00 server.
   CNewsFilter fMid;
   fMid.Init(true, 30, 90, NEWS_CALENDAR_WARN);
   fMid.SetServerOffset(5);
   AssertTrue (fMid.IsNewsBlockedAt(MakeTime(2025,1,29,23,35)), "midnight FOMC -25m");
   AssertTrue (fMid.IsNewsBlockedAt(MakeTime(2025,1,30, 0,30)), "midnight FOMC +30m next day");
   AssertTrue (fMid.IsNewsBlockedAt(MakeTime(2025,1,30, 1,30)), "midnight FOMC +90m next day");
   AssertFalse(fMid.IsNewsBlockedAt(MakeTime(2025,1,30, 1,31)), "midnight FOMC outside +90m");

   // Exact coverage fail-safe. 2026 is outside the approved 2021-2025 contract.
   CNewsFilter failClosed;
   failClosed.Init(true, 30, 90, NEWS_CALENDAR_FAIL_CLOSED);
   failClosed.SetServerOffset(2);
   AssertTrue(failClosed.IsNewsBlockedAt(MakeTime(2026,2,20,12,0)),
              "Approved-calendar coverage gap FAIL_CLOSED blocks");
   AssertTrue(failClosed.IsNewsBlockedAt(MakeTime(2020,12,20,12,0)),
              "Pre-coverage timestamp FAIL_CLOSED blocks");

   CNewsFilter failOpen;
   failOpen.Init(true, 30, 90, NEWS_CALENDAR_FAIL_OPEN);
   failOpen.SetServerOffset(2);
   AssertFalse(failOpen.IsNewsBlockedAt(MakeTime(2026,2,20,12,0)),
               "Approved-calendar coverage gap FAIL_OPEN permits non-event time");

   CNewsFilter fOff;
   fOff.Init(false, 30, 90, NEWS_CALENDAR_FAIL_CLOSED);
   fOff.SetServerOffset(2);
   AssertFalse(fOff.IsNewsBlockedAt(MakeTime(2025,1,29,21,0)), "Disabled filter ignores approved FOMC");
   AssertFalse(fOff.IsNewsBlockedAt(MakeTime(2026,1,29,21,0)), "Disabled filter ignores coverage fail-safe");

   Print("=== TestNewsFilter END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
