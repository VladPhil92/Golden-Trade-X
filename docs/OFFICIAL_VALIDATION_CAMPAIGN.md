# Golden Trade X v3.0-rc1 — Official Validation Campaign

## Propósito

v3.0-rc1 introduce una raíz única de procedencia para la campaña cuantitativa oficial. La finalidad no es producir un PASS por software, sino impedir que un resultado OOS, de robustez o forward pueda promoverse si fue generado con políticas, candidatos, presets, builds, entornos MT5 o escenarios distintos de los pre-registrados.

Un resultado positivo de esta fase habilita únicamente **manual release review**. No autoriza trading real ni capital real.

La ejecución operativa IS→OOS está documentada en `docs/OFFICIAL_CAMPAIGN_EXECUTION.md`.

## Campaign lock

`scripts/official_campaign_freeze.py` genera `campaign_lock.json` y, en el mismo acto, materializa el `walk_forward_plan.json` determinista.

El lock congela antes de observar evidencia oficial:

- `campaign_id`;
- Git SHA exacto del build candidato, inyectable en freeze mediante `--build-id`;
- universo completo de candidatos y SHA-256 de cada preset;
- fingerprint canónico del universo de candidatos;
- execution environment DEMO exacto y sus hashes de archivo/semántica;
- configuración y plan walk-forward;
- SHA-256 de la policy de promoción OOS;
- template semántico de robustez;
- SHA-256 de la policy de robustez;
- SHA-256 de la policy forward demo.

Un lock es `OFFICIAL_CAMPAIGN_FROZEN` sólo cuando el execution environment y las tres policies están aprobados antes de ejecutar evidencia. `--allow-draft` existe exclusivamente para ingeniería y produce `ENGINEERING_DRAFT_NOT_OFFICIAL`; ese estado no puede pasar el gate rc1.

## Build SHA

El SHA del build puede suministrarse al freeze desde el checkout real:

```bash
python scripts/official_campaign_freeze.py \
  --config config/official_validation_campaign.json \
  --output-dir data/research/official_campaign/freeze \
  --build-id "$GITHUB_SHA"
```

Esto evita exigir que un archivo versionado contenga el SHA del mismo commit que lo contiene, una condición autorreferencial imposible. El SHA se fija antes de la primera observación y forma parte del campaign fingerprint.

Si el config ya declara un SHA real distinto del SHA suministrado al freeze, la operación falla. El SHA de cuarenta ceros usado por el template es sólo un placeholder explícito para ser sustituido por el SHA del checkout al congelar.

## Execution environment

`config/execution_environment.example.json` es únicamente un template DRAFT. Para una campaña oficial debe existir un archivo nuevo e inmutable con:

```text
approved=true
require_trade_mode=DEMO
live_trading_authorized=false
```

El contrato fija broker, account company/server, símbolo, timeframe, MT5 build, modelling, tester model, portable mode, capital, leverage y la semántica de costes declarada.

El lock incorpora:

```text
execution_environment.file_sha256
execution_environment.canonical_sha256
```

Por tanto, cambiar el entorno después del freeze invalida la identidad de la campaña.

Antes del primer backtest oficial `scripts/mt5_environment_probe.py` debe producir una attestation `VERIFIED` contra el terminal y la cuenta DEMO reales. Cuenta REAL, broker/server distinto, build distinto, símbolo distinto o falta de sincronización bloquean la ejecución.

## Universo de candidatos

La campaña oficial no permite cambiar el conjunto de alternativas entre folds. El fingerprint se calcula a partir de pares ordenados:

```text
candidate name + preset SHA-256
```

`walk_forward_aggregate.py` comprueba que todos los selection manifests de todos los folds tengan exactamente el mismo fingerprint. Añadir, eliminar, renombrar o sustituir un preset después de observar un fold invalida el agregado OOS.

Además, el freeze y el runner rechazan cualquier preset del universo que no conserve explícitamente:

```text
InpAllowRealTrading=false
```

## Ejecución rolling IS → frozen OOS

`scripts/official_campaign_runner.py` deriva todos los specs IS a partir de la misma combinación congelada de:

```text
Build + Execution Environment + Fold + Candidate Preset
```

No permite escoger un broker/model/build diferente por fold.

Para cada fold:

1. ejecuta todos los candidatos IS registrados;
2. exige report Strategy Tester real y normalizado;
3. selecciona usando exclusivamente la policy IS pre-registrada;
4. congela el preset ganador;
5. crea un experiment ID OOS distinto;
6. ejecuta OOS independientemente;
7. conserva hashes e identidades de toda la cadena.

Una preparación sin terminal queda marcada `PREPARED_NOT_EXECUTED` y no constituye evidencia económica.

Al terminar todos los folds se genera `oos_summary.json` y se aplica la policy de promoción cuyo hash fue congelado antes de OOS.

## Robustez pre-registrada

`config/robustness_template.example.json` separa las reglas que deben decidirse antes de conocer el candidato OOS definitivo:

- perturbaciones paramétricas one-change-at-a-time;
- brokers requeridos y mínimo de brokers distintos;
- escenarios de sensibilidad de costes modelados;
- prohibición de presentar metadata-only stress como ejecución MT5 real.

Después del OOS puede vincularse el `base_spec` del candidato congelado, pero no cambiar el template. El gate rc1 compara el plan de robustez ejecutado contra el template congelado y falla ante drift.

## End-to-end release review gate

`scripts/rc1_release_review_gate.py` recibe un bundle de artefactos y comprueba la cadena completa:

```text
Campaign Lock
    ↓
MT5 DEMO Environment Attestation
    ↓
Frozen Walk-Forward Plan
    ↓
IS Selection → Frozen OOS
    ↓
OOS Aggregate
    ↓
OOS Promotion Decision
    ↓
Robustness Plan / Summary / Decision
    ↓
Forward Demo Readiness
    ↓
Fixed-Window Forward Plan
    ↓
Forward Evidence
    ↓
Forward Gate
    ↓
RC1 Manual Release Review
```

Las verificaciones de release incluyen hashes de artefactos, candidate universe, policy hashes, experiment IDs, frozen preset, source fold, build ID y template de robustez. La attestation de entorno queda vinculada al campaign lock y al manifest de ejecución IS→OOS.

Las decisiones finales son:

- `RC1_EVIDENCE_NOT_PROMOTABLE`;
- `RC1_PASS_FOR_MANUAL_RELEASE_REVIEW`.

En ambos casos:

```text
live_trading_authorized=false
real_capital_authorized=false
```

## Secuencia operativa oficial

1. Crear archivos de policy nuevos, revisados e inmutables; no convertir silenciosamente los ejemplos DRAFT en evidencia oficial.
2. Definir el universo completo de candidatos antes del primer IS run.
3. Crear y aprobar un execution environment DEMO exacto.
4. Definir broker labels y escenarios reales del robustness template.
5. Fijar el Git SHA exacto en el acto de freeze.
6. Ejecutar `official_campaign_freeze.py` sin `--allow-draft`.
7. Ejecutar y verificar la attestation del entorno DEMO.
8. Ejecutar cada fold IS con exactamente el universo congelado.
9. Seleccionar y congelar OOS usando únicamente evidencia IS.
10. Ejecutar todos los OOS folds y agregarlos; el agregador debe conservar el candidate-universe fingerprint.
11. Aplicar el promotion gate con la policy congelada.
12. Si pasa, vincular el OOS seleccionado como baseline y ejecutar el robustness template congelado.
13. Aplicar robustness gate.
14. Generar forward-demo readiness.
15. Registrar una ventana forward futura antes de observar resultados.
16. Ejecutar exclusivamente en DEMO y evaluar la ventana completa.
17. Aplicar forward-demo gate.
18. Ejecutar `rc1_release_review_gate.py` sobre el bundle completo.
19. Si pasa, abrir revisión manual del release candidate. No habilitar capital real automáticamente.

## Qué no resuelve esta fase

- No genera por sí misma evidencia económica.
- No sustituye Strategy Tester real, broker replication ni forward demo real.
- No convierte thresholds ilustrativos en criterios oficiales.
- No demuestra rentabilidad futura.
- No autoriza producción ni modifica `InpAllowRealTrading`.

La campaña oficial empieza únicamente cuando existe un `OFFICIAL_CAMPAIGN_FROZEN` generado con execution environment y policies aprobados, un build inmutable y una attestation DEMO válida.
