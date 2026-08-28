//+------------------------------------------------------------------+
//|                                           TestRiskManager.mq5   |
//|   Golden Trade X — Tests unitarios para CRiskManager            |
//+------------------------------------------------------------------+
//  Verifica contratos observables de la API pública. No accede a
//  miembros private ni modifica encapsulación productiva para facilitar tests.
//  CalculateLotSize/DD completos permanecen como integration/Strategy Tester.
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs false
#include <GoldenTradeX/RiskManager.mqh>

static int g_pass = 0;
static int g_fail = 0;

void AssertTrue(bool cond, string label)
  {
   if(cond) { g_pass++; Print("  PASS  ", label); }
   else     { g_fail++; Print("  FAIL  ", label); }
  }

void AssertFalse(bool cond, string label) { AssertTrue(!cond, label); }
void AssertEq(double a, double b, string label)
  { AssertTrue(MathAbs(a-b) < 1e-9, label); }

//+------------------------------------------------------------------+
void OnStart()
  {
   Print("=== TestRiskManager BEGIN ===");

   // Magic de test dedicado para no colisionar con presets productivos.
   const ulong testMagic = 992630;
   CRiskManager rm;
   rm.Init(1.0, 4.0, 1, 350, testMagic, 3, 8.0);

   // Una ganancia deja el contador observable en estado limpio aunque exista
   // una GlobalVariable residual de una ejecución anterior.
   rm.RegisterTradeResult(1.0);
   AssertEq(rm.GetPositionSizeMultiplier(), 1.0,
            "Multiplicador = 1.0 con estado limpio");
   AssertFalse(rm.IsConsecutiveLossLimitReached(),
               "Limite NO alcanzado con estado limpio");

   //--- Pérdidas consecutivas observadas por sus efectos públicos
   rm.RegisterTradeResult(-10.0);
   AssertEq(rm.GetPositionSizeMultiplier(), 1.0,
            "Multiplicador = 1.0 con 1 perdida");
   AssertFalse(rm.IsConsecutiveLossLimitReached(),
               "Limite NO alcanzado con 1 perdida");

   rm.RegisterTradeResult(-5.0);
   AssertEq(rm.GetPositionSizeMultiplier(), 0.75,
            "Multiplicador = 0.75 con 2 perdidas");
   AssertFalse(rm.IsConsecutiveLossLimitReached(),
               "Limite NO alcanzado con 2 perdidas");

   rm.RegisterTradeResult(-1.0);
   AssertEq(rm.GetPositionSizeMultiplier(), 0.75,
            "Multiplicador = 0.75 con 3 perdidas");
   AssertTrue(rm.IsConsecutiveLossLimitReached(),
              "Limite alcanzado con 3 perdidas");

   rm.RegisterTradeResult(20.0);
   AssertEq(rm.GetPositionSizeMultiplier(), 1.0,
            "Ganancia restaura multiplicador a 1.0");
   AssertFalse(rm.IsConsecutiveLossLimitReached(),
               "Ganancia libera limite de perdidas consecutivas");

   //--- Portfolio Risk Cap: API pública e idempotencia
   CRiskManager portfolio;
   portfolio.Init(1.0, 4.0, 1, 350, testMagic + 1, 3, 8.0);
   portfolio.InitPortfolioCap(true, 1.5);

   // ReconcilePortfolioRisk() del Init elimina reservas fake huérfanas de
   // ejecuciones anteriores. Release adicional debe ser idempotente.
   portfolio.ReleaseOpenRisk(990001);
   portfolio.ReleaseOpenRisk(990002);
   AssertEq(portfolio.GetPortfolioRiskUsed(), 0.0,
            "PortfolioRisk inicia/reconcilia en 0");

   portfolio.RegisterOpenRisk(990001, 0.8);
   AssertEq(portfolio.GetPortfolioRiskUsed(), 0.8,
            "PortfolioRisk tras primer registro = 0.8%");
   AssertEq(portfolio.GetAvailablePortfolioRisk(), 0.7,
            "Disponible = 1.5 - 0.8 = 0.7%");

   // Re-registrar la MISMA identidad debe reemplazar su reserva, no duplicarla.
   portfolio.RegisterOpenRisk(990001, 0.6);
   AssertEq(portfolio.GetPortfolioRiskUsed(), 0.6,
            "RegisterOpenRisk es idempotente por POSITION_IDENTIFIER");

   portfolio.RegisterOpenRisk(990002, 0.5);
   AssertEq(portfolio.GetPortfolioRiskUsed(), 1.1,
            "PortfolioRisk suma dos identidades = 1.1%");
   AssertEq(portfolio.GetAvailablePortfolioRisk(), 0.4,
            "Disponible = 1.5 - 1.1 = 0.4%");

   portfolio.ReleaseOpenRisk(990001);
   AssertEq(portfolio.GetPortfolioRiskUsed(), 0.5,
            "Liberar primera identidad conserva segunda reserva");

   portfolio.ReleaseOpenRisk(990001);
   AssertEq(portfolio.GetPortfolioRiskUsed(), 0.5,
            "ReleaseOpenRisk duplicado es idempotente");

   portfolio.ReleaseOpenRisk(990002);
   AssertEq(portfolio.GetPortfolioRiskUsed(), 0.0,
            "Liberar todas las reservas vuelve a 0");

   // Cap desactivado: ningún registro debe alterar presupuesto compartido.
   CRiskManager capOff;
   capOff.Init(1.0, 4.0, 1, 350, testMagic + 2, 3, 8.0);
   capOff.InitPortfolioCap(false, 1.5);
   capOff.RegisterOpenRisk(990003, 0.9);
   AssertEq(capOff.GetPortfolioRiskUsed(), 0.0,
            "Cap OFF: RegisterOpenRisk no acumula");

   Print("=== TestRiskManager END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
