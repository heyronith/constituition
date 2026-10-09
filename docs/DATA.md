# Data locations and backups

## Main-run raw chains (`main_v1`)

Authoritative copy: Modal Volume `rc-runs` under `main_v1/<config>/…` (840 chains).

### Session 2 packages (D55 rule 6)

Per-config `.tar.gz` of all `rounds.jsonl`, `constitutions.jsonl`, `lineage.jsonl`, `meta.json` files under each config (480 files/config = 120 chain dirs × 4).

| Package | Bytes | SHA-256 |
|---------|------:|---------|
| `olmo3_7b_final.tar.gz` | 1,444,142 | `5416b72cdc18634e19c10018795fd4f47022bdb8acd3c385bf034b7b09b0f405` |
| `qwen38_27b_nothink.tar.gz` | 1,844,024 | `ddf1e69b77446a0f0574a6ba4637ac24f66a548ed4f44d9d88adb06335e785c3` |
| `qwen38_27b_think.tar.gz` | 7,106,147 | `847382ded2ea18965c9f551bd51287595e7b0e5ecc0583cf9cee1ec6645010bf` |
| `gemma4_31b.tar.gz` | 1,572,853 | `c66452e7d6c93f0c576a88cd8ea6c6b721111bbbc1e7d3cefc871702f6c06e97` |
| `gemma4_12b.tar.gz` | 1,498,741 | `8a30cf6e881cb9d1d91b4be135f78a05bdf91f9464e693febda3f952d9e3358b` |
| `olmo3_7b_sft.tar.gz` | 1,413,063 | `6066c1eee68973ec4d6664c9a1d9de5ac05dca819bc451f57b13f792a8ae961c` |
| `olmo3_7b_dpo.tar.gz` | 1,709,921 | `abd6da6f52f0644b53d909847d02c9cf720b3ef19f719571fa403c36b3003fdd` |

**Locations:**

- Modal Volume: `rc-runs/backups_main_v1/<config>.tar.gz`
- Local (not committed): `results/backups_main_v1/` + `SHA256SUMS`

**Hugging Face private dataset:** target `ronithsharmila/rc-main-v1-raw` (and org fallback `predictfordecision/rc-main-v1-raw`). Upload **blocked** in Session 2: existing `HF_TOKEN` is **read-only** (`403` on `repos/create`). Packages remain on the Volume and local disk until a write-capable token is provided; no token values are committed.

## H3 battery

- Installed constitutions: `materials/main_run/h3_constitutions.json` (266)
- Dedup map (D74): `materials/main_run/h3_dedup_map.json` (191 distinct systems)
- 7D responses: Volume `rc-runs/main_v1_7d/<config>/`
