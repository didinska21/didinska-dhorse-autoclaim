#!/usr/bin/env python3
"""
Ambil cookie sesi DarkHorse dari profil login lokal -> file .env.

Prasyarat: sudah pernah `python3 login.py` di mesin ini (profil
persisten ada di session/profile/). Script ini membaca cookie untuk
genesis.dhorse.fun dari profil itu dan menulis SATU baris:

    DHORSE_COOKIE="nama=isi; nama2=isi2; ..."

ke file cookie.env (chmod 600) di folder ini.

Salin baris itu ke file .env di folder bot DI VPS, lalu jalankan:
    python3 dhorse_claim.py --cookie --once --dry-run
    python3 dhorse_claim.py --cookie --loop

PERINGATAN: cookie sesi = kredensial akunmu (setara password untuk
API situs ini). File cookie.env / .env JANGAN dibagikan, JANGAN
di-commit (sudah masuk .gitignore), JANGAN dikirim lewat chat.
Bila cookie bocor: logout dari situs (POST /api/me versi UI = tombol
logout) untuk mencabut sesi, lalu login & ekspor ulang.

Catatan Cloudflare: bila cookie mengandung cf_clearance dari browser
ini, mode --cookie di VPS bisa kena 403 karena IP/UA berbeda. Bila itu
terjadi, pakai mode browser (login.py) langsung di VPS tersebut.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(HERE, "session", "profile")
OUT_FILE = os.path.join(HERE, "cookie.env")
MINE_URL = "https://genesis.dhorse.fun/mine"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright belum terpasang: pip install -r requirements.txt && playwright install chromium")
        return 1
    if not os.path.isdir(PROFILE_DIR):
        print("Profil login belum ada. Jalankan dulu: python3 login.py")
        return 1
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=True,
            args=["--no-first-run", "--disable-extensions"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(MINE_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Gagal membuka situs dari profil: {e}")
            ctx.close()
            return 1
        cookies = [c for c in ctx.cookies() if "dhorse.fun" in (c.get("domain") or "")]
        ctx.close()
    if not cookies:
        print("Tidak ada cookie dhorse.fun di profil — login dulu dengan login.py.")
        return 1
    header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(f'DHORSE_COOKIE="{header}"\n')
    try:
        os.chmod(OUT_FILE, 0o600)
    except OSError:
        pass
    names = ", ".join(sorted({c["name"] for c in cookies}))
    print(f"OK: {len(cookies)} cookie tersimpan ke cookie.env (chmod 600).")
    print(f"Nama cookie (isi tidak ditampilkan): {names}")
    print("Salin ISI cookie.env ke file .env di folder bot di VPS kamu.")
    print("Perlakukan file itu seperti password. Jangan kirim lewat chat / jangan commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
