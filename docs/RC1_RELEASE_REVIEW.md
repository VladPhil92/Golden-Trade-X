# RC1 Release Review Gate

El gate `scripts/rc1_release_review_gate.py` audita una campaña v3.0-rc1 completa contra el `campaign_lock.json` original.

Uso:

```bash
python scripts/rc1_release_review_gate.py \
  --bundle config/rc1_release_bundle.example.json \
  --output data/research/official_campaign/rc1_release_review.json \
  --require-pass
```

El bundle sólo contiene rutas a evidencia ya generada. No recalcula resultados de trading ni corrige evidencia incompleta.

Un PASS significa exclusivamente que la cadena OOS → robustez → forward cumple la procedencia y los gates pre-registrados necesarios para abrir una revisión manual del release candidate.

No autoriza live trading y no habilita capital real.
