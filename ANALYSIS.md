# REA — DarkHorse Genesis `/mine` (genesis.dhorse.fun)

Analisa 12 Nov 2026, gaya REA (Reverse Engineer Anything): bedakan tegas
**Observasi** (terlihat/terbukti), **Inferensi** (dugaan berdasar), dan
**Unknown** (belum bisa dibuktikan). Tanpa login, tanpa klaim, tanpa
tanda tangan apa pun selama recon.

## Observasi

1. **Produknya**: DarkHorse Genesis — campaign mining poin **Horseshoes**
   untuk BTC RGB. Horseshoes = poin campaign, klaim atas alokasi yang
   direncanakan sampai 6% dari total supply token DarkHorse kelak
   (blog resmi `blog.dhorse.fun/mining/`, footer situs sendiri:
   "Horseshoes are campaign points, not platform balances").
   **Bukan token on-chain, bukan kontrak EVM/BSC.** Tidak ada fungsi
   kontrak yang terlibat dalam claim mining ini.
2. **Mekanisme mining** (blog resmi, terkonfirmasi screenshot pengguna lain):
   - Power: BTC `+30 per 0,0001 BTC` (maks 3.000), aset beda `+30` (maks 900),
     14 aset khusus `+200` ekstra (maks 2.800); Knight min 100 power +10%,
     Genesis Partner min 100 +30%.
   - Laju: ±0,224 Horseshoes / power / hari. Akun Bos: power 110 →
     ±25/hari, ±12 per ronde, laju tampil ±0,17/blok.
   - **Ronde = 72 blok Bitcoin (±12 jam), jam akhir SAMA untuk semua user.**
     Historis di akun Bos ronde berakhir ±06:59 / ±18:59 WIB
     (epoch #54 = 3, #55 = 11 Horseshoes tercatat 7 Nov).
   - **Minimum claim 1 Horseshoe, boleh claim berkali-kali dalam 1 ronde.**
   - **Yang tidak di-claim saat ronde berakhir = BURN permanen**, tidak
     terbawa ke ronde berikutnya. Yang sudah di-claim aman.
   - Pecahan <1 belum bisa di-claim (mengantre sampai ≥1).
3. **Halaman `/mine` sebelum login**: SPA, satu-satunya aksi
   "Connect with X" ("Sign in with X first", judul "Muster your BTC record").
   Tombol Claim, countdown, saldo — semua di balik login X.
4. **Auth**: klik Connect → rute internal `/connecting?to=%2Fmine` →
   popup otorisasi X. Pada 4 Nov dan 12 Nov 2026 alur ini **gagal di sisi
   situs** dari lingkungan agen: "Could not start the sign-in. Please try
   again" — redirect ke x.com tidak pernah terjadi. Login Bos sendiri
   dari perangkatnya terbukti bisa (feed publik menampilkan
   "@Didinska0610 became a Knight · 1,000").
5. **Alamat BTC**: hanya Taproot `bc1p…` yang diterima (validasi bech32m
   sisi klien teramati); maks 5 alamat terhubung, ganti alamat bakar
   200 Horseshoes, scan histori 1x per alamat. Ini untuk *menghitung
   power*, bukan untuk claim.
6. **Data publik tanpa login**: Live Activity ticker, Leaderboard
   (Horseshoes & Power), statistik Knight — dimuat asinkron (API
   client-side ada, tapi host/path-nya tidak terlihat dari alat
   observasi yang tersedia; lihat Unknown).
7. **Akses mesin mentah terblokir**: `curl` dari VM agen kena halaman
   tantangan Cloudflare ("Just a moment…") — situs SPA + Cloudflare.
   Browser live lolos tanpa tantangan.

## Inferensi

- Claim hampir pasti **POST API off-chain dengan sesi hasil login X**
  (cookie sesi), karena: tidak ada wallet yang terhubung di halaman
  mining, reward-nya poin akun, dan klaim di wallet DarkHorse (blog
  Wallet Update #04) juga digambarkan sebagai aksi dalam aplikasi.
  Konsekuensi: bot tidak butuh private key, gas, atau baw — bot butuh
  **sesi login yang awet**.
- Karena claim boleh berkali-kali per ronde dan minimumnya cuma 1,
  strategi anti-burn paling aman bukan "claim mepet deadline" tapi
  **claim setiap kali claimable ≥1 saat terpantau** (polling ±5 menit →
  risiko burn praktis nol, deadline hanya jadi lapis kedua).

## Bukti bundle JS resmi (update 12 Nov 22:52 WIB — pintu samping Wayback)

Shell SPA yang diarsipkan Internet Archive (9 Okt 2026) memuat bundle
Vite tunggal `/assets/index-B78mJdG7.js` (±355 KB). Bundle itu berhasil
diunduh dari arsip dan dibedah (grep terarah + REA; hash bundle saat
ini bisa berbeda, tetapi dua endpoint publik di bawah terbukti masih
hidup malam ini, dan pola API-nya konsisten dengan UI sekarang):

**API situs (same-origin, `fetch` dengan `credentials:"same-origin"`,
tanpa header auth khusus):**

| Endpoint | Metode | Isi / respons |
|---|---|---|
| `/api/mining/status` | GET | `{claimable, blocksLeft, tipHeight, tipAt, dailyRate, claimed, effectivePower, epochIndex, boostLabel, history[{epochIndex, burned, at}], live}` — UI resmi mem-poll ini tiap 30 detik; countdown UI = `blocksLeft × 600 detik` |
| `/api/mining/claim` | POST body `{}` | `{claimed: jumlah}`; error bisa berkode `FROZEN` (akun dibekukan) atau membawa `state` |
| `/api/mining/network` | GET (publik) | **Terverifikasi live 12 Nov 22:53 WIB**: `{miners: 41018, totalPower: 11107766, top: [...]}` tanpa login |
| `/api/config` | GET (publik) | **Terverifikasi live**: `{turnstileSiteKey, platformNetwork: "mainnet", referralClosed: true, ...}` |
| `/api/me` | GET / POST(logout) | profil akun; 401 = `NOT_SIGNED_IN` |
| `/api/x/login` | POST `{turnstileToken, referral, returnTo}` | `{authorizeUrl}` — **login X dilindungi Cloudflare Turnstile**; inilah gerbang yang gagal dari lingkungan otomatis ("Could not start the sign-in") dan memang gerbang manusia |
| `/api/claim`, `/api/checkin`, `/api/tasks*`, `/api/address`, `/api/muster*`, `/api/query`, `/api/sybil`, `/api/feed`, `/api/leaderboard`, `/api/stats`, `/api/invite` | GET/POST | endpoint campaign lain di bundle yang sama; muster/query/sybil memakai token Turnstile, **status & claim mining TIDAK** |

Catatan REA formal: `analyze-javascript-application` atas bundle ini
selesai dengan Evidence ID
`ev_1517a6e7491210f5ace7c6195352f747259a0b0b9aa16ad45db31384fa6ae813`
(SHA-256 artefak `5a90ac6826ffed1cca34a123a791e964eefc2e94e136aaf5c66885787ca0833b`),
tetapi REA sendiri menyatakan grafiknya **tidak lengkap**: worker
statisnya kehabisan heap 1024 MiB pada bundle minified 355 KB ini.
Karena itu kesimpulan endpoint di atas bersandar pada ekstraksi string
& konteks kode bundle secara langsung (tercantum apa adanya) plus
verifikasi live dua endpoint publiknya — bukan pada grafik REA.

Fakta penting dari kode UI resmi:
- Tombol Claim aktif dari `Math.floor(claimable)` — cocok dengan aturan
  minimum 1 Horseshoe.
- Status juga disimpan UI ke `localStorage["genesis_mine_status"]`.
- Klaim yang berhasil memanggil ulang status + `/api/me` untuk verifikasi —
  bot meniru persis pola ini.

## Soal "login pakai private key" (dicek 13 Nov 2026 atas tanya Bos)

Tidak bisa — dan ini sifat situsnya, bukan batas bot: pencarian di
seluruh bundle resmi menemukan **tepat satu** endpoint login,
`/api/x/login`, dan **nol** kemunculan `signMessage`, `nonce`,
`privateKey`, `mnemonic`, `walletLogin`. Kata "signature" hanya muncul
pada konteks *redeem*: payout token nanti diklaim dengan tanda tangan
dari wallet alamat BTC yang terikat ("the platform honors that
signature, not your account") — peringatan situs sendiri: mining di
alamat orang lain = hasilmu bisa diklaim pemilik alamat itu. Jadi
private key di env tidak membuka login apa pun, dan menaruhnya di
server hanya menambah risiko kehilangan payout kelak.
Kredensial portabel yang benar adalah cookie sesi (lihat README,
mode `--cookie`): terbukti live 13 Nov 03:29 WIB, cookie palsu →
`GET /api/mining/status` menjawab 401.

## Unknown (sisa, jujur)

- Nama & umur pasti cookie sesi login X (httpOnly, tidak terbaca dari
  bundle) — bot tidak perlu tahu: ia memakai sesi browsernya sendiri.
- Hash bundle produksi *hari ini* (arsip yang tersedia 9 Okt 2026);
  endpoint status/claim bisa berganti nama di deploy masa depan — bot
  mendeteksi kegagalan API dan jatuh ke pembacaan DOM + klik UI, lalu
  melapor, bukan menebak endpoint baru.
- Apakah sesi bisa mati di tengah ronde selain karena logout — bot
  menangani 401 sebagai `SESI_MATI` dan berhenti, tidak memaksa login.

## Kesimpulan untuk bot

Tidak ada jalan pintas on-chain, tapi ada jalan API resmi: bot =
penjaga sesi login X + `GET /api/mining/status` + `POST /api/mining/claim`,
dipanggil dari dalam halaman yang sedang login (same-origin, persis
seperti UI resmi), dengan klik tombol Claim di UI sebagai fallback.
Pagar: hanya dua endpoint mining itu yang disentuh, verifikasi status
sesudah claim, maksimum 1 claim per siklus, berhenti total bila 401 /
FROZEN / halaman minta tanda tangan wallet.
