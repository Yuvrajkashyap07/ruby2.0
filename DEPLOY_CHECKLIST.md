# Deployment checklist

## Before GitHub upload
- [ ] Upload the contents of this folder, not the outer ZIP directory.
- [ ] Keep `.streamlit/secrets.toml` out of Git.
- [ ] Confirm `app.py`, `requirements.txt`, `runtime.txt`, `.streamlit/config.toml`, `core/`, `data/` and `assets/` are at repository root.

## Streamlit configuration
- [ ] Main file path: `app.py`.
- [ ] Use a managed PostgreSQL database and a fresh database/schema.
- [ ] Set `SEED_SAMPLE_DATA = "false"`.
- [ ] Set a unique bootstrap admin email and a long password.
- [ ] Save credentials in Community Cloud Secrets, not in GitHub.

## Before the first real customer
- [ ] Validate all city/PIN candidates against the latest Department of Posts directory.
- [ ] Verify a collection point, capacity and fulfilment process for every active service area.
- [ ] Verify vendors, business registrations, product grade, MRP, supplier price and tax treatment.
- [ ] Add customer terms, privacy notice, consent and support / cancellation / returns process.
- [ ] Configure and test a payment provider and verified webhook before collecting online money.
- [ ] Test backups, restoration, concurrency, account controls and all role-specific journeys.
- [ ] Keep a separate environment for testing and training.
