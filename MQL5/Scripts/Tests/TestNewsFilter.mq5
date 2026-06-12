//+------------------------------------------------------------------+
//|                                              TestNewsFilter.mq5  |
//|   Golden Trade X — Tests unitarios para CNewsFilter              |
//+------------------------------------------------------------------+
//  Ejecución: arrastrar el script al gráfico en MetaEditor/MT5.
//  El resultado aparece en la pestaña Experts del Journal.
//  Código de salida:
//    "PASS" — todos los asserts superados
//    "FAIL" — al menos uno falló (ver detalle en Journal)
//+------------------------------------------------------------------+
#property script_show_inputs false
#include <GoldenTradeX/NewsFilter.mqh>

//--- Mini-framework de asserts
static int g_pass = 0;
static int g_fail = 0;

void AssertTrue(bool cond, string label)
  {
   if(cond) { g_pass++; Print("  PASS  ", label); }
   else     { g_fail++; Print("  FAIL  ", label); }
  }

void AssertFalse(bool cond, string label)
  {
   AssertTrue(!cond, label);
  }

//--- Construye una datetime desde componentes (año, mes, día, hora, min, seg)
datetime MakeTime(int year, int mon, int day, int hour, int min, int sec = 0)
  {
   MqlDateTime s;
   s.year = year; s.mon = mon; s.day = day;
   s.hour = hour; s.min = min; s.sec = sec;
   s.day_of_week = 0; s.day_of_year = 0;
   return(StructToTime(s));
  }

//+------------------------------------------------------------------+
void OnStart()
  {
   Print("=== TestNewsFilter BEGIN ===");

   CNewsFilter f;
   // offset UTC+2 (EET verano) — servidor = UTC + 2
   f.Init(true, 30, 90);
   f.SetServerOffset(2);

   //--- NFP: primer viernes del mes, 13:30 UTC → servidor 15:30
   // 2026-01-02 es viernes y es el primer viernes del año
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,2, 15,30)), "NFP: justo en el evento");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,2, 15,10)), "NFP: ventana previa -20min");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,2, 17, 0)), "NFP: ventana posterior +90min");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,1,2, 14,59)), "NFP: justo antes de ventana");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,1,2, 17, 1)), "NFP: justo despues de ventana");

   // Segundo viernes del mes — NO es NFP
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,1,9, 15,30)), "No-NFP: 2do viernes");

   //--- FOMC 2026: Jan 28 a las 19:00 UTC → servidor 21:00
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,28, 21, 0)), "FOMC: justo en el evento");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,28, 20,35)), "FOMC: ventana previa -25min");
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,1,28, 22,30)), "FOMC: ventana posterior +90min");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,1,28, 20,29)), "FOMC: antes de ventana");
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,1,28, 22,31)), "FOMC: despues de ventana");
   // Día no-FOMC
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,1,27, 21, 0)), "No-FOMC: dia incorrecto");

   //--- FOMC 2025: verificar algunas fechas clave
   // offset UTC+3 (EET invierno) para fechas de enero
   f.SetServerOffset(3);
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,1,29, 22, 0)), "FOMC 2025 Jan: servidor UTC+3");
   f.SetServerOffset(2);
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2025,12,10, 21, 0)), "FOMC 2025 Dic: servidor UTC+2");

   //--- CPI proxy: martes/miércoles del 10-15, 13:30 UTC → servidor 15:30
   // 2026-02-11 es miércoles (day_of_week==3), día 11
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,2,11, 15,30)), "CPI: miercoles d11");
   // 2026-03-10 es martes (day_of_week==2), día 10
   AssertTrue (f.IsNewsBlockedAt(MakeTime(2026,3,10, 15,30)), "CPI: martes d10");
   // día fuera de rango
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,2,16, 15,30)), "CPI: dia 16 fuera de rango");
   // jueves dentro del rango
   AssertFalse(f.IsNewsBlockedAt(MakeTime(2026,2,12, 15,30)), "CPI: jueves en rango — no aplica");

   //--- Filtro desactivado: debe devolver false siempre
   CNewsFilter fOff;
   fOff.Init(false, 30, 90);
   fOff.SetServerOffset(2);
   AssertFalse(fOff.IsNewsBlockedAt(MakeTime(2026,1,2,  15,30)), "disabled: NFP ignorado");
   AssertFalse(fOff.IsNewsBlockedAt(MakeTime(2026,1,28, 21, 0)),  "disabled: FOMC ignorado");

   //--- Resumen
   Print("=== TestNewsFilter END | PASS=", g_pass, " FAIL=", g_fail, " ===");
   if(g_fail == 0) Print(">>> ALL TESTS PASSED <<<");
   else            Print(">>> ", g_fail, " TEST(S) FAILED <<<");
  }
//+------------------------------------------------------------------+
