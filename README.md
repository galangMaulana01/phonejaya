# JAYAPONA Backend — Vercel Serverless

Backend FastAPI untuk Sistem Manajemen Toko HP Bekas JAYAPONA.
Dioptimalkan untuk deployment di **Vercel** menggunakan Mangum.

## Stack
- FastAPI + Mangum (serverless adapter)
- MongoDB Atlas (via Motor async)
- bcrypt (password hashing — kompatibel Vercel)
- JWT (python-jose)

## Role & Akses
| Role | Akses |
|------|-------|
| **owner** | Semua fitur |
| **kasir** | Stok, Transaksi, Tambah Unit, Customer |
| **teknisi** | Data Service, Input & Update Service |

## Cara Deploy ke Vercel

### 1. Clone & setup environment
```bash
cp .env.example .env
# Edit .env isi MONGO_URI & JWT_SECRET
```

### 2. Seed database (jalankan dari lokal)
```bash
pip install motor bcrypt python-dotenv
python scripts/seed.py
```

### 3. Push ke GitHub
```bash
git init && git add . && git commit -m "init"
git remote add origin https://github.com/USERNAME/REPO.git
git push -u origin main
```

### 4. Deploy di Vercel
1. Login vercel.com → New Project → import repo
2. **Framework Preset:** Other
3. **Root Directory:** `.` (root)
4. Tambah Environment Variables:
   - `MONGO_URI` = connection string Atlas
   - `MONGO_DB` = `jayapona`
   - `JWT_SECRET` = random string panjang
   - `APP_ENV` = `production`
   - `CORS_ORIGINS` = `*`
5. Deploy

### 5. Update BACKEND_URL di frontend
Buka `index.html`, ubah baris:
```javascript
window.BACKEND_URL = 'https://nama-project.vercel.app/api/v1';
```

## API Endpoints
| Method | Path | Role |
|--------|------|------|
| POST | `/api/v1/auth/login` | Public |
| GET | `/api/v1/auth/me` | All |
| GET/POST | `/api/v1/units` | All/Kasir+ |
| PUT | `/api/v1/units/{id}` | Kasir+ |
| GET/POST | `/api/v1/transaksi` | Kasir+ |
| GET/POST | `/api/v1/karyawan` | Owner |
| GET | `/api/v1/dashboard/stats` | Owner |
| GET | `/api/v1/log` | Owner |
| GET/POST/PUT | `/api/v1/service` | Teknisi+ |
| POST | `/api/v1/service/{id}/foto` | Teknisi+ |
| GET/POST | `/api/v1/customers` | Kasir+ |
| GET | `/health` | Public |

## Akun Default (setelah seed)
- Owner : `owner` / `owner123`
- Kasir : `andi` / `andi123`
- Teknisi : `teknisi` / `teknisi123`
