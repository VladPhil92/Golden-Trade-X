//+------------------------------------------------------------------+
//|                                                SessionFilter.mqh |
//|   Golden Trade X v2.60 — Filtro horario y de fin de semana       |
//+------------------------------------------------------------------+
//  InpStartHour/InpEndHour se interpretan en HORA DEL SERVIDOR del broker
//  (no UTC), por diseño — es lo que la mayoría de EAs asumen y lo que el
//  operador ve directamente en el terminal. La contrapartida: si el
//  servidor cambia de horario de verano/invierno (DST), la ventana
//  Londres-NY que el operador tenía en mente se desplaza una hora sin
//  aviso. v2.60 no cambia el comportamiento (no auto-convierte a UTC,
//  para no alterar configuraciones ya calibradas), pero SÍ detecta el
//  cambio de offset servidor-UTC entre inicializaciones y lo advierte en
//  el Journal, para que el operador revise InpStartHour/InpEndHour.
//+------------------------------------------------------------------+
#property strict

class CSessionFilter
  {
private:
   bool   m_enabled;
   int    m_startHour;
   int    m_endHour;
   bool   m_closeFriday;
   int    m_fridayCloseHour;
   string m_gvOffsetKey;

   int DetectServerOffsetUtc()
     {
      return (int)MathRound((double)(TimeCurrent() - TimeGMT()) / 3600.0);
     }

   void WarnIfOffsetChanged()
     {
      if(m_gvOffsetKey == "") return;
      int current = DetectServerOffsetUtc();
      if(GlobalVariableCheck(m_gvOffsetKey))
        {
         int previous = (int)GlobalVariableGet(m_gvOffsetKey);
         if(previous != current)
            Print("SessionFilter: ATENCION — el offset servidor-UTC cambio de ",
                  "UTC", (previous >= 0 ? "+" : ""), previous, " a ",
                  "UTC", (current >= 0 ? "+" : ""), current,
                  " (probable cambio de horario DST). InpStartHour=", m_startHour,
                  " InpEndHour=", m_endHour, " estan en hora de SERVIDOR — verifica ",
                  "que sigan cubriendo la ventana Londres-NY que deseas.");
        }
      GlobalVariableSet(m_gvOffsetKey, (double)current);
     }

public:
   void Init(bool enabled, int startHour, int endHour,
             bool closeFriday, int fridayCloseHour)
     {
      m_enabled         = enabled;
      m_startHour       = startHour;
      m_endHour         = endHour;
      m_closeFriday     = closeFriday;
      m_fridayCloseHour = fridayCloseHour;

      // v2.60: clave por cuenta — persiste el último offset UTC detectado
      // para poder comparar en el siguiente arranque del EA.
      long login    = AccountInfoInteger(ACCOUNT_LOGIN);
      m_gvOffsetKey = (login != 0) ? StringFormat("GTX_%d_ServerUtcOffset", (int)login) : "";
      if(m_enabled) WarnIfOffsetChanged();
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
