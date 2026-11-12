#!/usr/bin/env python3
"""
Login SEKALI untuk DarkHorse Genesis auto-claim.

Membuka browser (jendela yang KAMU kendalikan) ke genesis.dhorse.fun/mine.
Klik "Connect with X", selesaikan otorisasi X di popup seperti biasa.
Sesi (cookie + localStorage) tersimpan LOKAL di folder session/profile/
di mesin ini saja — tidak dikirim ke mana pun, jangan dibagikan, jangan
di-commit ke git (sudah masuk .gitignore).

Catatan jujur: pada 4 & 12 Nov 2026, alur "Connect with X" dari browser
agen gagal di sisi situs ("Could not start the sign-in. Please try
again"). Kalau itu terjadi juga di sini, coba lagi beberapa saat kemudian
— itu bug/gerbang di sisi situs, bukan salah akunmu. Login di PC/laptop
sendiri lalu salin folder session/ ke VPS juga bisa (lihat README).

Butuh layar: di VPS tanpa display jalankan lewat xvfb:
    xvfb-run -a python3 login.py
atau login di PC sendiri, zip folder session/, kirim ke VPS, unzip di
folder bot yang sama.

Selesai login: kembali ke terminal ini dan tekan ENTER. Sesi disimpan
otomatis oleh profil persisten browser.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(HERE, "session", "profile")
MINE_URL = "https://genesis.dhorse.fun/mine"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright belum terpasang. Jalankan dulu:")
        print("  pip install -r requirements.txt && playwright install chromium")
        return 1
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=False,
            args=["--no-first-run", "--disable-extensions"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(MINE_URL, wait_until="domcontentloaded", timeout=60000)
        print()
        print("=" * 64)
        print("1. Di jendela browser yang terbuka, klik 'Connect with X'.")
        print("2. Selesaikan otorisasi akun X kamu di popup.")
        print("3. Pastikan halaman /mine sudah menampilkan Power / Claimable")
        print("   (bukan lagi 'Sign in with X first').")
        print("4. Kembali ke sini, tekan ENTER untuk menyimpan & menutup.")
        print("=" * 64)
        try:
            input("Tekan ENTER setelah login berhasil... ")
        except EOFError:
            pass
        try:
            text = page.inner_text("body").lower()
            if "sign in with x first" in text:
                print("PERINGATAN: halaman masih menampilkan 'Sign in with X first'.")
                print("Sesi mungkin belum masuk. Ulangi login.py bila bot nanti lapor SESI_MATI.")
            else:
                print("OK: halaman /mine sudah dalam keadaan login. Sesi tersimpan di session/profile/")
        except Exception as e:
            print(f"Tidak bisa memeriksa halaman terakhir ({e}); sesi profil tetap tersimpan.")
        ctx.close()
    try:
        os.chmod(PROFILE_DIR, 0o700)
    except OSError:
        pass
    print("Selesai. Sekarang uji:  python3 dhorse_claim.py --once --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
