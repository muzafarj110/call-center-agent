# MongoDB Setup (Atlas) — AIShop

The platform now stores everything in MongoDB instead of Google Sheets:

| Collection | Holds |
|------------|-------|
| `clients`   | client registry (config, phone_number_id, status, client_id) |
| `products`  | each client's catalog/menu/specialties (scoped by client_id) |
| `orders`    | orders / bookings / leads |
| `customers` | remembered names + addresses |
| `slots`     | available appointment times (clinics/hospitals) |

Data is scoped per client by a `client_id` (auto-generated at onboarding).

## 1. Create a free MongoDB Atlas cluster

1. Go to https://www.mongodb.com/cloud/atlas/register and sign up.
2. **Build a Database** → choose the **M0 Free** tier → pick a cloud/region near
   your Railway region → Create.
3. **Database Access** → Add New Database User → username + password (save these).
   Give it "Read and write to any database."
4. **Network Access** → Add IP Address → **Allow access from anywhere**
   (`0.0.0.0/0`). Railway's IPs aren't fixed, so this is required.
5. **Database → Connect → Drivers → Python** → copy the connection string. It
   looks like:
   ```
   mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
   Replace `USER`/`PASSWORD` with the user you created. (URL-encode special
   characters in the password.)

## 2. Set env vars on Railway

| Variable | Value |
|----------|-------|
| `MONGODB_URI` | the full connection string from step 1 |
| `MONGODB_DB`  | `aishop` (optional; this is the default) |
| `ONBOARD_KEY` | optional shared key clients must enter on the onboarding form |
| `ADMIN_SECRET`| protects /products writes, /orders, /clients, /reload-clients |

When `MONGODB_URI` is set, Mongo becomes the source of truth and the old
`CLIENTS_JSON` / Google Sheet config is ignored. You can also set these locally
in `.env` for testing.

## 3. Migrate Daily Fresh (one time)

Daily Fresh must exist in the `clients` collection or it stops routing. Easiest:
just re-onboard it through the form (or POST /onboard) with:
- business_type: `grocery`, business_name: `Daily Fresh Vegetables & Fruits L.L.C`
- products: paste the current product list ("Name - price" per line)
- phone_number_id: the Daily Fresh WhatsApp phone_number_id
- escalation_number: `971565893710`, language: Both

It'll be created as **active** and routable immediately.

## 4. Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /onboard` | create/update a client + seed products (form posts here) |
| `GET /clients` | list active clients (admin) |
| `GET /products?client_id=...` | list a client's products |
| `POST/PUT /products` | add/update a product `{client_id,name,price,unit,stock}` (admin) |
| `DELETE /products` | remove a product `{client_id,name}` (admin) |
| `GET /orders?client_id=...` | list a client's orders (admin) |
| `POST /update-order` | set order status `{order_id,status[,client_id]}` |
| `POST /reload-clients` | force registry reload from Mongo |

Admin-protected endpoints need header `X-Admin-Secret: <ADMIN_SECRET>` (only if
`ADMIN_SECRET` is set).

## 5. Local testing

```bash
pip install -r requirements.txt        # installs pymongo + dnspython
export MONGODB_URI="mongodb+srv://..."  # or put it in .env
python3 daily_fresh.py
curl http://127.0.0.1:5001/health
```

## Notes

- No more per-client Google Sheets — clients manage products via the dashboard /
  `/products` API (a management UI is the next build).
- `credentials.json` / `GOOGLE_CREDENTIALS_JSON` are no longer needed; you can
  remove them from Railway.
- Free M0 tier is fine to start; upgrade if you outgrow it.
