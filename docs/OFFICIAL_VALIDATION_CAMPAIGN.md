# Golden Trade X v3.0-rc1 — Official Validation Campaign

## Propósito

v3.0-rc1 introduce una raíz única de procedencia para la campaña cuantitativa oficial. La finalidad no es producir un PASS por software, sino impedir que un resultado OOS, de robustez o forward pueda promoverse si fue generado con políticas, candidatos, presets, builds o escenarios distintos de los pre-registrados.

Un resultado positivo de esta fase habilita únicamente **manual release review**. No autoriza trading real ni capital real.

## Campaign lock

`scripts/official_campaign_freeze.py` genera `campaign_lock.json` y, en el mismo acto, materializa el `walk_forward_plan.json` determinista.

El lock congela antes de observar evidencia oficial:

- `campaign_id`;
- Git SHA exacto del build candidato;
- universo completo de candidatos y SHA-256 de cada preset;
- fingerprint canónico del universo de candidatos;
- configuración y plan walk-forward;
- SHA-256 de la policy de promoción OOS;
- template semántico de robustez;
- SHA-256 de la policy de robustez;
- SHA-256 de la policy forward demo.

Un lock es `OFFICIAL_CAMPAIGN_FROZEN` sólo cuando las tres policies están aprobadas antes de ejecutar evidencia. `--allow-draft` existe exclusivamente para ingeniería y produce `ENGINEERING_DRAFT_NOT_OFFICIAL`; ese estado no puede pasar el gate rc1.

## Universo de candidatos

La campaña oficial no permite cambiar el conjunto de alternativas entre folds. El fingerprint se calcula a partir de pares ordenados:

```text
candidate name + preset SHA-256
```

`walk_forward_aggregate.py` comprueba que todos los selection manifests de todos los folds tengan exactamente el mismo fingerprint. Añadir, eliminar, renombrar o sustituir un preset después de observar un fold invalida el agregado OOS.

Además, el freeze rechaza cualquier preset del universo que no declare explícitamente:

```text
InpAllowRealTrading=false
```

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

Las verificaciones incluyen hashes de artefactos, candidate universe, policy hashes, experiment IDs, frozen preset, source fold, build ID y template de robustez.

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
3. Definir broker labels y escenarios reales del robustness template.
4. Fijar el Git SHA exacto del build candidato.
5. Ejecutar `official_campaign_freeze.py` sin `--allow-draft`.
6. Ejecutar cada fold IS con exactamente el universo congelado.
7. Seleccionar y congelar OOS usando únicamente evidencia IS.
8. Ejecutar todos los OOS folds y agregarlos; el agregador debe conservar el candidate-universe fingerprint.
9. Aplicar el promotion gate con la policy congelada.
10. Vincular el OOS seleccionado como baseline y ejecutar el robustness template congelado.
11. Aplicar robustness gate.
12. Generar forward-demo readiness.
13. Registrar una ventana forward futura antes de observar resultados.
14. Ejecutar exclusivamente en DEMO y evaluar la ventana completa.
15. Aplicar forward-demo gate.
16. Ejecutar `rc1_release_review_gate.py` sobre el bundle completo.
17. Si pasa, abrir revisión manual del release candidate. No habilitar capital real automáticamente.

## Qué no resuelve esta fase

- No genera por sí misma evidencia económica.
- No sustituye Strategy Tester real, broker replication ni forward demo real.
- No convierte thresholds ilustrativos en criterios oficiales.
- No demuestra rentabilidad futura.
- No autoriza producción ni modifica `InpAllowRealTrading`.

La campaña oficial empieza únicamente cuando existe un `OFFICIAL_CAMPAIGN_FROZEN` generado con policies aprobadas y un build inmutable.
