//+------------------------------------------------------------------+
//|                                                 NewsFilter.mqh   |
//|   Golden Trade X v2.62 — Filtro de noticias fail-safe           |
//+------------------------------------------------------------------+
//  FOMC 2025-2027: fechas de decisión verificadas contra la Federal
//  Reserve. Statement modelado a 14:00 US Eastern con DST.
//
//  NFP/CPI: la HORA se modela a 08:30 US Eastern con DST, pero la FECHA
//  sigue siendo proxy hasta que la fase calendar-cache integre fuentes
//  oficiales históricas/futuras. Esta limitación es deliberadamente visible.
//
//  Las ventanas se evalúan con timestamps absolutos, no minutos-del-día:
//  esto conserva correctamente buffers que cruzan medianoche.
//+------------------------------------------------------------------+
#property strict

enum ENUM_NEWS_CALENDAR_POLICY
  {
   NEWS_CALENDAR_WARN = 0,
   NEWS_CALENDAR_FAIL_CLOSED = 1,
   NEWS_CALENDAR_FAIL_OPEN = 2
  };

class CNewsFilter
  {
private:
   bool  m_enabled;
   int   m_bufferBefore;
   int   m_bufferAfter;
   int   m_serverOffset;
   int   m_offsetDateKey;
   bool  m_calendarWarned;
   ENUM_NEWS_CALENDAR_POLICY m_policy;

   static const int FOMC_FIRST_YEAR;
   static const int FOMC_LAST_YEAR;

   void DetectServerOffset()
     {
      m_serverOffset = (int)MathRound((double)(TimeCurrent() - TimeGMT()) / 3600.0);
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      m_offsetDateKey = dt.year * 10000 + dt.mon * 100 + dt.day;
     }

   void RefreshServerOffsetIfNeeded()
     {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      int key = dt.year * 10000 + dt.mon * 100 + dt.day;
      if(key != m_offsetDateKey) DetectServerOffset();
     }

   int DayOfWeekForDate(int year, int mon, int day)
     {
      MqlDateTime x;
      ZeroMemory(x);
      x.year = year; x.mon = mon; x.day = day; x.hour = 12;
      datetime t = StructToTime(x);
      TimeToStruct(t, x);
      return x.day_of_week;
     }

   int FirstSunday(int year, int mon)
     {
      int dow = DayOfWeekForDate(year, mon, 1);
      return 1 + ((7 - dow) % 7);
     }

   bool IsUsEasternDst(int year, int mon, int day)
     {
      if(mon < 3 || mon > 11) return false;
      if(mon > 3 && mon < 11) return true;
      if(mon == 3)
        {
         int secondSunday = FirstSunday(year, 3) + 7;
         return day >= secondSunday;
        }
      return day < FirstSunday(year, 11);
     }

   int EasternToUtcHour(int year, int mon, int day, int easternHour)
     { return easternHour + (IsUsEasternDst(year, mon, day) ? 4 : 5); }

   datetime EventServerTime(int year, int mon, int day, int utcHour, int minute)
     {
      // StructToTime se usa como calendario civil base; luego se desplaza por
      // offset servidor-UTC. El resultado es comparable con TimeCurrent().
      MqlDateTime x;
      ZeroMemory(x);
      x.year = year; x.mon = mon; x.day = day;
      x.hour = utcHour; x.min = minute;
      datetime utcCivil = StructToTime(x);
      return utcCivil + (datetime)(m_serverOffset * 3600);
     }

   bool InAbsoluteWindow(datetime nowServer, datetime eventServer)
     {
      if(eventServer <= 0) return false;
      datetime start = eventServer - (datetime)(m_bufferBefore * 60);
      datetime finish = eventServer + (datetime)(m_bufferAfter * 60);
      return nowServer >= start && nowServer <= finish;
     }

   bool CalendarCoverageAvailable(int year)
     { return year >= FOMC_FIRST_YEAR && year <= FOMC_LAST_YEAR; }

   bool HandleMissingCalendarCoverage(int year)
     {
      if(CalendarCoverageAvailable(year)) return false;
      if(!m_calendarWarned)
        {
         m_calendarWarned = true;
         Print("NewsFilter: CALENDAR_COVERAGE_MISSING año=", year,
               " FOMC exacto=", FOMC_FIRST_YEAR, "-", FOMC_LAST_YEAR,
               " policy=", (int)m_policy,
               ". Evidencia histórica/futura requiere calendar cache oficial.");
        }
      return m_policy == NEWS_CALENDAR_FAIL_CLOSED;
     }

   bool IsNfpProxyDate(const MqlDateTime &dt)
     { return dt.day_of_week == 5 && dt.day <= 7; }

   bool IsCpiProxyDate(const MqlDateTime &dt)
     {
      return dt.day >= 10 && dt.day <= 15 &&
             (dt.day_of_week == 2 || dt.day_of_week == 3);
     }

   bool IsFomcDecisionDate(int year, int mon, int day)
     {
      if(year == 2025)
         return((mon==1&&day==29)||(mon==3&&day==19)||(mon==5&&day==7)||
                (mon==6&&day==18)||(mon==7&&day==30)||(mon==9&&day==17)||
                (mon==10&&day==29)||(mon==12&&day==10));
      if(year == 2026)
         return((mon==1&&day==28)||(mon==3&&day==18)||(mon==4&&day==29)||
                (mon==6&&day==17)||(mon==7&&day==29)||(mon==9&&day==16)||
                (mon==10&&day==28)||(mon==12&&day==9));
      if(year == 2027)
         return((mon==1&&day==27)||(mon==3&&day==17)||(mon==4&&day==28)||
                (mon==6&&day==9)||(mon==7&&day==28)||(mon==9&&day==15)||
                (mon==10&&day==27)||(mon==12&&day==8));
      return false;
     }

   // Evalúa candidatos de fecha -1/0/+1 para que un buffer pueda cruzar
   // medianoche del servidor sin perder la asociación con la fecha del evento.
   bool IsNfpWindowAt(datetime nowServer)
     {
      for(int offset = -1; offset <= 1; offset++)
        {
         datetime candidate = nowServer + (datetime)(offset * 86400);
         MqlDateTime dt;
         TimeToStruct(candidate, dt);
         if(!IsNfpProxyDate(dt)) continue;
         int utcHour = EasternToUtcHour(dt.year, dt.mon, dt.day, 8);
         datetime ev = EventServerTime(dt.year, dt.mon, dt.day, utcHour, 30);
         if(InAbsoluteWindow(nowServer, ev)) return true;
        }
      return false;
     }

   bool IsCpiProxyWindowAt(datetime nowServer)
     {
      for(int offset = -1; offset <= 1; offset++)
        {
         datetime candidate = nowServer + (datetime)(offset * 86400);
         MqlDateTime dt;
         TimeToStruct(candidate, dt);
         if(!IsCpiProxyDate(dt)) continue;
         int utcHour = EasternToUtcHour(dt.year, dt.mon, dt.day, 8);
         datetime ev = EventServerTime(dt.year, dt.mon, dt.day, utcHour, 30);
         if(InAbsoluteWindow(nowServer, ev)) return true;
        }
      return false;
     }

   bool IsFomcWindowAt(datetime nowServer)
     {
      for(int offset = -1; offset <= 1; offset++)
        {
         datetime candidate = nowServer + (datetime)(offset * 86400);
         MqlDateTime dt;
         TimeToStruct(candidate, dt);
         if(!CalendarCoverageAvailable(dt.year)) continue;
         if(!IsFomcDecisionDate(dt.year, dt.mon, dt.day)) continue;
         int utcHour = EasternToUtcHour(dt.year, dt.mon, dt.day, 14);
         datetime ev = EventServerTime(dt.year, dt.mon, dt.day, utcHour, 0);
         if(InAbsoluteWindow(nowServer, ev)) return true;
        }
      return false;
     }

   bool Evaluate(datetime nowServer)
     {
      MqlDateTime dt;
      TimeToStruct(nowServer, dt);
      if(HandleMissingCalendarCoverage(dt.year)) return true;
      if(IsNfpWindowAt(nowServer)) return true;
      if(IsCpiProxyWindowAt(nowServer)) return true;
      if(IsFomcWindowAt(nowServer)) return true;
      return false;
     }

public:
   void Init(bool enabled, int bufferMinsBefore, int bufferMinsAfter,
             ENUM_NEWS_CALENDAR_POLICY policy = NEWS_CALENDAR_WARN)
     {
      m_enabled = enabled;
      m_bufferBefore = MathMax(0, bufferMinsBefore);
      m_bufferAfter = MathMax(0, bufferMinsAfter);
      m_policy = policy;
      m_calendarWarned = false;
      m_offsetDateKey = 0;
      DetectServerOffset();
     }

   void SetServerOffset(int offset)
     {
      m_serverOffset = offset;
      m_offsetDateKey = -1; // test hook: IsNewsBlockedAt no auto-refresca
     }

   bool IsNewsBlocked()
     {
      if(!m_enabled) return false;
      RefreshServerOffsetIfNeeded();
      return Evaluate(TimeCurrent());
     }

   bool IsNewsBlockedAt(datetime t)
     {
      if(!m_enabled) return false;
      return Evaluate(t);
     }

   void PrintStatus()
     {
      datetime now = TimeCurrent();
      Print("NewsFilter | ServerOffset=UTC", (m_serverOffset >= 0 ? "+" : ""),
            m_serverOffset,
            " | Policy=", (int)m_policy,
            " | FOMCcoverage=", FOMC_FIRST_YEAR, "-", FOMC_LAST_YEAR,
            " | Bloqueado=", (IsNewsBlocked() ? "SI" : "NO"),
            " | NFP_proxy=", (IsNfpWindowAt(now) ? "SI" : "NO"),
            " | FOMC=", (IsFomcWindowAt(now) ? "SI" : "NO"),
            " | CPI_proxy=", (IsCpiProxyWindowAt(now) ? "SI" : "NO"));
     }
  };

const int CNewsFilter::FOMC_FIRST_YEAR = 2025;
const int CNewsFilter::FOMC_LAST_YEAR = 2027;
//+------------------------------------------------------------------+
