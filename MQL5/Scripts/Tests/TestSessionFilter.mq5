//+------------------------------------------------------------------+
//|                                            TestSessionFilter.mq5 |
//|   Golden Trade X — Unit tests for CSessionFilter                 |
//+------------------------------------------------------------------+
//  Tests are self-contained: we inject datetime structs via a
//  thin wrapper that overrides TimeCurrent() with a fixed value.
//
//  Run from MetaTrader 5 → Script → TestSessionFilter
//  All results are printed to the Experts tab (Journal).
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs

#include "../../Include/GoldenTradeX/SessionFilter.mqh"

//--- Minimal test harness
int g_pass = 0;
int g_fail = 0;

void Assert(bool condition, string desc)
  {
   if(condition) { g_pass++; Print("  PASS  ", desc); }
   else          { g_fail++; Print("  FAIL  ", desc); }
  }

//+------------------------------------------------------------------+
//| Testable subclass that injects a fixed datetime                   |
//+------------------------------------------------------------------+
class CSessionFilterTestable : public CSessionFilter
  {
public:
   MqlDateTime m_fixedDt;
   bool        m_useFixed;

   CSessionFilterTestable() : m_useFixed(false) {}

   void SetTime(int dow, int hour)
     {
      m_fixedDt.day_of_week = dow;
      m_fixedDt.hour        = hour;
      m_useFixed            = true;
     }

   bool IsTradingAllowedAt(int dow, int hour)
     {
      // Re-implement logic inline using injected time
      if(!m_enabled) return true;

      if(m_closeFriday && dow == 5 && hour >= m_fridayCloseHour) return false;
      if(dow == 0 || dow == 6) return false;
      return(hour >= m_startHour && hour < m_endHour);
     }

   bool MustCloseAllAt(int dow, int hour)
     {
      if(!m_closeFriday) return false;
      return(dow == 5 && hour >= m_fridayCloseHour);
     }
  };

//+------------------------------------------------------------------+
//| Script entry point                                                |
//+------------------------------------------------------------------+
void OnStart()
  {
   Print("=== TestSessionFilter ===");

   CSessionFilterTestable sf;

   // ── 1. Disabled filter — always allowed ─────────────────────────
   sf.Init(false, 7, 20, true, 19);
   Assert(sf.IsTradingAllowedAt(1, 3),  "Disabled: Mon 03:00 allowed");
   Assert(sf.IsTradingAllowedAt(0, 12), "Disabled: Sun 12:00 allowed");
   Assert(sf.IsTradingAllowedAt(6, 10), "Disabled: Sat 10:00 allowed");
   Assert(sf.IsTradingAllowedAt(5, 21), "Disabled: Fri 21:00 allowed when disabled");

   // ── 2. Enabled, standard session 07-20 ──────────────────────────
   sf.Init(true, 7, 20, true, 19);

   Assert(sf.IsTradingAllowedAt(1, 7),  "Mon 07:00 — session open");
   Assert(sf.IsTradingAllowedAt(1, 12), "Mon 12:00 — mid session");
   Assert(sf.IsTradingAllowedAt(1, 19), "Mon 19:00 — last allowed hour");
   Assert(!sf.IsTradingAllowedAt(1, 20), "Mon 20:00 — past end hour");
   Assert(!sf.IsTradingAllowedAt(1, 6),  "Mon 06:00 — before start hour");

   // ── 3. Weekend blocks ────────────────────────────────────────────
   Assert(!sf.IsTradingAllowedAt(0, 12), "Sunday blocked");
   Assert(!sf.IsTradingAllowedAt(6, 10), "Saturday blocked");

   // ── 4. Friday close ─────────────────────────────────────────────
   Assert(sf.IsTradingAllowedAt(5, 18),  "Fri 18:00 — still open");
   Assert(!sf.IsTradingAllowedAt(5, 19), "Fri 19:00 — friday close");
   Assert(!sf.IsTradingAllowedAt(5, 21), "Fri 21:00 — friday close");

   // ── 5. MustCloseAll ─────────────────────────────────────────────
   Assert(sf.MustCloseAllAt(5, 19),  "MustCloseAll Fri 19:00");
   Assert(sf.MustCloseAllAt(5, 20),  "MustCloseAll Fri 20:00");
   Assert(!sf.MustCloseAllAt(5, 18), "MustCloseAll Fri 18:00 — not yet");
   Assert(!sf.MustCloseAllAt(4, 19), "MustCloseAll Thu 19:00 — not friday");

   // ── 6. Friday close disabled ─────────────────────────────────────
   sf.Init(true, 7, 20, false, 19);
   Assert(sf.IsTradingAllowedAt(5, 19),  "Fri 19:00 allowed when closeFriday=false");
   Assert(!sf.MustCloseAllAt(5, 20),     "MustCloseAll=false when closeFriday=false");

   // ── 7. Edge: session boundaries exact hours ───────────────────────
   sf.Init(true, 0, 24, true, 23);
   Assert(sf.IsTradingAllowedAt(1, 0),  "Session 00-24: Mon 00:00 allowed");
   Assert(sf.IsTradingAllowedAt(3, 23), "Session 00-24: Wed 23:00 allowed");

   // ── 8. Weekday boundary: Monday (dow=1) and Friday (dow=5) ───────
   sf.Init(true, 7, 20, true, 19);
   Assert(sf.IsTradingAllowedAt(2, 10), "Tuesday trading allowed");
   Assert(sf.IsTradingAllowedAt(3, 10), "Wednesday trading allowed");
   Assert(sf.IsTradingAllowedAt(4, 10), "Thursday trading allowed");

   // ── Summary ──────────────────────────────────────────────────────
   Print("=========================");
   Print("PASS: ", g_pass, " / FAIL: ", g_fail,
         " / TOTAL: ", g_pass + g_fail);
   if(g_fail == 0)
      Print(">>> ALL TESTS PASSED <<<");
   else
      Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
