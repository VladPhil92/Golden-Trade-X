//+------------------------------------------------------------------+
//|                                         EquityCurveFilter.mqh    |
//|   Golden Trade X v2.20 — Filtro de curva de equity (EMA equity) |
//+------------------------------------------------------------------+
//  Reduce el tamaño de posición al 50% cuando la equity cae por debajo
//  de su propia EMA(period). El valor de la EMA persiste via
//  GlobalVariable para sobrevivir reinicios del EA.
//
//  Uso: llamar Update() en cada tick. Multiplicar el lote calculado
//  por el valor de retorno (1.0 = normal, 0.5 = reducido).
//+------------------------------------------------------------------+
#property strict

class CEquityCurveFilter
  {
private:
   bool   m_enabled;
   int    m_period;
   double m_ema;
   string m_gvKey;

   void UpdateEma(double equity)
     {
      double k = 2.0 / (m_period + 1.0);
      m_ema = (m_ema <= 0) ? equity : equity * k + m_ema * (1.0 - k);
      GlobalVariableSet(m_gvKey, m_ema);
     }

public:
   void Init(bool enabled, int period, ulong magic)
     {
      m_enabled = enabled;
      m_period  = (period > 1) ? period : 20;
      long login = AccountInfoInteger(ACCOUNT_LOGIN);
      m_gvKey   = StringFormat("GTX_ECF_%d_%d_EMA", (int)login, (int)magic);
      m_ema     = GlobalVariableCheck(m_gvKey) ? GlobalVariableGet(m_gvKey) : 0.0;
     }

   // Actualiza la EMA y retorna el multiplicador de tamaño de lote.
   // 0.5 si equity < EMA (modo reducido), 1.0 si no.
   double Update()
     {
      if(!m_enabled) return 1.0;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      UpdateEma(equity);
      return (m_ema > 0 && equity < m_ema) ? 0.5 : 1.0;
     }

   double GetEma() { return m_ema; }
   bool   IsEnabled() { return m_enabled; }
  };
//+------------------------------------------------------------------+
