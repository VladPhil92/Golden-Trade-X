//+------------------------------------------------------------------+
//|                                           TestRiskManager.mq5   |
//|   Golden Trade X — Tests unitarios para CRiskManager            |
//+------------------------------------------------------------------+
//  Ejecución: arrastrar el script al gráfico en MetaEditor/MT5.
//  El resultado aparece en la pestaña Experts del Journal.
//
//  NOTA: CalculateLotSize y las comprobaciones de DD/drawdown dependen
//  de AccountInfoDouble/SymbolInfo — sólo se prueban las partes puras
//  (conteo de pérdidas consecutivas, multiplicador de tamaño).
//  Para los tests de integración completos usar el Strategy Tester.
//+------------------------------------------------------------------+
#property script_show_inputs false
#include <GoldenTradeX/RiskManager.mqh>

static int g_pass = 0;
static int g_fail = 0;

void AssertTrue(bool cond, string label)
  {
   if(cond) { g_pass++; Print("  PASS  ", label); }
   else     { g_fail++; Print("  FAIL  ", label); }
  }

void AssertFalse(bool cond, string label)  { AssertTrue(!cond, label); }
void AssertEq(double a, double b, string label) { AssertTrue(MathAbs(a-b)<1e-9, label); }
void AssertEqI(long a, long b, string label)    { AssertTrue(a==b, label); }

//+------------------------------------------------------------------+
// Subclase de test que expone métodos internos para prueba de caja blanca
//+------------------------------------------------------------------+
class CRiskManagerTest : public CRiskManager
  {
public:
   int    GetConsecLosses()   { return(m_consecutiveLosses); }
   double GetSizeMultiplier() { return(GetPositionSizeMultiplier()); }

   // Resetea estado en memoria Y borra la GlobalVariable para evitar
   // contaminación entre tests en la misma sesión MT5
   void ResetState()
     {
      m_consecutiveLosses = 0;
      if(m_gvConsecLossKey != "") GlobalVariableDel(m_gvConsecLossKey);
     }
  };

//+------------------------------------------------------------------+
void OnStart()
  {
   Print("=== TestRiskManager BEGIN ===");

   CRiskManagerTest rm;
   // magic 0 para evitar colisiones de GlobalVariables en tests
   rm.Init(1.0, 4.0, 1, 350, 0, 3, 8.0);
   rm.ResetState();

   //--- Conteo de perdidas consecutivas
   rm.RegisterTradeResult(-10.0);
   AssertEqI(rm.GetConsecLosses(), 1, "ConsecLoss despues de 1 perdida");

   rm.RegisterTradeResult(-5.0);
   AssertEqI(rm.GetConsecLosses(), 2, "ConsecLoss despues de 2 perdidas");

   rm.RegisterTradeResult(-1.0);
   AssertEqI(rm.GetConsecLosses(), 3, "ConsecLoss despues de 3 perdidas");

   // Ganar resetea el contador
   rm.RegisterTradeResult(20.0);
   AssertEqI(rm.GetConsecLosses(), 0, "ConsecLoss reset tras ganancia");

   //--- Multiplicador de tamano de posicion
   rm.ResetState();
   AssertEq(rm.GetSizeMultiplier(), 1.0, "Multiplicador = 1.0 sin perdidas");

   rm.RegisterTradeResult(-1.0);
   AssertEq(rm.GetSizeMultiplier(), 1.0, "Multiplicador = 1.0 con 1 perdida");

   rm.RegisterTradeResult(-2.0);
   AssertEq(rm.GetSizeMultiplier(), 0.75, "Multiplicador = 0.75 con 2 perdidas");

   rm.RegisterTradeResult(-3.0);
   AssertEq(rm.GetSizeMultiplier(), 0.75, "Multiplicador = 0.75 con 3 perdidas");

   rm.RegisterTradeResult(5.0);   // win
   AssertEq(rm.GetSizeMultiplier(), 1.0, "Multiplicador vuelve a 1.0 tras ganancia");

   //--- Limite de perdidas consecutivas
   rm.ResetState();
   AssertFalse(rm.IsConsecutiveLossLimitReached(), "Limite NO alcanzado con 0 perdidas");

   rm.RegisterTradeResult(-1.0);
   rm.RegisterTradeResult(-2.0);
   AssertFalse(rm.IsConsecutiveLossLimitReached(), "Limite NO alcanzado con 2 perdidas");

   rm.RegisterTradeResult(-3.0);
   AssertTrue(rm.IsConsecutiveLossLimitReached(), "Limite alcanzado con 3 perdidas (InpMaxConsecLosses=3)");

   // Tras ganar, el limite se libera
   rm.RegisterTradeResult(10.0);
   AssertFalse(rm.IsConsecutiveLossLimitReached(), "Limite liberado tras ganancia");

   //--- Portfolio Risk Cap (v2.60) — funciones puras basadas en GlobalVariable
   {
      CRiskManagerTest rm2;
      rm2.Init(1.0, 4.0, 1, 350, 0, 3, 8.0);
      rm2.InitPortfolioCap(true, 1.5);

      // Limpieza previa: liberar tickets de prueba si quedaron de una corrida anterior
      rm2.ReleaseOpenRisk(90001);
      rm2.ReleaseOpenRisk(90002);
      AssertEq(rm2.GetPortfolioRiskUsed(), 0.0, "PortfolioRisk inicia en 0");

      rm2.RegisterOpenRisk(90001, 0.8);
      AssertEq(rm2.GetPortfolioRiskUsed(), 0.8, "PortfolioRisk tras 1er registro = 0.8%");
      AssertEq(rm2.GetAvailablePortfolioRisk(), 0.7, "Disponible = 1.5 - 0.8 = 0.7%");

      rm2.RegisterOpenRisk(90002, 0.5);
      AssertEq(rm2.GetPortfolioRiskUsed(), 1.3, "PortfolioRisk tras 2do registro = 1.3%");
      AssertEq(rm2.GetAvailablePortfolioRisk(), 0.2, "Disponible = 1.5 - 1.3 = 0.2%");

      rm2.ReleaseOpenRisk(90001);
      AssertEq(rm2.GetPortfolioRiskUsed(), 0.5, "PortfolioRisk tras liberar 90001 = 0.5%");

      rm2.ReleaseOpenRisk(90002);
      AssertEq(rm2.GetPortfolioRiskUsed(), 0.0, "PortfolioRisk tras liberar todo = 0.0%");

      // Liberar un ticket no registrado no debe romper nada ni ir negativo
      rm2.ReleaseOpenRisk(99999);
      AssertEq(rm2.GetPortfolioRiskUsed(), 0.0, "Liberar ticket inexistente no afecta el total");

      // Con el cap desactivado, Register/Release no deben tener efecto
      CRiskManagerTest rm3;
      rm3.Init(1.0, 4.0, 1, 350, 0, 3, 8.0);
      rm3.InitPortfolioCap(false, 1.5);
      rm3.RegisterOpenRisk(90003, 0.9);
      AssertEq(rm3.GetPortfolioRiskUsed(), 0.0, "Cap OFF: RegisterOpenRisk no acumula");
   }

   //--- Resumen
   Print("=== TestRiskManager END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
