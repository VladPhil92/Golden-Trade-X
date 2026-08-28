//+------------------------------------------------------------------+
//|                                                 NewsFilter.mqh   |
//|   Golden Trade X — Filtro de calendario de noticias de impacto   |
//+------------------------------------------------------------------+
//  Detecta automáticamente:
//    - NFP: primer viernes de cada mes (~13:30 UTC)
//    - FOMC: fechas hardcodeadas (actualizar cada año desde
//            https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
//    - CPI proxy: martes/miércoles del 10–15 de cada mes (~13:30 UTC)
//
//  Los offsets UTC→servidor se detectan automáticamente con TimeGMT().
//  Mantener InpPauseForNews=true como override manual para eventos
//  no cubiertos (discursos del presidente de la Fed, crisis geopolíticas).
//+------------------------------------------------------------------+
#property strict

class CNewsFilter
  {
private:
   bool  m_enabled;
   int   m_bufferBefore;    // minutos de bloqueo antes del evento
   int   m_bufferAfter;     // minutos de bloqueo después del evento
   int   m_serverOffset;    // horas: servidor - UTC (auto-detectado)
   bool  m_fomcWarned;      // v2.50: aviso único de cobertura FOMC agotada

   // Último año con fechas FOMC cargadas. Al superarlo, IsFomcDay deja de
   // proteger — el EA avisa UNA vez en el Journal en lugar de fallar mudo.
   static const int FOMC_LAST_YEAR;

   void DetectServerOffset()
     {
      m_serverOffset = (int)MathRound((double)(TimeCurrent() - TimeGMT()) / 3600.0);
     }

   // Convierte hora UTC a hora del servidor del broker
   int UtcToServer(int utcHour)
     {
      return((utcHour + m_serverOffset + 24) % 24);
     }

   // Devuelve true si la hora actual está en la ventana de bloqueo
   // del evento definido por evServerHour:evMinUTC.
   // Maneja correctamente blockStart negativo y blockEnd > 1439 (cruce de medianoche).
   bool InWindow(const MqlDateTime &dt, int evServerHour, int evMinUtc)
     {
      int nowMins    = dt.hour * 60 + dt.min;
      int evMins     = evServerHour * 60 + evMinUtc;
      int blockStart = evMins - m_bufferBefore;
      int blockEnd   = evMins + m_bufferAfter;

      // Ventana sin cruce de medianoche: caso normal
      if(blockStart >= 0 && blockEnd <= 1439)
         return(nowMins >= blockStart && nowMins <= blockEnd);

      // Cruce de medianoche por inicio (blockStart < 0):
      //   bloqueo activo si nowMins está en [0, blockEnd] O en [blockStart+1440, 1439]
      if(blockStart < 0)
         return(nowMins <= blockEnd || nowMins >= blockStart + 1440);

      // Cruce de medianoche por fin (blockEnd > 1439):
      //   bloqueo activo si nowMins >= blockStart O nowMins <= blockEnd-1440
      return(nowMins >= blockStart || nowMins <= blockEnd - 1440);
     }

   // NFP: primer viernes de cada mes, 13:30 UTC
   bool IsNfpWindow(const MqlDateTime &dt)
     {
      if(dt.day_of_week != 5 || dt.day > 7) return(false);
      return(InWindow(dt, UtcToServer(13), 30));
     }

   // CPI proxy: martes (2) o miércoles (3) entre el día 10 y el 15, 13:30 UTC
   // No es exacto — para precisión consultar https://www.bls.gov/schedule/news_release/cpi.htm
   bool IsCpiProxyWindow(const MqlDateTime &dt)
     {
      if(dt.day < 10 || dt.day > 15) return(false);
      if(dt.day_of_week != 2 && dt.day_of_week != 3) return(false);
      return(InWindow(dt, UtcToServer(13), 30));
     }

   // FOMC: fechas de decisión hardcodeadas
   // Decisiones típicamente a las 19:00 UTC (verano) / 19:00 UTC (invierno)
   bool IsFomcDay(int year, int mon, int day)
     {
      if(year > FOMC_LAST_YEAR && !m_fomcWarned)
        {
         m_fomcWarned = true;
         Print("NewsFilter: ATENCION — sin fechas FOMC cargadas para ", year,
               ". El filtro FOMC esta INACTIVO. Actualizar IsFomcDay() desde ",
               "federalreserve.gov/monetarypolicy/fomccalendars.htm");
        }
      if(year == 2025)
         return((mon==1  && day==29) || (mon==3  && day==19) ||
                (mon==5  && day==7)  || (mon==6  && day==18) ||
                (mon==7  && day==30) || (mon==9  && day==17) ||
                (mon==10 && day==29) || (mon==12 && day==10));
      // 2026: fechas aproximadas — verificar en federalreserve.gov antes del año nuevo
      if(year == 2026)
         return((mon==1  && day==28) || (mon==3  && day==18) ||
                (mon==4  && day==29) || (mon==6  && day==17) ||
                (mon==7  && day==29) || (mon==9  && day==16) ||
                (mon==11 && day==4)  || (mon==12 && day==9));
      // 2027: PROYECTADAS (sincronizadas con scripts/fomc_calendar.py) —
      // verificar contra federalreserve.gov cuando la Fed publique el
      // calendario oficial (~mediados de 2026) y actualizar si difieren.
      if(year == 2027)
         return((mon==1  && day==27) || (mon==3  && day==17) ||
                (mon==4  && day==28) || (mon==6  && day==16) ||
                (mon==7  && day==28) || (mon==9  && day==15) ||
                (mon==10 && day==27) || (mon==12 && day==8));
      return(false);
     }

   bool IsFomcWindow(const MqlDateTime &dt)
     {
      if(!IsFomcDay(dt.year, dt.mon, dt.day)) return(false);
      // Anuncio a las 19:00 UTC en reuniones normales
      return(InWindow(dt, UtcToServer(19), 0));
     }

public:
   void Init(bool enabled, int bufferMinsBefore, int bufferMinsAfter)
     {
      m_enabled      = enabled;
      m_bufferBefore = bufferMinsBefore;
      m_bufferAfter  = bufferMinsAfter;
      m_fomcWarned   = false;
      DetectServerOffset();
     }

   // Permite inyectar offset fijo en tests (evita dependencia de TimeCurrent/TimeGMT)
   void SetServerOffset(int offset) { m_serverOffset = offset; }

   // Devuelve true si el momento actual está dentro de una ventana de bloqueo
   bool IsNewsBlocked()
     {
      if(!m_enabled) return(false);

      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);

      if(IsNfpWindow(dt))       return(true);
      if(IsCpiProxyWindow(dt))  return(true);
      if(IsFomcWindow(dt))      return(true);

      return(false);
     }

   // Variante para tests: evalúa el bloqueo en una datetime específica
   bool IsNewsBlockedAt(datetime t)
     {
      if(!m_enabled) return(false);

      MqlDateTime dt;
      TimeToStruct(t, dt);

      if(IsNfpWindow(dt))       return(true);
      if(IsCpiProxyWindow(dt))  return(true);
      if(IsFomcWindow(dt))      return(true);

      return(false);
     }

   // Diagnóstico: imprime en el journal el offset detectado y el estado actual
   void PrintStatus()
     {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      Print("NewsFilter | ServerOffset=UTC+", m_serverOffset,
            " | Bloqueado=", (IsNewsBlocked() ? "SI" : "NO"),
            " | NFP=", (IsNfpWindow(dt) ? "SI" : "NO"),
            " | FOMC=", (IsFomcWindow(dt) ? "SI" : "NO"),
            " | CPI_proxy=", (IsCpiProxyWindow(dt) ? "SI" : "NO"));
     }
  };

const int CNewsFilter::FOMC_LAST_YEAR = 2027;
//+------------------------------------------------------------------+
