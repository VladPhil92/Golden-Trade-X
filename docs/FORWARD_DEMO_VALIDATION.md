# Golden Trade X v2.90.4 — Forward Demo Validation

## Propósito

v2.90.4 convierte el paso desde evidencia OOS/robustez hacia observación forward demo en una cadena auditable y fail-closed. No autoriza capital real. Un resultado positivo sólo puede habilitar revisión de release posterior.

## Cadena de evidencia

1. `forward_demo_readiness.py` une el PASS del rolling frozen OOS con el PASS de robustez y exige que ambos correspondan al mismo `experiment_id` y al mismo frozen preset SHA-256.
2. `forward_demo_planner.py` fija antes de observar resultados:
   - candidato exacto;
   - bytes exactos del frozen preset;
   - SHA-256 de la policy forward;
   - Git SHA del build que se ejecutará en demo;
   - cuenta, broker, símbolo y timeframe;
   - ventana UTC de inicio y fin;
   - fingerprint esperado de la configuración efectiva de runtime.
3. `ResearchTelemetry.mqh` emite `START`, heartbeats horarios y `END` en `GoldenTradeX_sessions_*.csv` con candidato, build, broker, modo de cuenta, build de terminal y snapshot canónico de inputs de trading/riesgo.
4. `telemetry_db.py` ingiere el ledger de sesiones y calcula SHA-256 del snapshot de configuración.
5. `forward_demo_evaluator.py` verifica la ventana pre-registrada, continuidad de heartbeats, ausencia de drift y suficiencia de trades cerrados; después calcula métricas descriptivas de la evidencia forward.
6. `forward_demo_gate.py` aplica exclusivamente la policy cuyo SHA quedó congelado en el plan.

## Ventana fija y prevención de selección post hoc

La campaña debe declarar `observation_start_utc` y `observation_end_utc` antes de ejecutarse. El evaluador no permite escoger posteriormente una subventana favorable. Los gaps entre el inicio planificado, heartbeats consecutivos y el final planificado deben quedar dentro de `maximum_heartbeat_gap_seconds`.

## Fingerprint de configuración

El EA serializa en orden determinista todos los inputs que pueden afectar señal, sizing, guards de ejecución o gestión de posiciones. Logging y labels de procedencia no forman parte de ese fingerprint porque no deben cambiar la lógica de trading.

`forward_demo_planner.py` deriva el mismo snapshot desde el frozen `.set`. Si los bytes del preset no coinciden con el SHA del candidato OOS, el plan falla. Durante la observación, cualquier `config_sha256` diferente invalida la evidencia.

## Provenance fail-closed

Toda fila de sesión dentro de la ventana debe conservar exactamente:

- `CandidateID`;
- `BuildID`;
- cuenta y magic number;
- broker;
- símbolo;
- timeframe;
- `TradeMode=DEMO`;
- configuration SHA-256.

La policy también puede exigir un único MetaTrader terminal build durante toda la campaña. Un cambio de cualquiera de estas identidades no se promedia ni se ignora: invalida la evidencia.

## Métricas forward calculadas

El evaluador calcula únicamente a partir de `position_outcomes` cerrados dentro de la ventana fija:

- closed trades;
- net PnL;
- total realized R;
- expectancy en R;
- profit factor en R cuando existe gross loss;
- win rate;
- closed-trade maximum drawdown en R.

También reporta slippage absoluto observado para aperturas `SERVER_CONFIRMED`. El drawdown reportado es de la secuencia de trades cerrados; no pretende representar intra-trade equity drawdown.

## Policy y decisiones

La policy de ejemplo está deliberadamente en `approved=false`. Sus cifras son ilustrativas y no son criterios oficiales. Una policy oficial debe revisarse y congelarse antes de iniciar la campaña.

Decisiones posibles del gate:

- `BLOCKED_POLICY_UNAPPROVED`;
- `FORWARD_DEMO_FAIL`;
- `FORWARD_DEMO_PASS_FOR_RELEASE_REVIEW`.

En todos los casos `live_trading_authorized=false`.

## Limitaciones que permanecen

- El ledger de outcomes se asocia a la campaña por cuenta + magic + símbolo + ventana temporal. La integridad de sesiones bloquea drift en ese mismo ámbito, pero v2.90.4 no introduce un `CampaignID` dentro de cada outcome.
- La sensibilidad de costos de v2.90.3 sigue siendo modelada cuando el Strategy Tester no materializa esos costos como ejecución real.
- Ningún PASS forward demuestra rentabilidad futura ni sustituye una decisión de riesgo para producción.

## Secuencia operativa oficial

1. Completar OOS frozen y robustez.
2. Generar readiness positivo.
3. Aprobar/fijar policy forward.
4. Generar plan con ventana futura y Git SHA exacto del build demo.
5. Configurar `InpResearchCandidateId` y `InpResearchBuildId` con las identidades congeladas.
6. Ejecutar exclusivamente en cuenta DEMO durante toda la ventana.
7. Ingerir ledgers a SQLite.
8. Ejecutar evaluator.
9. Ejecutar gate con la misma policy por hash.
10. Si pasa, abrir únicamente revisión del siguiente release candidate; no habilitar live trading.
