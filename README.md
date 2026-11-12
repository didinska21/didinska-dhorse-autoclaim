# DarkHorse Genesis — Bot Auto Claim Horseshoes

Reward mining di `genesis.dhorse.fun/mine` **hangus tiap akhir ronde**
(72 blok BTC, ±12 jam) kalau belum di-Claim. Bot ini memantau halaman
mining dengan sesi login X kamu dan menekan **Claim** otomatis begitu
claimable ≥ 1 Horseshoe — jadi tidak kelewat / ke-burn lagi.

Analisa lengkap situsnya (gaya REA): lihat `ANALYSIS.md`.

## Cara kerja

Bot memakai **API resmi situs itu sendiri** (ketemu dari JS bundle
resminya, lihat `ANALYSIS.md`):

- `GET /api/mining/status` → `claimable, blocksLeft, tipHeight, dailyRate, …`
- `POST /api/mining/claim` (body `{}`) → `{claimed: jumlah}`

Panggilan dilakukan dari dalam halaman `/mine` yang sedang login
(fetch same-origin, cookie sesimu sendiri — persis cara UI resminya).
Kalau API gagal, bot jatuh ke cara cadangan: baca angka di halaman dan
klik tombol `Claim`. Maksimum 1 claim per siklus, selalu verifikasi
status sesudahnya.

## Pagar aman

- Login **sekali** lewat `login.py` — akun X kamu, di browser yang kamu
  kendalikan (login dilindungi Turnstile, memang gerbang manusia).
  Sesi tersimpan lokal di `session/` (chmod 700, masuk `.gitignore`).
  **Tidak ada password / private key / seed di bot ini.**
- Bot **hanya** menyentuh dua endpoint mining di atas (atau tombol
  `Claim` sebagai fallback). Tidak pernah: Connect Wallet, Sign,
  Approve, Mint, Buy, Send, Mystery Box, ganti alamat.
- API menjawab `FROZEN` → bot berhenti & melapor, tidak memaksa.
- Sesi mati (401) → bot berhenti & melapor `SESI_MATI` (jalankan `login.py` lagi).
- `--dry-run` untuk cek tanpa claim apa pun.

## Pasang (di VPS / PC kamu)

```bash
git clone <repo-ini> dhorse-autoclaim   # atau salin folder ini
cd dhorse-autoclaim
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Login sekali

Di mesin berlayar (PC/laptop kamu):

```bash
python3 login.py
```

Klik **Connect with X**, selesaikan otorisasi, pastikan `/mine` sudah
menampilkan Power/Claimable, lalu tekan ENTER di terminal.

Di VPS tanpa layar: `xvfb-run -a python3 login.py`, **atau** login di PC
lalu kirim folder `session/` ke VPS (zip → scp → unzip di folder bot).
Folder `session/` = sesi loginmu; perlakukan seperti password, jangan
dibagikan / jangan di-commit.

> Catatan: alur Connect X situs ini kadang gagal dari sisi situs
> ("Could not start the sign-in"). Itu bug mereka (terjadi juga
> 4 & 12 Nov 2026) — coba lagi beberapa saat kemudian.

## Mode cookie-env (tanpa browser, tanpa login X berulang)

Tidak ada login pakai private key di situs ini — satu-satunya login di
seluruh bundle resminya adalah `/api/x/login` (akun X + Turnstile);
private key wallet BTC baru dipakai nanti saat *redeem* payout, bukan
untuk login/claim mining. Kredensial yang setara "env" di sini adalah
**cookie sesi** hasil login X itu:

```bash
# di mesin tempat kamu login (setelah login.py):
python3 export_cookie.py        # -> cookie.env (chmod 600), isi tidak ditampilkan
# salin isi cookie.env ke file .env di folder bot di VPS:
#   DHORSE_COOKIE="nama=isi; nama2=isi2; ..."
# di VPS (tanpa browser sama sekali):
python3 dhorse_claim.py --cookie --once --dry-run
python3 dhorse_claim.py --cookie --loop
```

Terbukti live 13 Nov 2026: cookie palsu → API menjawab **401**
(autentikasi murni cookie). Cookie mati → bot lapor `SESI_MATI`,
ekspor ulang sekali. Cookie = password akun: jangan dibagikan,
jangan di-commit (`.env`/`cookie.env` masuk `.gitignore`).
Risiko: `cf_clearance` kadang terikat IP/UA browser asal — bila VPS
kena 403 di mode ini, pakai mode browser (`login.py`) di VPS itu.

## Jalan

```bash
python3 dhorse_claim.py --selftest          # uji parser (tanpa browser)
python3 dhorse_claim.py --once --dry-run    # cek state saja
python3 dhorse_claim.py --once --inspect    # + simpan snapshot & network log
python3 dhorse_claim.py --once              # claim bila claimable >= 1
```

Jaga 24 jam pakai `screen`:

```bash
screen -S dhorse
python3 dhorse_claim.py --loop
# Ctrl+A lalu D untuk lepas; screen -r dhorse untuk kembali
```

Tempo loop adaptif: normal tiap 5 menit; merapat ke 60 dtk (lalu 30 dtk)
saat ronde mendekati akhir (dari countdown halaman, sisa blok, atau
estimasi historis ±06:59/±18:59 WIB). Log: terminal + `runs.log`.
Semua request jaringan ke situs tercatat di `inspect/network.jsonl`
(nama field saja) — bahan untuk upgrade ke mode API murni nanti.

## Opsi penting

| Flag | Arti |
|---|---|
| `--min-claim 1` | minimum claimable untuk claim (default 1 = minimum situs; tidak bisa di bawah itu) |
| `--interval 300` | tempo dasar polling (detik) |
| `--headed` | tampilkan browser (debug) |
| `--dry-run` | jangan klik, hanya lapor |

## Troubleshooting

- `SESI_MATI` → sesi X habis / situs logout: jalankan `login.py` lagi.
- `PARSE_GAGAL` → tampilan situs berubah: jalankan `--once --inspect`,
  snapshot teks ada di `inspect/` untuk disesuaikan parsernya.
- `BATAL_KLIK` → tombol Claim tidak ketemu tepat 1 / disabled: bot
  memang tidak menebak. Cek manual sekali, laporkan snapshot-nya.
- `CLAIM_TERKIRIM_BELUM_TERVERIFIKASI` → klik sudah dilakukan tapi angka
  belum berubah saat dicek ulang; cek manual di situs sebelum mengira gagal.
