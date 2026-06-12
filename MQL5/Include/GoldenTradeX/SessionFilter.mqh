//+------------------------------------------------------------------+
//|                                                SessionFilter.mqh |
//|   Golden Trade X — Filtro horario y de fin de semana             |
//+------------------------------------------------------------------+
#property strict

class CSessionFilter
  {
private:
   bool m_enabled;
   int  m_startHour;
   int  m_endHour;
   bool m_closeFriday;
   int  m_fridayCloseHour;

public:
   void Init(bool enabled, int startHour, int endHour,
             bool closeFriday, int fridayCloseHour)
     {
      m_enabled         = enabled;
      m_startHour       = startHour;
      m_endHour         = endHour;
      m_closeFriday     = closeFriday;
      m_fridayCloseHour = fridayCloseHour;
     }

   //--- ¿Está permitido abrir nuevas operaciones?
   bool IsTradingAllowed()
     {
      if(!m_enabled) return(true);

      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);

      //--- Nunca abrir cerca del cierre semanal
      if(m_closeFriday && dt.day_of_week == 5 && dt.hour >= m_fridayCloseHour)
         return(false);

      if(dt.day_of_week == 0 || dt.day_of_week == 6)
         return(false);

      return(dt.hour >= m_startHour && dt.hour < m_endHour);
     }

   //--- ¿Hay que cerrar todo (viernes tarde)?
   bool MustCloseAll()
     {
      if(!m_closeFriday) return(false);
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      return(dt.day_of_week == 5 && dt.hour >= m_fridayCloseHour);
     }
  };
//+------------------------------------------------------------------+
