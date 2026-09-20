# Local Official XM Campaign

GitHub-hosted Windows runners can install and compile MetaTrader 5 but may fail
to establish terminal IPC with error `-10005 IPC timeout`.

For XM official validation, the supported fallback is to run the frozen campaign
on the user's Windows machine against the already logged-in XM DEMO session.

## Safety boundary

The local runner:

- does not request or persist the MT5 account password;
- requires the current MT5 session to be DEMO;
- revalidates broker/server/currency/leverage/build/symbol contract metadata;
- preserves `InpAllowRealTrading=false`;
- preserves `live_trading_authorized=false`;
- preserves `real_capital_authorized=false`.

## Entry point

From the repository root with exactly one XM MT5 terminal open:

    .\scripts\run-local-official-campaign.ps1

Default campaign:

    config/official_validation_campaign.xm_gold.json

BTCUSD can be selected explicitly:

    .\scripts\run-local-official-campaign.ps1 -CampaignConfig config/official_validation_campaign.xm_btcusd.json

## Methodology

The local runner retains the official evidence sequence:

    pre-campaign readiness
      -> campaign freeze at current Git SHA
      -> frozen Python runtime
      -> local DEMO runtime context
      -> exact EA compilation
      -> broker environment attestation
      -> rolling IS candidate evaluation
      -> IS-only winner freeze
      -> frozen OOS execution
      -> OOS aggregation and promotion gate
      -> L4 evidence integrity validation
      -> ZIP evidence bundle

The resulting local evidence remains validation evidence only and does not
authorize live trading or real capital.
