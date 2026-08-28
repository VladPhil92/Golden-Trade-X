//+------------------------------------------------------------------+
//|                                            TestSessionFilter.mq5 |
//|   Golden Trade X — Unit tests for CSessionFilter                 |
//+------------------------------------------------------------------+
//  Uses the production IsTradingAllowedAt/MustCloseAllAt methods.
//  No private state access and no duplicated session logic.
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false

#include <GoldenTradeX/SessionFilter.mqh>

int g_pass = 0;
int g_fail = 0;

void Assert(bool condition, string desc)
  {
   if(condition) { g_pass++; Print("  PASS  ", desc); }
   else          { g_fail++; Print("  FAIL  ", desc); }
  }

datetime MakeTime(int year, int mon, int day, int hour, int min = 0)
  {
   MqlDateTime dt;
   ZeroMemory(dt);
   dt.year = year;
   dt.mon  = mon;
   dt.day  = day;
   dt.hour = hour;
   dt.min  = min;
   return StructToTime(dt);
  }

void OnStart()
  {
   Print("=== TestSessionFilter BEGIN ===");
   CSessionFilter sf;

   // 2026-08-24 Monday; 28 Friday; 29 Saturday; 30 Sunday.
   datetime mon03 = MakeTime(2026, 8, 24, 3);
   datetime mon06 = MakeTime(2026, 8, 24, 6);
   datetime mon07 = MakeTime(2026, 8, 24, 7);
   datetime mon12 = MakeTime(2026, 8, 24, 12);
   datetime mon19 = MakeTime(2026, 8, 24, 19);
   datetime mon20 = MakeTime(2026, 8, 24, 20);
   datetime tue10 = MakeTime(2026, 8, 25, 10);
   datetime wed10 = MakeTime(2026, 8, 26, 10);
   datetime thu10 = MakeTime(2026, 8, 27, 10);
   datetime thu19 = MakeTime(2026, 8, 27, 19);
   datetime fri18 = MakeTime(2026, 8, 28, 18);
   datetime fri19 = MakeTime(2026, 8, 28, 19);
   datetime fri20 = MakeTime(2026, 8, 28, 20);
   datetime fri21 = MakeTime(2026, 8, 28, 21);
   datetime sat10 = MakeTime(2026, 8, 29, 10);
   datetime sun12 = MakeTime(2026, 8, 30, 12);

   // Disabled means the trading-session gate itself does not block entries.
   sf.Init(false, 7, 20, true, 19);
   Assert(sf.IsTradingAllowedAt(mon03), "Disabled: Mon 03:00 allowed");
   Assert(sf.IsTradingAllowedAt(sun12), "Disabled: Sun 12:00 allowed");
   Assert(sf.IsTradingAllowedAt(sat10), "Disabled: Sat 10:00 allowed");
   Assert(sf.IsTradingAllowedAt(fri21), "Disabled: Fri 21:00 allowed");

   sf.Init(true, 7, 20, true, 19);
   Assert(sf.IsTradingAllowedAt(mon07),  "Mon 07:00 session open");
   Assert(sf.IsTradingAllowedAt(mon12),  "Mon 12:00 mid session");
   Assert(sf.IsTradingAllowedAt(mon19),  "Mon 19:00 last allowed hour");
   Assert(!sf.IsTradingAllowedAt(mon20), "Mon 20:00 past end hour");
   Assert(!sf.IsTradingAllowedAt(mon06), "Mon 06:00 before start hour");

   Assert(!sf.IsTradingAllowedAt(sun12), "Sunday blocked");
   Assert(!sf.IsTradingAllowedAt(sat10), "Saturday blocked");

   Assert(sf.IsTradingAllowedAt(fri18),  "Fri 18:00 still open");
   Assert(!sf.IsTradingAllowedAt(fri19), "Fri 19:00 friday close");
   Assert(!sf.IsTradingAllowedAt(fri21), "Fri 21:00 friday close");

   Assert(sf.MustCloseAllAt(fri19),  "MustCloseAll Fri 19:00");
   Assert(sf.MustCloseAllAt(fri20),  "MustCloseAll Fri 20:00");
   Assert(!sf.MustCloseAllAt(fri18), "MustCloseAll Fri 18:00 false");
   Assert(!sf.MustCloseAllAt(thu19), "MustCloseAll Thu 19:00 false");

   sf.Init(true, 7, 20, false, 19);
   Assert(sf.IsTradingAllowedAt(fri19), "Fri 19:00 allowed when closeFriday=false");
   Assert(!sf.MustCloseAllAt(fri20),    "MustCloseAll false when closeFriday=false");

   // A full-day session uses endHour=24 internally. The EA presets retain
   // validated 0..23 hours; this case only checks the class boundary logic.
   sf.Init(true, 0, 24, true, 23);
   Assert(sf.IsTradingAllowedAt(MakeTime(2026,8,24,0)),  "00-24: Mon 00:00 allowed");
   Assert(sf.IsTradingAllowedAt(MakeTime(2026,8,26,23)), "00-24: Wed 23:00 allowed");

   sf.Init(true, 7, 20, true, 19);
   Assert(sf.IsTradingAllowedAt(tue10), "Tuesday trading allowed");
   Assert(sf.IsTradingAllowedAt(wed10), "Wednesday trading allowed");
   Assert(sf.IsTradingAllowedAt(thu10), "Thursday trading allowed");

   Print("=== TestSessionFilter END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
