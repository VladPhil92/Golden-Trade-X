//+------------------------------------------------------------------+
//|                                                 NewsFilter.mqh   |
//|   Golden Trade X v2.62 — Filtro de noticias fail-safe           |
//+------------------------------------------------------------------+
//  FOMC 2025-2027: fechas de decisión verificadas contra el calendario
//  publicado por la Federal Reserve. La hora del statement se modela como
//  14:00 US Eastern y se convierte dinámicamente a UTC según DST de EE.UU.
//
//  NFP/CPI siguen siendo proxies de FECHA hasta que el calendar cache oficial
//  de la fase de research sustituya estas heurísticas. Su HORA sí se convierte
//  correctamente desde 08:30 US Eastern (12:30 UTC en DST / 13:30 estándar).
//
//  La cobertura de calendario tiene política explícita WARN / FAIL_CLOSED /
//  FAIL_OPEN para impedir que una expiración silenciosa incremente el riesgo.
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

   int UtcToServer(int utcHour)
     { return((utcHour + m_serverOffset + 24) % 24); }

   bool InWindow(const MqlDateTime &dt, int evServerHour, int evMinute)
     {
      int nowMins = dt.hour * 60 + dt.min;
      int evMins = evServerHour * 60 + evMinute;
      int blockStart = evMins - m_bufferBefore;
      int blockEnd = evMins + m_bufferAfter;

      if(blockStart >= 0 && blockEnd <= 1439)
         return(nowMins >= blockStart && nowMins <= blockEnd);
      if(blockStart < 0)
         return(nowMins <= blockEnd || nowMins >= blockStart + 1440);
      return(nowMins >= blockStart || nowMins <= blockEnd - 1440);
     }

   int DayOfWeekForDate(int year, int mon, int day)
     {
      MqlDateTime x;
      ZeroMemory(x);
      x.year = year;
      x.mon = mon;
      x.day = day;
      x.hour = 12;
      datetime t = StructToTime(x);
      TimeToStruct(t, x);
      return x.day_of_week;
     }

   int FirstSunday(int year, int mon)
     {
      int dow = DayOfWeekForDate(year, mon, 1);
      return 1 + ((7 - dow) % 7);
     }

   // Reglas DST de Estados Unidos vigentes desde 2007:
   // segundo domingo de marzo → primer domingo de noviembre.
   bool IsUsEasternDst(int year, int mon, int day)
     {
      if(mon < 3 || mon > 11) return false;
      if(mon > 3 && mon < 11) return true;
      if(mon == 3)
        {
         int secondSunday = FirstSunday(year, 3) + 7;
         return day >= secondSunday;
        }
      int firstSundayNov = FirstSunday(year, 11);
      return day < firstSundayNov;
     }

   int EasternToUtcHour(int year, int mon, int day, int easternHour)
     {
      // EDT=UTC-4; EST=UTC-5.
      return easternHour + (IsUsEasternDst(year, mon, day) ? 4 : 5);
     }

   bool CalendarCoverageAvailable(int year)
     { return year >= FOMC_FIRST_YEAR && year <= FOMC_LAST_YEAR; }

   bool HandleMissingCalendarCoverage(int year)
     {
      if(CalendarCoverageAvailable(year)) return false;

      if(!m_calendarWarned)
        {
         m_calendarWarned = true;
         Print("NewsFilter: CALENDAR_COVERAGE_MISSING para año ", year,
               " (FOMC exacto disponible ", FOMC_FIRST_YEAR, "-", FOMC_LAST_YEAR,
               "). Policy=", (int)m_policy,
               ". Para evidencia histórica/futura cargar calendario oficial.");
        }

      // true significa bloquear la operación por política fail-closed.
      return m_policy == NEWS_CALENDAR_FAIL_CLOSED;
     }

   // NFP: proxy de fecha = primer viernes. Hora oficial típica 08:30 ET,
   // convertida con DST; festivos pueden desplazar la FECHA → fase calendar cache.
   bool IsNfpWindow(const MqlDateTime &dt)
     {
      if(dt.day_of_week != 5 || dt.day > 7) return false;
      int utcHour = EasternToUtcHour(dt.year, dt.mon, dt.day, 8);
      return InWindow(dt, UtcToServer(utcHour), 30);
     }

   // CPI: proxy de fecha. Hora típica 08:30 ET convertida con DST.
   bool IsCpiProxyWindow(const MqlDateTime &dt)
     {
      if(dt.day < 10 || dt.day > 15) return false;
      if(dt.day_of_week != 2 && dt.day_of_week != 3) return false;
      int utcHour = EasternToUtcHour(dt.year, dt.mon, dt.day, 8);
      return InWindow(dt, UtcToServer(utcHour), 30);
     }

   // Fechas de DECISIÓN/statement (segundo día de reunión) verificadas.
   bool IsFomcDecisionDate(int year, int mon, int day)
     {
      if(year == 2025)
         return((mon==1  && day==29) || (mon==3  && day==19) ||
                (mon==5  && day==7)  || (mon==6  && day==18) ||
                (mon==7  && day==30) || (mon==9  && day==17) ||
                (mon==10 && day==29) || (mon==12 && day==10));

      if(year == 2026)
         return((mon==1  && day==28) || (mon==3  && day==18) ||
                (mon==4  && day==29) || (mon==6  && day==17) ||
                (mon==7  && day==29) || (mon==9  && day==16) ||
                (mon==10 && day==28) || (mon==12 && day==9));

      if(year == 2027)
         return((mon==1  && day==27) || (mon==3  && day==17) ||
                (mon==4  && day==28) || (mon==6  && day==9)  ||
                (mon==7  && day==28) || (mon==9  && day==15) ||
                (mon==10 && day==27) || (mon==12 && day==8));
      return false;
     }

   bool IsFomcWindow(const MqlDateTime &dt)
     {
      if(!CalendarCoverageAvailable(dt.year)) return false;
      if(!IsFomcDecisionDate(dt.year, dt.mon, dt.day)) return false;
      // Regular statement: 14:00 US Eastern → 18:00 UTC DST / 19:00 UTC EST.
      int utcHour = EasternToUtcHour(dt.year, dt.mon, dt.day, 14);
      return InWindow(dt, UtcToServer(utcHour), 0);
     }

   bool Evaluate(const MqlDateTime &dt)
     {
      if(HandleMissingCalendarCoverage(dt.year)) return true;
      if(IsNfpWindow(dt)) return true;
      if(IsCpiProxyWindow(dt)) return true;
      if(IsFomcWindow(dt)) return true;
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
      // Test hook: evitar auto-refresh durante IsNewsBlockedAt.
      m_offsetDateKey = -1;
     }

   bool IsNewsBlocked()
     {
      if(!m_enabled) return false;
      RefreshServerOffsetIfNeeded();
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      return Evaluate(dt);
     }

   bool IsNewsBlockedAt(datetime t)
     {
      if(!m_enabled) return false;
      MqlDateTime dt;
      TimeToStruct(t, dt);
      return Evaluate(dt);
     }

   void PrintStatus()
     {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      Print("NewsFilter | ServerOffset=UTC", (m_serverOffset >= 0 ? "+" : ""),
            m_serverOffset,
            " | Policy=", (int)m_policy,
            " | FOMCcoverage=", FOMC_FIRST_YEAR, "-", FOMC_LAST_YEAR,
            " | Bloqueado=", (IsNewsBlocked() ? "SI" : "NO"),
            " | NFP_proxy=", (IsNfpWindow(dt) ? "SI" : "NO"),
            " | FOMC=", (IsFomcWindow(dt) ? "SI" : "NO"),
            " | CPI_proxy=", (IsCpiProxyWindow(dt) ? "SI" : "NO"));
     }
  };

const int CNewsFilter::FOMC_FIRST_YEAR = 2025;
const int CNewsFilter::FOMC_LAST_YEAR = 2027;
//+------------------------------------------------------------------+
