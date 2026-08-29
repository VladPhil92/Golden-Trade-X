# Golden Trade X v3.0-rc1 — Official Campaign Execution

## Objetivo

Esta fase convierte el campaign lock de v3.0-rc1 en una ejecución reproducible de la secuencia:

```text
Frozen build + candidates + policies + MT5 environment
                         ↓
              Runtime DEMO attestation
                         ↓
                 Rolling IS execution
                         ↓
             IS-only candidate selection
                         ↓
                   Frozen OOS run
                         ↓
                 OOS aggregation
                         ↓
              Frozen promotion policy
                         ↓
            Robustness phase or rejection
```

El runner termina en la frontera de promoción OOS. No ejecuta automáticamente robustez, forward demo ni producción. Esto mantiene separados los gates metodológicos y evita que una sola automatización pueda promover una estrategia hasta capital real.

En toda salida de esta fase:

```text
live_trading_authorized=false
real_capital_authorized=false
```

## 1. Execution environment contract

`config/execution_environment.example.json` define el contrato que debe reemplazarse por un archivo nuevo e inmutable antes de la campaña real.

El contrato congela:

- identificador del entorno;
- `approved=true` sólo después de revisión humana;
- `require_trade_mode=DEMO`;
- broker label canónico;
- `ACCOUNT_COMPANY` esperado;
- `ACCOUNT_SERVER` esperado;
- símbolo exacto;
- timeframe;
- build exacto de MetaTrader 5;
- semántica de modelling;
- código numérico del tester model;
- Expert compilado;
- execution mode;
- portable mode;
- capital inicial y divisa;
- leverage;
- semántica declarada de spread, commission y swap;
- slippage metadata;
- `optimization=false`;
- MT5 forward mode deshabilitado.

Un contrato aprobado no admite `REPLACE_WITH`, `PLACEHOLDER`, `TBD` ni `UNKNOWN` en los identificadores críticos.

El entorno oficial exige siempre:

```text
require_trade_mode=DEMO
live_trading_authorized=false
```

## 2. Build SHA sin autorreferencia imposible

Un archivo versionado no puede contener de forma estable el SHA del mismo commit que lo contiene: editar el archivo altera el commit y por tanto altera el SHA.

Por eso `official_campaign_freeze.py` admite:

```bash
--build-id <FULL_40_HEX_GIT_SHA>
```

En GitHub Actions se inyecta `GITHUB_SHA` en el instante del freeze, antes de producir evidencia. Ese SHA queda dentro de `campaign_lock.json` y del `campaign_fingerprint`.

Si el config ya contiene un SHA explícito distinto del SHA inyectado, el freeze falla. El valor de cuarenta ceros se reserva como placeholder del template y sólo puede convertirse en un build real mediante el override explícito.

## 3. Qué incorpora ahora el campaign fingerprint

Además de candidatos, walk-forward y policies, el lock congela:

```text
execution_environment.file_sha256
execution_environment.canonical_sha256
```

Por tanto, cambiar posteriormente broker, servidor, símbolo, MT5 build, tester model, capital, leverage o cualquier otro campo del contrato produce una campaña distinta.

## 4. Runtime attestation

`scripts/mt5_environment_probe.py` se ejecuta en Windows contra la instalación real de MetaTrader.

Las credenciales se leen únicamente desde variables de entorno:

```text
GTX_MT5_LOGIN
GTX_MT5_PASSWORD
GTX_MT5_SERVER
```

La contraseña no se materializa en los artefactos de campaña.

El probe usa la API Python de MetaTrader 5 para observar, como mínimo:

- trade mode de la cuenta;
- account company;
- account server;
- account currency;
- símbolo efectivo;
- build del terminal;
- estado de conexión;
- disponibilidad/sincronización del símbolo;
- digits y point;
- contract size;
- tick size y tick value;
- profit currency.

La attestation sólo recibe estado:

```text
VERIFIED
```

si coinciden exactamente con el contrato congelado los campos safety-critical y la cuenta es DEMO.

Una cuenta REAL, un servidor distinto, otro broker company, otro símbolo o un build distinto bloquean la campaña antes del primer Strategy Tester run oficial.

## 5. Preparación determinista del walk-forward

`scripts/official_campaign_runner.py` tiene dos modos.

### Prepare-only

Sin `--terminal`, genera:

```text
data/research/official_campaign/execution/
  campaign_execution_manifest.json
  folds/
    WF001/
      is_execution_set.json
      is/
        presets/
        specs/
    WF002/
      ...
```

Cada spec IS se deriva exclusivamente de:

```text
Campaign Lock
+ Frozen Execution Environment
+ Frozen Walk-Forward Fold
+ Frozen Candidate Preset
```

No se permite que cada fold elija broker, build, model, capital o leverage independientemente.

`PREPARED_NOT_EXECUTED` significa exactamente eso: no es evidencia económica ni un backtest completado.

## 6. Ejecución oficial IS → OOS

Con un terminal real, el runner procesa cada fold secuencialmente.

Para cada candidato IS:

1. copia los bytes exactos del preset congelado;
2. verifica nuevamente su SHA-256;
3. coloca el preset en `Profiles/Tester`;
4. registra la identidad de experimento;
5. ejecuta `strategy_tester_harness.py`;
6. exige report HTML real y no vacío;
7. normaliza las métricas del report;
8. exige estado `COMPLETED`.

Sólo después de completar todos los candidatos del fold se construye el `is_evidence_manifest.json`.

## 7. Selección estrictamente IS

El runner llama a `walk_forward_selector.py` con el plan y la evidencia IS del fold.

El selector:

- verifica comparabilidad de provenance;
- aplica exclusivamente constraints y ranking pre-registrados;
- congela los bytes del preset ganador;
- crea un spec OOS con un experiment ID nuevo;
- no utiliza información OOS durante la selección.

Después el runner ejecuta ese spec OOS de forma independiente.

## 8. Agregación y promotion gate

Cuando todos los folds tienen OOS ejecutado:

```text
oos_evidence_manifest.json
        ↓
walk_forward_aggregate.py
        ↓
oos_summary.json
        ↓
promotion_gate.py
        ↓
oos_promotion_decision.json
```

El agregador vuelve a comprobar que el candidate-universe fingerprint sea el mismo en todos los folds y que coincida con el campaign lock.

El promotion gate sólo puede usar la policy cuyo SHA-256 fue congelado antes de OOS.

Resultados de esta etapa:

```text
OOS_PROMOTION_PASS_READY_FOR_ROBUSTNESS
OOS_PROMOTION_REJECTED
FAILED
```

Un PASS significa únicamente que puede comenzar la campaña de robustez congelada.

## 9. Workflow oficial de GitHub Actions

`.github/workflows/official-validation-campaign.yml` es manual (`workflow_dispatch`). No se dispara con cada commit ni con cada PR.

Requiere un config real, por ejemplo:

```text
config/official_validation_campaign.json
```

Los `.example.json` permanecen DRAFT y deben fallar si se intentan usar como campaña oficial.

El workflow realiza, en orden:

1. valida rutas y timeout;
2. congela la campaña con el `GITHUB_SHA` actual;
3. instala MetaTrader y compila el EA;
4. resuelve el data root real;
5. comprueba que `portable_mode` coincida con el contrato;
6. realiza runtime attestation contra la cuenta DEMO;
7. ejecuta la campaña IS→OOS;
8. agrega OOS y aplica el promotion gate;
9. publica todos los artefactos, incluso si la campaña falla.

## 10. Secrets requeridos

El workflow espera secrets de repositorio o environment:

```text
GTX_MT5_LOGIN
GTX_MT5_PASSWORD
GTX_MT5_SERVER
```

Deben corresponder a la cuenta DEMO declarada en el contrato. Si faltan, el probe falla cerrado.

No deben configurarse credenciales de una cuenta REAL para esta fase.

## 11. Casos que invalidan la campaña

Entre otros:

- campaña DRAFT;
- execution environment no aprobado;
- placeholder en contrato aprobado;
- policy no aprobada;
- build SHA distinto;
- candidate universe mutado;
- preset mutado después del freeze;
- `InpAllowRealTrading` distinto de `false`;
- terminal en cuenta REAL;
- account company o server distinto;
- MT5 build distinto;
- símbolo distinto/no disponible;
- portable mode distinto;
- report Strategy Tester ausente;
- report no normalizable;
- experiment ID distinto del precomputado;
- cambio de policy después del freeze.

## 12. Frontera de evidencia

La existencia del workflow, un CI verde o un campaign manifest preparado no demuestra edge.

La primera evidencia económica oficial existe únicamente cuando MetaTrader ha ejecutado los Strategy Tester runs registrados y cada uno produce report real normalizado.

La promoción OOS tampoco demuestra rentabilidad futura. Sólo permite continuar a:

```text
Robustness Validation
    ↓
Forward DEMO
    ↓
RC1 Manual Release Review
```

La autorización de capital real permanece fuera de esta automatización.
