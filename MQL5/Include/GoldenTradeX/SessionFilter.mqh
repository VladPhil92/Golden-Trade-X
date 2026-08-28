//+------------------------------------------------------------------+
//|                                                SessionFilter.mqh |
//|   Golden Trade X — Filtro horario y de fin de semana             |
//+------------------------------------------------------------------+
//  InpStartHour/InpEndHour se interpretan en HORA DEL SERVIDOR del broker
//  (no UTC), por diseño. El módulo expone variantes *At(datetime) para que
//  la misma lógica productiva pueda verificarse determinísticamente sin
//  acceder a estado privado ni duplicar reglas dentro de los tests.
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

   bool TradingAllowedFor(const MqlDateTime &dt)
     {
      if(!m_enabled) return true;

      if(m_closeFriday && dt.day_of_week == 5 && dt.hour >= m_fridayCloseHour)
         return false;

      if(dt.day_of_week == 0 || dt.day_of_week == 6)
         return false;

      return(dt.hour >= m_startHour && dt.hour < m_endHour);
     }

   bool MustCloseFor(const MqlDateTime &dt)
     {
      if(!m_closeFriday) return false;
      return(dt.day_of_week == 5 && dt.hour >= m_fridayCloseHour);
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

      long login    = AccountInfoInteger(ACCOUNT_LOGIN);
      m_gvOffsetKey = (login != 0) ? StringFormat("GTX_%d_ServerUtcOffset", (int)login) : "";
      if(m_enabled) WarnIfOffsetChanged();
     }

   // Evalúa exactamente la lógica productiva para una hora arbitraria de
   // servidor. Es una seam de test determinística y también útil para
   // diagnósticos/replays; no expone ni permite mutar estado interno.
   bool IsTradingAllowedAt(datetime serverTime)
     {
      MqlDateTime dt;
      TimeToStruct(serverTime, dt);
      return TradingAllowedFor(dt);
     }

   bool MustCloseAllAt(datetime serverTime)
     {
      MqlDateTime dt;
      TimeToStruct(serverTime, dt);
      return MustCloseFor(dt);
     }

   bool IsTradingAllowed()
     {
      return IsTradingAllowedAt(TimeCurrent());
     }

   bool MustCloseAll()
     {
      return MustCloseAllAt(TimeCurrent());
     }
  };
//+------------------------------------------------------------------+
