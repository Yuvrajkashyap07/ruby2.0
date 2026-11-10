# RUBY — Community Buying Network

RUBY combines local customer demand into community buying campaigns. Customers select a city and PIN-code area, add products to a shared campaign basket and track pooled quantities. Vendors submit supplier quotations. Operations manages locations, product catalogue, campaigns, orders and analytics.

## Included capabilities

- Customer, vendor and administrator workspaces with role-based sign-in.
- 28 Indian cities and 10 candidate PIN-code records per city (280 rows total). Location records start as inactive when sample data is disabled. Operations must confirm local postal records, collection-point capacity and actual delivery serviceability before activation.
- Product catalogue with 24 grocery and home-care products and bundled product imagery.
- City-based best-seller suggestions using paid local order history.
- City / PIN-based campaign baskets, pooled demand and campaign MOQ progress.
- Vendor applications, approval controls and supplier quotations with MOQ, capacity, price and lead time.
- Order commitment, operations status updates and CSV exports.
- Descriptive analytics for orders, sales, categories, cities and product demand.
- Customer segmentation using RFM features and K-Means.
- Campaign MOQ classification using Logistic Regression when historical campaign outcomes are sufficient.
- Product-demand quantity regression using a Random Forest model when paid order-line history is sufficient.
- Market-basket co-purchase analysis and supplier quote outlier review.
- Unit economics view using recorded product cost and selling price.

## Run locally

Python 3.12 is recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
streamlit run app.py
```

The default local configuration loads a reproducible sample dataset on first run. Sample accounts:

| Role | Email | Password |
|---|---|---|
| Administrator | admin@ruby.local | RubyAdmin#2026 |
| Customer | customer1@ruby.local | RubyCustomer#2026 |
| Vendor | vendor1@ruby.local | RubyVendor#2026 |

The sample records are fictional and are provided to make the screens and analytics usable immediately. They must not be mixed with customer or commercial records. Use a fresh database and disable sample seeding for a live instance.

## Deploy on Streamlit Community Cloud

1. Unzip this folder and upload the **contents** of `RUBY_Enhanced` into the root of a GitHub repository.
2. Open Streamlit Community Cloud and choose **Create app**.
3. Select the repository and branch, and set **Main file path** to `app.py`.
4. In **Advanced settings / Secrets**, configure a managed PostgreSQL database and a first administrator account. Example:

```toml
DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/ruby?sslmode=require"
SEED_SAMPLE_DATA = "false"
BOOTSTRAP_ADMIN_EMAIL = "admin@example.com"
BOOTSTRAP_ADMIN_PASSWORD = "a-long-random-password-at-least-10-characters"
BOOTSTRAP_ADMIN_NAME = "RUBY Operations"
```

5. Deploy. Sign in with the administrator credentials you configured.
6. Review the 280 PIN-code candidates and activate only the areas where RUBY has verified postal coverage, a working collection point and a practical fulfilment arrangement.
7. Approve suppliers, validate product details and prices, create campaigns and test customer / vendor / admin journeys using a separate test environment before accepting real orders.

**Do not commit `.streamlit/secrets.toml`, API credentials, database passwords or customer data to GitHub.** Streamlit Community Cloud supports secrets in the app settings; use that mechanism for deployment credentials.

## Database and data persistence

- A local SQLite database is used when `DATABASE_URL` is not configured.
- A managed PostgreSQL database is required for a shared instance. Streamlit Community Cloud does not guarantee local-file persistence.
- `SEED_SAMPLE_DATA=false` prevents fictional sample users, orders, campaigns and vendors from being loaded.
- The 280 PIN-code records are imported as inactive candidate coverage when the database is first initialised. Operations must activate the service areas only after validation.
- Make database backups and test restoration before handling real customer information.

## Analytics: method and minimum-data gates

| Method | RUBY use | Gate / caveat |
|---|---|---|
| Descriptive analysis | Orders, value, category, city, SKU and contribution summaries | Requires recorded transactions |
| K-Means clustering | RFM customer groups | At least 12 paying customers in the current implementation; segment labels are relative to the current population |
| Classification | Campaign reaches MOQ or not | At least 30 completed campaigns with pre-cutoff demand snapshots and both outcomes; uses the latest 20% of campaigns as a chronological holdout when both classes are present |
| Regression | Estimate typical quantity per order line | At least 60 paid historical order lines; uses the latest 20% of paid order lines as a chronological holdout |
| Market-basket mining | Products purchased together | Uses co-occurrence counts; results depend on order volume |
| Quote anomaly review | Unusual supplier prices relative to peers | A flag is a review signal, not proof of error |

For a real production decision, keep campaign snapshots over time, use chronological train/test splits, monitor model drift and compare every model against a simple baseline. Current validation is a small chronological holdout and should be treated as an early check, not final model certification. The current application deliberately does not fabricate a prediction where its data gate is not met.

## Operational and commercial controls

This repository provides the application workflow and a deployable Streamlit configuration. It is not a substitute for payment-gateway integration, formal supplier KYC, GST and invoicing review, customer terms, privacy notices, returns/refunds operations, food-safety checks where applicable, security testing or a production-scale load assessment. The current checkout records a customer commitment and does not charge a card or wallet. Integrate and test an approved payment provider and webhook flow before collecting online payments.

Streamlit Community Cloud is suitable for a controlled application and teaching / validation workloads, but its published compute limits and hibernation behaviour can affect a public consumer marketplace. Use a dedicated scalable service architecture before a high-volume commercial launch.

## PIN-code data note

The city/PIN dataset contains 280 curated six-digit candidate records to provide a structured launch footprint. The official Department of Posts / Open Government Data directory is the authoritative reference for validating current PIN-code, office, district and state details. The data.gov.in directory is updated periodically; postal presence by itself does not establish last-mile serviceability. The included localities and candidate PINs are marked for review and must be checked against the current directory and on-ground hub coverage before activation.

## Project structure

```text
RUBY_Enhanced/
├── app.py
├── core/
│   ├── analytics.py
│   ├── db.py
│   ├── security.py
│   └── seed.py
├── data/
│   ├── city_pincodes.csv
│   └── products.csv
├── assets/products/        # bundled product catalogue images
├── .streamlit/config.toml
├── .streamlit/secrets.toml.example
├── requirements.txt
└── runtime.txt
```
