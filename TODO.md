# Zil TODO

Pending improvements to be implemented in future releases.

## Deploy

- [x] Add `--cpu` CLI flag to `zil deploy` for explicit CPU control (done, unreleased)
- [ ] Validate CPU/memory compatibility before calling `gcloud run deploy`
  - Cloud Run constraints: 1 CPU ≤ 4Gi, 2 CPU ≤ 8Gi, 4 CPU ≤ 16Gi, 8 CPU ≤ 32Gi
  - Fail early with a helpful message instead of letting gcloud reject it
- [ ] Release 0.1.18 with `--cpu` flag so `zil-runtime` can drop the `>=0.1.17` pin
