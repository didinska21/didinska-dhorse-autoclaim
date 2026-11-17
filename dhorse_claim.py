#!/usr/bin/env python3
"""
DarkHorse Genesis — auto-claim bot  (genesis.dhorse.fun/mine)
=============================================================
Kenapa bot ini ada: reward mining Horseshoes HANGUS (burn) di akhir tiap
ronde (72 blok Bitcoin, ±12 jam) kalau belum di-Claim. Bot ini menjaga
sesi login X kamu, memantau halaman /mine, dan menekan tombol Claim
begitu claimable >= minimum (default 1 Horseshoe), jadi tidak ada lagi
ronde yang kelewat.

CARA KERJA (aman by design):
  * Login SEKALI lewat login.py (akun X kamu sendiri, di jendela browser
    yang kamu kendalikan). Sesi tersimpan lokal di folder session/
    (profil browser persisten). TIDAK ada password / private key /
    seed phrase yang disimpan atau dikirim ke mana pun.
  * Bot HANYA pernah menekan satu tombol: "Claim" di
    https://genesis.dhorse.fun/mine
    Tombol lain tidak pernah disentuh: tidak Connect Wallet, tidak Sign,
    tidak Approve, tidak Mint, tidak Buy/Send/Transfer, tidak Mystery Box.
  * Claim di situs ini adalah aksi akun off-chain (kredit poin
    Horseshoes), BUKAN transaksi on-chain dan BUKAN tanda tangan wallet.
    Kalau suatu saat halaman meminta tanda tangan wallet / popup
    ekstensi, bot berhenti dan melapor — tidak melanjutkan.
  * Default mode sekali-jalan + --dry-run tersedia untuk cek tanpa klik.
  * Semua request jaringan ke genesis.dhorse.fun dicatat (method, URL,
    status, nama field JSON) ke inspect/network.jsonl — ini bahan REA
    untuk versi API murni nanti, dan bukti audit buat kamu.

MODE API (hasil REA 12 Nov 2026, dari JS bundle resmi situs):
  * Status:  GET  /api/mining/status  -> {claimable, blocksLeft,
    tipHeight, dailyRate, claimed, effectivePower, epochIndex, history[]}
  * Claim:   POST /api/mining/claim   body "{}" -> {claimed: jumlah}
  * Auth = cookie sesi login X (same-origin), TANPA header khusus dan
    TANPA Turnstile untuk status/claim (Turnstile hanya untuk login,
    muster & sybil). Bot memanggil API ini dari dalam halaman yang
    sedang login (fetch same-origin persis seperti UI resmi), dan
    klik tombol Claim di UI tetap disiapkan sebagai fallback.
  * Yang tetap tidak bisa agen lakukan: login X atas nama kamu
    (Turnstile + otorisasi X memang gerbang manusia) — itu login.py.
  * Angka claimable / sisa ronde dibaca dari teks halaman. Kalau situs
    mengubah tampilan, parser bisa gagal membaca — bot melapor
    PARSE_GAGAL dan TIDAK menebak-nebak klik di luar tombol Claim.
  * Estimasi jam akhir ronde cadangan (±06:59 / ±18:59 WIB, dari
    kadens historis 72 blok) hanya dipakai untuk mempercepat polling,
    bukan sebagai jam pasti.

UPDATE 17 Nov 2026 (REA bundle index-Bse_Z7JS.js, lihat ANALYSIS.md):
  * DAILY CHECK-IN di halaman utama (/):  GET /api/me memberi state
    checkinToday/checkinDays; aksinya POST /api/checkin body "{}" ->
    +20 Horseshoes ke pending. Auth cookie sesi saja, TANPA Turnstile
    (persis pola mining claim). Bot check-in sekali per hari server:
    tiap siklus baca /api/me, POST hanya bila checkinToday == false,
    lalu verifikasi ulang /api/me.
  * BOARD (/board): tab Horseshoes = GET /api/leaderboard
    {rows[50]{handle,tier,points}, me{rank}}; tab Power =
    GET /api/mining/network {miners,totalPower,top[50]{handle,power}};
    rank power sendiri = field networkRank di GET /api/mining/status
    (field baru, parser lama belum menangkapnya). Bot melaporkan rank
    Horseshoes + rank/power tiap siklus --once, dan berkala di --loop.
  * Matikan per fitur: --no-checkin / --no-board. --board-only untuk
    cetak board saja (tanpa cookie pun bisa: versi publik, rank
    pribadi kosong).

Pakai:
  python3 dhorse_claim.py --once --dry-run     # cek saja, tanpa klik
  python3 dhorse_claim.py --once               # check-in + claim bila >= 1 + board
  python3 dhorse_claim.py --loop               # jaga terus (untuk screen)
  python3 dhorse_claim.py --once --inspect     # simpan snapshot teks+network
  python3 dhorse_claim.py --board-only         # cetak rank/power saja
  python3 dhorse_claim.py --selftest           # uji parser tanpa browser
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

BASE = "https://genesis.dhorse.fun"
MINE_URL = BASE + "/mine"
ALLOWED_HOST = "genesis.dhorse.fun"
HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(HERE, "session", "profile")
INSPECT_DIR = os.path.join(HERE, "inspect")
LOG_FILE = os.path.join(HERE, "runs.log")
WIB = timezone(timedelta(hours=7))

# Tombol yang TIDAK AKAN PERNAH diklik bot (daftar ini hanya dokumentasi
# pagar; logika klik di bawah hanya mencari tombol "Claim" persis).
FORBIDDEN_LABELS = (
    "connect wallet", "sign", "approve", "mint", "buy", "send",
    "transfer", "mystery", "open box", "connect with x", "connect x",
)


def now_wib() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")


def log(msg: str) -> None:
    line = f"[{now_wib()}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def log_block(lines: list[str]) -> None:
    """Blok multi-baris rapi: baris pertama bertimestamp, sisanya menjorok
    sejajar di bawahnya. Semua baris tetap ditulis ke runs.log."""
    if not lines:
        return
    stamp = f"[{now_wib()}] "
    out = [stamp + lines[0]] + [" " * len(stamp) + ln for ln in lines[1:]]
    for ln in out:
        print(ln, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            for ln in out:
                f.write(ln + "\n")
    except OSError:
        pass


def fmt_num(x, dec: int = 4) -> str:
    """1234567.891 -> '1,234,567.891' (nol ekor dibuang)."""
    if x is None:
        return "-"
    s = f"{float(x):,.{dec}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def bar(done: float, total: float, width: int = 20) -> str:
    """Bar progres teks: bar(61, 72) -> '█████████████████░░░ 85%'."""
    if not total:
        return ""
    frac = max(0.0, min(1.0, float(done) / float(total)))
    fill = round(frac * width)
    return "█" * fill + "░" * (width - fill) + f" {frac * 100:.0f}%"


def banner(mode: str, min_claim: float, interval: int, loop: bool, dry: bool) -> None:
    tempo = f"{interval // 60} mnt" if interval >= 60 else f"{interval} dtk"
    log_block([
        "╔══════════════════════════════════════════════════════════╗",
        "║  🐴 DARKHORSE GENESIS — CLAIM + CHECK-IN + BOARD          ║",
        "╚══════════════════════════════════════════════════════════╝",
        f"Mode {mode} · claim otomatis ≥ {fmt_num(min_claim, 1)} · cek tiap {tempo}"
        + (" · LOOP 24 jam" if loop else " · sekali jalan")
        + (" · ⚠️ DRY-RUN (tanpa claim)" if dry else ""),
    ])


# ---------------------------------------------------------------- parsing

@dataclass
class MineState:
    logged_in: bool = False
    claimable: float | None = None
    claimed_total: float | None = None
    power: float | None = None
    epoch: int | None = None
    block_in_round: int | None = None   # x dari x/72
    round_blocks: int | None = None     # biasanya 72
    minutes_left_hint: int | None = None
    raw_found: str = ""
    # --- field API /api/mining/status (dari JS bundle resmi, lihat ANALYSIS.md)
    blocks_left_api: int | None = None  # blocksLeft
    tip_height: int | None = None       # tipHeight (tinggi blok BTC terakhir)
    daily_rate: float | None = None     # dailyRate (Horseshoes/hari)
    via_api: bool = False
    # --- field BARU di /api/mining/status (bundle 17 Nov 2026, dipakai UI /board & /mine)
    network_rank: int | None = None     # networkRank = rank power sendiri se-network
    network_power: float | None = None  # networkPower = total power network (snapshot status)
    block_seconds: int | None = None    # blockSeconds = detik per blok utk countdown

    def blocks_left(self) -> int | None:
        if self.blocks_left_api is not None:
            return self.blocks_left_api
        if self.block_in_round is not None and self.round_blocks:
            return max(0, self.round_blocks - self.block_in_round)
        return None


def parse_status_json(data: dict) -> MineState:
    """Parse respons GET /api/mining/status persis seperti UI resmi:
    claimable (float, UI menampilkannya di-floor), blocksLeft,
    tipHeight, dailyRate, history[].burned."""
    st = MineState(logged_in=True, via_api=True)
    if isinstance(data.get("claimable"), (int, float)):
        st.claimable = float(data["claimable"])
    if isinstance(data.get("blocksLeft"), (int, float)):
        st.blocks_left_api = int(data["blocksLeft"])
        st.round_blocks = 72
        st.block_in_round = 72 - st.blocks_left_api
        # countdown UI resmi = blocksLeft * 600 detik
        st.minutes_left_hint = st.blocks_left_api * 10
    if isinstance(data.get("tipHeight"), (int, float)):
        st.tip_height = int(data["tipHeight"])
    if isinstance(data.get("networkRank"), (int, float)):
        st.network_rank = int(data["networkRank"])
    if isinstance(data.get("networkPower"), (int, float)):
        st.network_power = float(data["networkPower"])
    if isinstance(data.get("blockSeconds"), (int, float)):
        st.block_seconds = int(data["blockSeconds"])
        if st.blocks_left_api is not None:
            # countdown UI resmi = blocksLeft * (blockSeconds || 600)
            st.minutes_left_hint = int(st.blocks_left_api * st.block_seconds / 60)
    if isinstance(data.get("dailyRate"), (int, float)):
        st.daily_rate = float(data["dailyRate"])
    if isinstance(data.get("claimed"), (int, float)):
        st.claimed_total = float(data["claimed"])
    if isinstance(data.get("effectivePower"), (int, float)):
        st.power = float(data["effectivePower"])
    elif isinstance(data.get("power"), (int, float)):
        st.power = float(data["power"])
    if isinstance(data.get("epochIndex"), (int, float)):
        st.epoch = int(data["epochIndex"]) + 1
    hist = data.get("history")
    if isinstance(hist, list):
        burned = sum(float(h.get("burned", 0) or 0) for h in hist if isinstance(h, dict))
        st.raw_found += f" riwayat_burn_total={burned}"
    st.raw_found += f" api claimable={st.claimable} blocksLeft={st.blocks_left_api} tip={st.tip_height}"
    return st


@dataclass
class MeState:
    """State akun dari GET /api/me (field yang benar-benar dipakai UI resmi)."""
    logged_in: bool = False
    handle: str | None = None           # handle X akun
    checkin_today: bool | None = None   # checkinToday: sudah check-in hari server ini?
    checkin_days: int | None = None     # checkinDays: total hari check-in
    mustered: bool | None = None        # mustered: sudah muster alamat BTC?
    has_wallet: bool = False            # walletAddress terisi?


def parse_me_json(data: dict) -> MeState:
    me = MeState(logged_in=True)
    if isinstance(data.get("handle"), str) and data["handle"]:
        me.handle = data["handle"]
    if isinstance(data.get("checkinToday"), bool):
        me.checkin_today = data["checkinToday"]
    if isinstance(data.get("checkinDays"), (int, float)):
        me.checkin_days = int(data["checkinDays"])
    if isinstance(data.get("mustered"), bool):
        me.mustered = data["mustered"]
    me.has_wallet = bool(data.get("walletAddress"))
    return me


@dataclass
class BoardState:
    """Ringkasan /board: rank Horseshoes (leaderboard) + rank Power (network)."""
    hs_rank: int | None = None          # /api/leaderboard -> me.rank
    hs_points: float | None = None      # poin sendiri bila ketemu (me.points / baris sendiri)
    hs_top_handle: str | None = None
    hs_top_points: float | None = None
    hs_in_top: int | None = None        # posisi (1-based) bila handle sendiri ada di rows Top 50
    power_rank: int | None = None       # /api/mining/status -> networkRank
    power: float | None = None          # effectivePower sendiri
    power_top_handle: str | None = None
    power_top: float | None = None
    power_in_top: int | None = None
    miners: int | None = None
    total_power: float | None = None


def parse_board(leaderboard: dict | None, network: dict | None,
                handle: str | None, st: MineState | None) -> BoardState:
    b = BoardState()
    if isinstance(leaderboard, dict):
        rows = leaderboard.get("rows") if isinstance(leaderboard.get("rows"), list) else []
        if rows and isinstance(rows[0], dict):
            b.hs_top_handle = rows[0].get("handle")
            if isinstance(rows[0].get("points"), (int, float)):
                b.hs_top_points = float(rows[0]["points"])
        me = leaderboard.get("me")
        if isinstance(me, dict):
            if isinstance(me.get("rank"), (int, float)):
                b.hs_rank = int(me["rank"])
            if isinstance(me.get("points"), (int, float)):
                b.hs_points = float(me["points"])
        if handle:
            for i, r in enumerate(rows):
                if isinstance(r, dict) and str(r.get("handle", "")).lower() == handle.lower():
                    b.hs_in_top = i + 1
                    if isinstance(r.get("points"), (int, float)):
                        b.hs_points = float(r["points"])
                    if b.hs_rank is None:
                        b.hs_rank = i + 1
                    break
    if isinstance(network, dict):
        if isinstance(network.get("miners"), (int, float)):
            b.miners = int(network["miners"])
        if isinstance(network.get("totalPower"), (int, float)):
            b.total_power = float(network["totalPower"])
        top = network.get("top") if isinstance(network.get("top"), list) else []
        if top and isinstance(top[0], dict):
            b.power_top_handle = top[0].get("handle")
            if isinstance(top[0].get("power"), (int, float)):
                b.power_top = float(top[0]["power"])
        if handle:
            for i, r in enumerate(top):
                if isinstance(r, dict) and str(r.get("handle", "")).lower() == handle.lower():
                    b.power_in_top = i + 1
                    break
    if st is not None:
        if st.network_rank is not None:
            b.power_rank = st.network_rank
        if st.power is not None:
            b.power = st.power
        if b.power_rank is None and b.power_in_top is not None:
            b.power_rank = b.power_in_top
    return b


def board_lines(b: BoardState, handle: str | None) -> list[str]:
    who = f" @{handle}" if handle else ""
    hs = f"#{fmt_num(b.hs_rank, 0)}" if b.hs_rank is not None else "di luar Top 50 / belum berperingkat"
    if b.hs_points is not None:
        hs += f" · {fmt_num(b.hs_points, 0)} Horseshoes"
    if b.hs_in_top is not None:
        hs += f" · tampil di Top 50 (#{b.hs_in_top})"
    pw = f"#{fmt_num(b.power_rank, 0)}" if b.power_rank is not None else "belum ada rank dari API"
    if b.power is not None:
        pw += f" · power {fmt_num(b.power, 0)}"
    if b.power_in_top is not None:
        pw += f" · tampil di Top 50 (#{b.power_in_top})"
    lines = [f"📊 BOARD{who} — 🏆 Horseshoes: {hs}",
             f"   ⚡ Power: {pw}"]
    net = []
    if b.hs_top_handle:
        net.append(f"Top HS @{b.hs_top_handle} {fmt_num(b.hs_top_points, 0)}")
    if b.power_top_handle:
        net.append(f"Top Power @{b.power_top_handle} {fmt_num(b.power_top, 0)}")
    if b.miners is not None:
        net.append(f"miners {fmt_num(b.miners, 0)}")
    if b.total_power is not None:
        net.append(f"total power {fmt_num(b.total_power, 0)}")
    if net:
        lines.append("   🌐 " + " · ".join(net))
    return lines


def _num(s: str) -> float:
    """Angka situs: '0.7800' = desimal; '4.950' pada power = ribuan.
    Untuk claimable kita selalu dipanggil pada konteks desimal 4 angka
    di belakang koma bila ada; fungsi ini menormalkan koma desimal ID."""
    s = s.strip()
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    return float(s)


def parse_mine_text(text: str) -> MineState:
    """Baca state dari teks halaman /mine (setelah login). Konservatif:
    hanya mengambil angka yang dekat dengan labelnya."""
    t = " ".join(text.split())
    st = MineState()
    low = t.lower()

    if "sign in with x first" in low or "connect with x" in low:
        st.logged_in = False
        return st
    # Setelah login halaman memuat label mining; anggap login bila ada
    # salah satu label ini.
    if any(k in low for k in ("claimable", "to claim", "my power", "mined")):
        st.logged_in = True

    m = re.search(r"(?:mined\s*[•·\-]?\s*)?claimable\D{0,30}?(\d+(?:[.,]\d+)?)", low)
    if not m:
        m = re.search(r"to claim\D{0,30}?(\d+(?:[.,]\d+)?)", low)
    if m:
        try:
            st.claimable = _num(m.group(1))
            st.raw_found += f" claimable={m.group(1)}"
        except ValueError:
            pass

    m = re.search(r"(?<!to )claimed\D{0,30}?(\d+(?:[.,]\d+)?)", low)
    if m:
        try:
            raw_c = m.group(1)
            # total claimed = bilangan bulat besar: "1,300" / "1.300" = ribuan
            if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw_c):
                raw_c = raw_c.replace(",", "").replace(".", "")
            st.claimed_total = _num(raw_c)
            st.raw_found += f" claimed={m.group(1)}"
        except ValueError:
            pass

    m = re.search(r"(?:my power|power)\D{0,20}?(\d[\d.,]*)", low)
    if m:
        raw = m.group(1).replace(".", "").replace(",", ".")
        try:
            st.power = float(raw)
            st.raw_found += f" power={m.group(1)}"
        except ValueError:
            pass

    m = re.search(r"epoch\s*#?\s*(\d+)", low)
    if m:
        st.epoch = int(m.group(1))

    m = re.search(r"(\d{1,3})\s*/\s*(72)\b", low)
    if m:
        st.block_in_round = int(m.group(1))
        st.round_blocks = int(m.group(2))
    else:
        m = re.search(r"block\s+(\d[\d.,]*)", low)
        if m:
            st.raw_found += f" blockheight={m.group(1)}"

    m = re.search(r"due in\s+(\d+)\s*(?:min|minute)", low) or \
        re.search(r"(\d+)\s*(?:min|minutes?)\s+(?:left|remaining)", low) or \
        re.search(r"ends? in\s+(\d+)\s*(?:min|minute)", low)
    if m:
        st.minutes_left_hint = int(m.group(1))

    return st


def next_round_end_estimate(now: datetime | None = None) -> datetime:
    """Cadangan historis: ronde berakhir ±06:59 / ±18:59 WIB.
    Hanya untuk tempo polling — BUKAN jam pasti (blok BTC bervariasi)."""
    now = now or datetime.now(WIB)
    candidates = []
    for day_off in (0, 1):
        d = (now + timedelta(days=day_off)).date()
        for hh in (6, 18):
            candidates.append(datetime(d.year, d.month, d.day, hh, 59, tzinfo=WIB))
    future = [c for c in candidates if c > now]
    return min(future) if future else candidates[-1]


# ---------------------------------------------------------------- browser

def _json_field_names(obj, prefix="", out=None, depth=0):
    if out is None:
        out = set()
    if depth > 3:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(f"{prefix}{k}")
            _json_field_names(v, f"{prefix}{k}.", out, depth + 1)
    elif isinstance(obj, list) and obj:
        _json_field_names(obj[0], prefix, out, depth + 1)
    return out


class ClaimBot:
    def __init__(self, headless: bool = True, inspect: bool = False,
                 do_checkin_feature: bool = True, show_board: bool = True):
        self.headless = headless
        self.inspect = inspect
        self.do_checkin_feature = do_checkin_feature
        self.show_board = show_board
        self.net_log_path = os.path.join(INSPECT_DIR, "network.jsonl")
        os.makedirs(INSPECT_DIR, exist_ok=True)
        os.makedirs(PROFILE_DIR, exist_ok=True)

    # -- network sniffing: catat saja, tidak mengubah apa pun
    def _on_response(self, resp):
        try:
            url = resp.url
            if ALLOWED_HOST not in url:
                return
            rec = {"ts": now_wib(), "method": resp.request.method,
                   "url": url, "status": resp.status}
            ctype = (resp.headers or {}).get("content-type", "")
            if "json" in ctype:
                try:
                    body = resp.json()
                    rec["json_fields"] = sorted(_json_field_names(body))[:60]
                    # endpoint mining = kandidat API claim/status untuk REA lanjutan
                    if any(k in url.lower() for k in ("mine", "mining", "claim", "horseshoe", "round")):
                        rec["json_preview"] = json.dumps(body)[:800]
                except Exception:
                    pass
            with open(self.net_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def run_cycle(self, do_claim: bool, min_claim: float) -> MineState | None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log("BLOCKER: playwright belum terpasang. Jalankan: "
                "pip install -r requirements.txt && playwright install chromium")
            return None

        with sync_playwright() as p:
            try:
                ctx = p.chromium.launch_persistent_context(
                    PROFILE_DIR, headless=self.headless,
                    args=["--no-first-run", "--disable-extensions"],
                )
            except Exception as e:
                log(f"BLOCKER: browser gagal diluncurkan: {e}. "
                    "Pastikan sudah: playwright install chromium")
                return None
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("response", self._on_response)
            try:
                page.goto(MINE_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                text = page.inner_text("body")
            except Exception as e:
                log(f"BLOCKER: gagal membuka {MINE_URL}: {e}")
                ctx.close()
                return None

            if self.inspect:
                snap = os.path.join(INSPECT_DIR, f"mine_{datetime.now(WIB):%Y%m%d_%H%M%S}.txt")
                with open(snap, "w", encoding="utf-8") as f:
                    f.write(text)
                log(f"inspect: snapshot teks disimpan ke {snap}")

            # ---- JALUR UTAMA: API resmi situs (dari JS bundle, ANALYSIS.md)
            # GET /api/mining/status dengan cookie sesi yang sama seperti UI
            # (fetch same-origin dari dalam halaman — persis cara situsnya).
            st_api, api_note = self._api_status(page)
            if api_note == "SESI_MATI":
                log("SESI_MATI: /api/mining/status menjawab 401 NOT_SIGNED_IN. "
                    "Jalankan login.py lagi. Bot berhenti siklus ini, tidak klik apa pun.")
                st_dead = MineState(logged_in=False)
                ctx.close()
                return st_dead
            if st_api is not None:
                st = st_api
            else:
                # fallback: baca teks halaman seperti sebelumnya
                st = parse_mine_text(text)
            log(f"state: via={'API' if st.via_api else 'DOM'} logged_in={st.logged_in} claimable={st.claimable} "
                f"claimed={st.claimed_total} power={st.power} epoch={st.epoch} "
                f"block={st.block_in_round}/{st.round_blocks} blocksLeft={st.blocks_left()} "
                f"tip={st.tip_height} dailyRate={st.daily_rate} "
                f"menit_hint={st.minutes_left_hint} ({st.raw_found.strip()})")

            if not st.logged_in:
                log("SESI_MATI: halaman meminta Sign in with X. Jalankan login.py lagi "
                    "(login sekali, sesi disimpan lokal). Bot berhenti siklus ini, tidak klik apa pun.")
                ctx.close()
                return st

            # ---- DAILY CHECK-IN + BOARD (fitur 17 Nov 2026, pola API sama)
            me_b: MeState | None = None
            if self.do_checkin_feature:
                me_b, ck_note = self._checkin_step(page, do_write=do_claim)
                if ck_note == "SESI_MATI":
                    ctx.close()
                    return MineState(logged_in=False)
            if self.show_board:
                self._board_step(page, st, me_b.handle if me_b else None)

            if st.claimable is None:
                log("PARSE_GAGAL: angka claimable tidak terbaca (API maupun DOM). "
                    "Tidak ada klik. Simpan snapshot dengan --inspect untuk dicek.")
                ctx.close()
                return st

            # ---- keputusan claim
            est_end = next_round_end_estimate()
            mins_to_est_end = (est_end - datetime.now(WIB)).total_seconds() / 60.0
            urgent = (st.minutes_left_hint is not None and st.minutes_left_hint <= 45) or \
                     (st.blocks_left() is not None and st.blocks_left() <= 6) or \
                     mins_to_est_end <= 45

            if st.claimable >= min_claim:
                if not do_claim:
                    log(f"DRY-RUN: claimable {st.claimable} >= {min_claim} — "
                        f"seharusnya CLAIM sekarang{' (URGENT: ronde mau habis)' if urgent else ''}. Tidak diklik.")
                    ctx.close()
                    return st
                # Claim API dulu: POST /api/mining/claim {} -> {claimed: n}
                claimed_amt, claim_note = self._api_claim(page)
                if claimed_amt is not None:
                    log(f"CLAIM_BERHASIL_API: +{claimed_amt} Horseshoes masuk akun "
                        f"(POST /api/mining/claim). Verifikasi status ulang ...")
                    page.wait_for_timeout(1500)
                    st2, _ = self._api_status(page)
                    if st2 is not None:
                        log(f"status sesudah claim: claimable={st2.claimable} "
                            f"blocksLeft={st2.blocks_left()} claimed={st2.claimed_total}")
                        ctx.close()
                        return st2
                    ctx.close()
                    return st
                if claim_note == "FROZEN":
                    log("BLOCKER: akun FROZEN menurut API claim. Bot berhenti mengklaim; "
                        "cek akunmu di situs (status sybil/frozen memang ada di sistem mereka).")
                    ctx.close()
                    return st
                log(f"Claim API tidak berhasil ({claim_note}); fallback klik tombol Claim di UI ...")
                ok = self._click_claim(page)
                if ok:
                    page.wait_for_timeout(4000)
                    text2 = page.inner_text("body")
                    st2 = parse_mine_text(text2)
                    if st2.claimable is not None and st.claimable is not None and st2.claimable < st.claimable:
                        log(f"CLAIM_BERHASIL: claimable {st.claimable} -> {st2.claimable}; "
                            f"claimed_total={st2.claimed_total}")
                    elif st2.claimed_total != st.claimed_total and st2.claimed_total is not None:
                        log(f"CLAIM_BERHASIL (total naik): claimed {st.claimed_total} -> {st2.claimed_total}; "
                            f"claimable sekarang={st2.claimable}")
                    else:
                        log(f"CLAIM_TERKIRIM_BELUM_TERVERIFIKASI: klik Claim dilakukan, "
                            f"angka sesudahnya claimable={st2.claimable} claimed={st2.claimed_total}. "
                            f"Cek manual sekali di situs; bot tidak klik ulang di siklus ini.")
                    ctx.close()
                    return st2
                ctx.close()
                return st
            else:
                if st.claimable > 0 and urgent:
                    log(f"INFO: claimable {st.claimable} masih di bawah minimum {min_claim} "
                        f"dan ronde mendekati akhir — pecahan <1 memang belum bisa di-claim "
                        f"(mengantre sampai >=1 menurut aturan situs). Tidak ada yang bisa diklik.")
                else:
                    log(f"Belum claim: claimable {st.claimable} < minimum {min_claim}. Aman, lanjut pantau.")
                ctx.close()
                return st

    # -- API resmi situs, dipanggil dari dalam halaman (same-origin,
    #    cookie sesi UI sendiri). Endpoint dari JS bundle resmi:
    #    GET /api/mining/status, POST /api/mining/claim body "{}".
    #    TIDAK ada header auth khusus / Turnstile untuk dua endpoint ini
    #    (Turnstile hanya untuk login X, muster & cek sybil).
    def _api_status(self, page):
        try:
            r = page.evaluate(
                """async () => {
                    const resp = await fetch('/api/mining/status',
                        {credentials:'same-origin', cache:'no-store'});
                    let body = null;
                    try { body = await resp.json(); } catch(e) {}
                    return {status: resp.status, body};
                }"""
            )
        except Exception as e:
            return None, f"eval-gagal: {e}"
        if not isinstance(r, dict):
            return None, "respons-aneh"
        if r.get("status") == 401:
            return None, "SESI_MATI"
        body = r.get("body")
        if r.get("status") == 200 and isinstance(body, dict) and "claimable" in body:
            return parse_status_json(body), "OK"
        return None, f"http-{r.get('status')}"

    def _api_claim(self, page):
        """Return (claimed_amount | None, note)."""
        try:
            r = page.evaluate(
                """async () => {
                    const resp = await fetch('/api/mining/claim',
                        {method:'POST', credentials:'same-origin',
                         headers:{'content-type':'application/json'}, body:'{}'});
                    let body = null;
                    try { body = await resp.json(); } catch(e) {}
                    return {status: resp.status, body};
                }"""
            )
        except Exception as e:
            return None, f"eval-gagal: {e}"
        if not isinstance(r, dict):
            return None, "respons-aneh"
        body = r.get("body") or {}
        if r.get("status") == 200 and isinstance(body, dict) and \
                isinstance(body.get("claimed"), (int, float)):
            return float(body["claimed"]), "OK"
        code = body.get("error") if isinstance(body, dict) else None
        if code == "FROZEN":
            return None, "FROZEN"
        return None, f"http-{r.get('status')} error={code}"

    def _api_fetch(self, page, path: str, method: str = "GET"):
        """Fetch same-origin generik dari dalam halaman login (pola UI resmi).
        Return (status:int, body:dict|None)."""
        try:
            r = page.evaluate(
                """async ([path, method]) => {
                    const opts = {credentials:'same-origin', cache:'no-store'};
                    if (method === 'POST') {
                        opts.method = 'POST';
                        opts.headers = {'content-type':'application/json'};
                        opts.body = '{}';
                    }
                    const resp = await fetch(path, opts);
                    let body = null;
                    try { body = await resp.json(); } catch(e) {}
                    return {status: resp.status, body};
                }""", [path, method])
        except Exception as e:
            return 0, {"error": f"eval-gagal: {e}"}
        if not isinstance(r, dict):
            return 0, None
        return int(r.get("status") or 0), r.get("body")

    def _checkin_step(self, page, do_write: bool):
        """Daily check-in mode browser. Return (MeState|None, note)."""
        status, body = self._api_fetch(page, "/api/me")
        if status == 401:
            log("SESI_MATI: /api/me 401. Bot berhenti siklus ini.")
            return None, "SESI_MATI"
        if status != 200 or not isinstance(body, dict):
            log(f"CHECKIN_SKIP: /api/me HTTP {status} — check-in dilewati siklus ini.")
            return None, f"http-{status}"
        me = parse_me_json(body)
        if me.checkin_today is None:
            log("PARSE_GAGAL (check-in): checkinToday tidak ada di /api/me; tidak ditebak.")
            return me, "PARSE_GAGAL"
        days_txt = f" · total {me.checkin_days} hari" if me.checkin_days is not None else ""
        if me.checkin_today:
            log(f"📅 Daily check-in: SUDAH hari ini{days_txt}.")
            return me, "SUDAH"
        if not do_write:
            log(f"📅 DRY-RUN: check-in BELUM hari ini{days_txt} — seharusnya POST /api/checkin (+20). Tidak dikirim.")
            return me, "DRY"
        c_status, c_body = self._api_fetch(page, "/api/checkin", method="POST")
        err = c_body.get("error") if isinstance(c_body, dict) else None
        if c_status == 401:
            return me, "SESI_MATI"
        if c_status == 200:
            s2, b2 = self._api_fetch(page, "/api/me")
            if s2 == 200 and isinstance(b2, dict):
                me2 = parse_me_json(b2)
                if me2.checkin_today:
                    d2 = f" · total {me2.checkin_days} hari" if me2.checkin_days is not None else ""
                    log(f"📅✅ CHECKIN_BERHASIL: +20 Horseshoes masuk pending{d2} (terverifikasi).")
                    return me2, "BERHASIL"
            log("📅✅ CHECKIN_TERKIRIM: POST 200, verifikasi belum menegaskan; tidak POST ulang siklus ini.")
            return me, "BERHASIL"
        if err and ("ALREADY" in str(err).upper() or "CHECKED" in str(err).upper()):
            log(f"📅 Daily check-in: server menjawab {err} — dianggap SUDAH.")
            return me, "SUDAH"
        if err == "FROZEN":
            log("BLOCKER: akun FROZEN menurut API check-in.")
            return me, "FROZEN"
        log(f"📅 CHECKIN_GAGAL: HTTP {c_status} error={err}")
        return me, "GAGAL"

    def _board_step(self, page, st: MineState, handle: str | None) -> None:
        s_lb, b_lb = self._api_fetch(page, "/api/leaderboard")
        s_nw, b_nw = self._api_fetch(page, "/api/mining/network")
        if s_lb != 200 and s_nw != 200:
            log(f"BOARD_GAGAL: leaderboard HTTP {s_lb}, network HTTP {s_nw}.")
            return
        b = parse_board(b_lb if s_lb == 200 else None,
                        b_nw if s_nw == 200 else None, handle, st)
        log_block(board_lines(b, handle))

    def _click_claim(self, page) -> bool:
        """Satu-satunya aksi klik bot ini. Konservatif:
        - hanya di genesis.dhorse.fun/mine
        - hanya tombol yang teksnya persis 'Claim' (atau 'Claim now')
        - batal bila tombol mengandung kata terlarang / disabled."""
        if ALLOWED_HOST not in page.url or "/mine" not in page.url:
            log(f"BATAL_KLIK: URL bukan /mine: {page.url}")
            return False
        candidates = page.get_by_role("button", name=re.compile(r"^claim( now)?$", re.I))
        n = candidates.count()
        if n == 0:
            # fallback: tombol apa pun yang teks persisnya Claim
            candidates = page.locator("button", has_text=re.compile(r"^Claim$"))
            n = candidates.count()
        if n != 1:
            log(f"BATAL_KLIK: ditemukan {n} tombol Claim (harus tepat 1). Tidak diklik.")
            return False
        btn = candidates.first
        try:
            label = (btn.inner_text() or "").strip().lower()
        except Exception:
            label = ""
        if any(f in label for f in FORBIDDEN_LABELS) or label not in ("claim", "claim now"):
            log(f"BATAL_KLIK: label tombol tidak bersih: {label!r}")
            return False
        if not btn.is_enabled():
            log("BATAL_KLIK: tombol Claim disabled.")
            return False
        log("Klik Claim (1x) ...")
        btn.click(timeout=10000)
        return True


# ---------------------------------------------------------------- selftest

FIXTURE_1 = """
Mining epoch #58 block 970,937 MY POWER 110 power Darkhorse Knight
MINED • CLAIMABLE 0.7800 horseshoes block in progress, output due in 4 minutes
CLAIMED 1,300 TO CLAIM 0.7800 Claim
"""
FIXTURE_2 = """
Sign in with X first — Connect with X — Muster your BTC record
"""
FIXTURE_3 = """
epoch 61 37/72 CLAIMABLE 12.3456 CLAIMED 14 power 110 Claim
"""


API_FIXTURE = {
    "live": True, "claimable": 12.3456, "blocksLeft": 35, "tipHeight": 970937,
    "dailyRate": 24.64, "claimed": 1300, "effectivePower": 110,
    "networkRank": 4321, "networkPower": 11244365, "blockSeconds": 600,
    "epochIndex": 60, "boostLabel": "knight",
    "history": [{"epochIndex": 59, "burned": 0, "at": "2026-11-12 06:59:00"},
                {"epochIndex": 58, "burned": 3.5, "at": "2026-11-11 18:59:00"}],
}


ME_FIXTURE = {"handle": "Didinska0610", "checkinToday": False, "checkinDays": 6,
              "mustered": True, "walletAddress": "bc1pfixture"}
LB_FIXTURE = {"rows": [{"handle": "01573bit", "tier": "partner", "points": 200408},
                       {"handle": "Didinska0610", "tier": "knight", "points": 1234}],
              "me": {"rank": 777}}
NET_FIXTURE = {"miners": 41567, "totalPower": 11244365,
               "top": [{"handle": "HougeSol", "power": 7420},
                       {"handle": "didinska0610", "power": 110}]}


def selftest() -> int:
    sa = parse_status_json(API_FIXTURE)
    assert sa.via_api and sa.logged_in, sa
    assert abs(sa.claimable - 12.3456) < 1e-9 and sa.blocks_left() == 35, sa
    assert sa.minutes_left_hint == 350 and sa.tip_height == 970937, sa
    assert sa.epoch == 61 and sa.claimed_total == 1300, sa
    assert sa.network_rank == 4321 and sa.network_power == 11244365, sa
    me = parse_me_json(ME_FIXTURE)
    assert me.logged_in and me.handle == "Didinska0610", me
    assert me.checkin_today is False and me.checkin_days == 6 and me.mustered, me
    bd = parse_board(LB_FIXTURE, NET_FIXTURE, me.handle, sa)
    assert bd.hs_rank == 777 and bd.hs_points == 1234 and bd.hs_in_top == 2, bd
    assert bd.hs_top_handle == "01573bit" and bd.power_rank == 4321, bd
    assert bd.power_in_top == 2 and bd.miners == 41567, bd
    assert board_lines(bd, me.handle), bd
    s1 = parse_mine_text(FIXTURE_1)
    assert s1.logged_in and abs((s1.claimable or 0) - 0.78) < 1e-9, s1
    assert s1.minutes_left_hint == 4, s1
    s2 = parse_mine_text(FIXTURE_2)
    assert not s2.logged_in, s2
    s3 = parse_mine_text(FIXTURE_3)
    assert s3.logged_in and abs((s3.claimable or 0) - 12.3456) < 1e-9, s3
    assert s3.block_in_round == 37 and s3.blocks_left() == 35, s3
    print("SELFTEST OK:", json.dumps(asdict(s1)), "|", json.dumps(asdict(s3)))
    return 0


# ------------------------------------------------------- mode cookie-env
# Alternatif tanpa browser & tanpa login X berulang di VPS:
# kredensialnya BUKAN private key (situs tidak punya login private key /
# signature sama sekali — satu-satunya login di bundle resminya adalah
# /api/x/login), melainkan COOKIE SESI hasil login X itu sendiri.
# Ambil sekali dengan export_cookie.py (atau salin header Cookie dari
# browser kamu sendiri), taruh di .env VPS:  DHORSE_COOKIE="name=...; ..."
# Cookie = kata sandi akunmu. Jangan dibagikan, jangan di-commit
# (.env sudah masuk .gitignore), chmod 600.
# Catatan: cookie cf_clearance dari Cloudflare kadang terikat IP/UA
# browser asal — bila mode ini menjawab 403, pakai mode browser biasa
# (profil persisten) yang kebal masalah itu.

ENV_FILE = os.path.join(HERE, ".env")
COOKIE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/130.0.0.0 Safari/537.36")


def load_ua() -> str:
    """UA untuk mode cookie. cf_clearance kadang terikat UA browser asal,
    jadi UA bisa dioverride lewat DHORSE_UA di env/.env (samakan persis
    dengan User-Agent browser tempat cookie diambil)."""
    u = os.environ.get("DHORSE_UA", "").strip()
    if u:
        return u
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DHORSE_UA="):
                        v = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if v:
                            return v
        except OSError:
            pass
    return COOKIE_UA


def load_cookie() -> str | None:
    c = os.environ.get("DHORSE_COOKIE", "").strip()
    if c:
        return c
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DHORSE_COOKIE="):
                        v = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if v:
                            return v
        except OSError:
            pass
    return None


def _http_api(cookie: str | None, method: str, path: str, body: bytes | None = None,
              referer: str | None = None):
    import urllib.request
    import urllib.error
    req = urllib.request.Request(BASE + path, data=body, method=method)
    if cookie:
        req.add_header("Cookie", cookie)
    req.add_header("User-Agent", load_ua())
    req.add_header("Accept", "application/json")
    req.add_header("Referer", referer or MINE_URL)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.add_header("Origin", BASE)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return resp.status, {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        return e.code, parsed
    except Exception as e:
        return 0, {"error": f"NETWORK: {e}"}


def run_cookie_cycle(cookie: str, do_claim: bool, min_claim: float) -> MineState | None:
    status, body = _http_api(cookie, "GET", "/api/mining/status")
    if status == 401:
        log("SESI_MATI (cookie): /api/mining/status 401 — cookie sesi habis/dicabut. "
            "Ambil cookie baru sekali lewat export_cookie.py, perbarui .env. Bot tidak login sendiri.")
        return MineState(logged_in=False)
    if status == 403:
        log("BLOCKER (cookie): 403 dari Cloudflare — cookie dari browser lain kemungkinan "
            "tidak cocok dengan IP/UA VPS ini (cf_clearance). Pakai mode browser (login.py) di VPS ini.")
        return None
    if status != 200 or not isinstance(body, dict) or "claimable" not in body:
        log(f"BLOCKER (cookie): status HTTP {status} body={str(body)[:200]}")
        return None
    st = parse_status_json(body)
    _bl = st.blocks_left()
    _burn_m = re.search(r"riwayat_burn_total=([\d.]+)", st.raw_found or "")
    _burn = f" · 🔥 burn historis {fmt_num(float(_burn_m.group(1)), 1)}" if _burn_m else ""
    _lines = [
        f"🐴 Epoch {st.epoch if st.epoch is not None else '-'}"
        + (f" · sisa {_bl} blok (±{_bl * 10} mnt)" if _bl is not None else "")
        + f" · tip BTC {fmt_num(st.tip_height, 0)}",
    ]
    if _bl is not None:
        _lines.append(f"   Ronde   {bar(72 - _bl, 72)}")
    _lines.append(
        f"   💰 Claimable {fmt_num(st.claimable)} Horseshoes"
        f" · ✅ claimed {fmt_num(st.claimed_total, 1)}"
        f" · ⚡ power {fmt_num(st.power, 0)}"
        f" · 📈 {fmt_num(st.daily_rate, 1)}/hari{_burn}")
    if st.network_rank is not None:
        _lines.append(f"   🏆 Rank power se-network: #{fmt_num(st.network_rank, 0)}"
                      + (f" · total power network {fmt_num(st.network_power, 0)}" if st.network_power else ""))
    if st.claimable is not None and st.claimable < min_claim:
        _lines.append(f"   Target  {bar(st.claimable, min_claim, 10)} menuju {fmt_num(min_claim, 1)}")
    log_block(_lines)
    est_end = next_round_end_estimate()
    mins_to_est_end = (est_end - datetime.now(WIB)).total_seconds() / 60.0
    urgent = (st.blocks_left() is not None and st.blocks_left() <= 6) or mins_to_est_end <= 45
    if st.claimable is None:
        log("PARSE_GAGAL (cookie): claimable tidak ada di respons status.")
        return st
    if st.claimable >= min_claim:
        if not do_claim:
            log(f"DRY-RUN (cookie): claimable {st.claimable} >= {min_claim} — seharusnya CLAIM"
                f"{' (URGENT)' if urgent else ''}. Tidak dikirim.")
            return st
        c_status, c_body = _http_api(cookie, "POST", "/api/mining/claim", body=b"{}")
        if c_status == 200 and isinstance(c_body, dict) and isinstance(c_body.get("claimed"), (int, float)):
            s2, b2 = _http_api(cookie, "GET", "/api/mining/status")
            if s2 == 200 and isinstance(b2, dict) and "claimable" in b2:
                st2 = parse_status_json(b2)
                log_block([
                    f"🎉 CLAIM_BERHASIL_API +{fmt_num(c_body['claimed'])} Horseshoes masuk akun!",
                    f"   Sisa claimable {fmt_num(st2.claimable)} · total claimed {fmt_num(st2.claimed_total, 1)}",
                ])
                return st2
            log(f"🎉 CLAIM_BERHASIL_API +{fmt_num(c_body['claimed'])} Horseshoes masuk akun!")
            return st
        code = c_body.get("error") if isinstance(c_body, dict) else None
        if code == "FROZEN":
            log("BLOCKER: akun FROZEN menurut API claim. Berhenti mengklaim; cek akun di situs.")
            return st
        log(f"CLAIM_GAGAL (cookie): HTTP {c_status} error={code} body={str(c_body)[:200]}")
        return st
    if st.claimable > 0 and urgent:
        log(f"   ⏰ INFO: claimable {fmt_num(st.claimable)} < minimum {fmt_num(min_claim, 1)} dan ronde mau habis — "
            "pecahan <1 belum bisa di-claim menurut aturan situs.")
    else:
        log(f"   💤 Belum claim: {fmt_num(st.claimable)} < {fmt_num(min_claim, 1)}. Aman, nunggu genap.")
    return st


# ------------------------------------------------- daily check-in & board
# Daily Check-in (halaman utama /): state dari GET /api/me
# (checkinToday/checkinDays), aksi POST /api/checkin body "{}" -> +20
# Horseshoes ke pending (teks UI resmi: "20 horseshoes added to your
# pending"). Wrapper fetch UI sama persis dengan mining claim:
# same-origin + content-type json, TANPA Turnstile/token. "Hari" di sini
# hari SERVER — bot tidak menebak batas harinya; ia membaca checkinToday
# tiap siklus dan POST hanya saat nilainya false, jadi pergantian hari
# server otomatis tertangkap kapan pun loop berjalan.

def run_cookie_checkin(cookie: str, do_checkin: bool) -> tuple[str, MeState | None]:
    """Return (outcome, me). outcome: SUDAH | BERHASIL | DRY | GAGAL |
    FROZEN | PARSE_GAGAL | SESI_MATI | BLOCKER."""
    status, body = _http_api(cookie, "GET", "/api/me", referer=BASE + "/")
    if status == 401:
        log("SESI_MATI (cookie): /api/me 401 NOT_SIGNED_IN — cookie habis/dicabut. "
            "Ambil cookie baru sekali lewat export_cookie.py, perbarui .env.")
        return "SESI_MATI", None
    if status == 403:
        log("BLOCKER (cookie): 403 Cloudflare saat /api/me — cf_clearance tidak cocok "
            "dengan IP/UA VPS ini. Pakai mode browser (login.py) di VPS ini.")
        return "BLOCKER", None
    if status != 200 or not isinstance(body, dict):
        log(f"BLOCKER (cookie): /api/me HTTP {status} body={str(body)[:200]}")
        return "BLOCKER", None
    me = parse_me_json(body)
    if me.checkin_today is None:
        log("PARSE_GAGAL (check-in): field checkinToday tidak ada di /api/me — "
            "bentuk API berubah; check-in TIDAK ditebak/dipaksa. Lapor snapshot /api/me ke Bos.")
        return "PARSE_GAGAL", me
    days_txt = f" · total {me.checkin_days} hari" if me.checkin_days is not None else ""
    if me.checkin_today:
        log(f"📅 Daily check-in: SUDAH hari ini{days_txt}. Tidak ada aksi.")
        return "SUDAH", me
    if not do_checkin:
        log(f"📅 DRY-RUN: daily check-in BELUM hari ini{days_txt} — seharusnya POST "
            "/api/checkin sekarang (+20 Horseshoes). Tidak dikirim.")
        return "DRY", me
    c_status, c_body = _http_api(cookie, "POST", "/api/checkin", body=b"{}", referer=BASE + "/")
    if c_status == 401:
        log("SESI_MATI (cookie): POST /api/checkin 401 — sesi mati di tengah siklus.")
        return "SESI_MATI", me
    err = c_body.get("error") if isinstance(c_body, dict) else None
    if c_status == 200:
        # verifikasi persis cara UI: panggil ulang /api/me
        s2, b2 = _http_api(cookie, "GET", "/api/me", referer=BASE + "/")
        if s2 == 200 and isinstance(b2, dict):
            me2 = parse_me_json(b2)
            if me2.checkin_today:
                d2 = f" · total {me2.checkin_days} hari" if me2.checkin_days is not None else ""
                log(f"📅✅ CHECKIN_BERHASIL: +20 Horseshoes masuk pending{d2} "
                    f"(terverifikasi checkinToday=true).")
                return "BERHASIL", me2
        log("📅✅ CHECKIN_TERKIRIM: POST /api/checkin menjawab 200, tapi verifikasi "
            "/api/me belum menegaskan checkinToday=true — cek manual sekali; bot tidak POST ulang siklus ini.")
        return "BERHASIL", me
    if err and ("ALREADY" in str(err).upper() or "CHECKED" in str(err).upper()):
        log(f"📅 Daily check-in: server menjawab {err} — dianggap SUDAH hari ini.")
        return "SUDAH", me
    if err == "FROZEN":
        log("BLOCKER: akun FROZEN menurut API check-in. Berhenti check-in; cek akun di situs.")
        return "FROZEN", me
    log(f"📅 CHECKIN_GAGAL: HTTP {c_status} error={err} body={str(c_body)[:200]}")
    return "GAGAL", me


def fetch_board(cookie: str | None, handle: str | None = None,
                st: MineState | None = None) -> BoardState | None:
    """Baca /board persis cara UI: GET /api/leaderboard (tab Horseshoes)
    + GET /api/mining/network (tab Power) + rank power dari status mining.
    Dua endpoint pertama PUBLIK — tanpa cookie pun jalan (rank pribadi
    kosong). Bila handle belum diketahui dan ada cookie, ambil dari /api/me."""
    if handle is None and cookie:
        s_me, b_me = _http_api(cookie, "GET", "/api/me", referer=BASE + "/board")
        if s_me == 200 and isinstance(b_me, dict):
            handle = parse_me_json(b_me).handle
    s_lb, b_lb = _http_api(cookie, "GET", "/api/leaderboard", referer=BASE + "/board")
    s_nw, b_nw = _http_api(cookie, "GET", "/api/mining/network", referer=BASE + "/board")
    if s_lb != 200 and s_nw != 200:
        log(f"BOARD_GAGAL: leaderboard HTTP {s_lb}, network HTTP {s_nw}.")
        return None
    b = parse_board(b_lb if s_lb == 200 else None,
                    b_nw if s_nw == 200 else None, handle, st)
    log_block(board_lines(b, handle))
    return b


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="DarkHorse Genesis auto-claim")
    ap.add_argument("--once", action="store_true", help="satu siklus lalu berhenti")
    ap.add_argument("--loop", action="store_true", help="jaga terus (default tempo adaptif)")
    ap.add_argument("--dry-run", action="store_true", help="tidak klik Claim, hanya lapor")
    ap.add_argument("--inspect", action="store_true", help="simpan snapshot teks + network log")
    ap.add_argument("--headed", action="store_true", help="browser terlihat (debug)")
    ap.add_argument("--min-claim", type=float, default=1.0, help="minimum claimable untuk claim (default 1.0, minimum situs)")
    ap.add_argument("--interval", type=int, default=300, help="tempo dasar polling detik (default 300)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cookie", action="store_true",
                    help="mode HTTP murni memakai DHORSE_COOKIE dari env/.env (tanpa browser)")
    ap.add_argument("--no-checkin", action="store_true",
                    help="matikan daily check-in (default: aktif, +20/hari)")
    ap.add_argument("--no-board", action="store_true",
                    help="matikan laporan rank/power /board (default: aktif)")
    ap.add_argument("--board-only", action="store_true",
                    help="cetak board (rank Horseshoes + power) lalu berhenti; "
                         "tanpa --cookie jalan versi publik tanpa login")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.min_claim < 1.0:
        log("Peringatan: --min-claim di bawah 1.0 akan ditolak situs; dipatok ke 1.0")
        args.min_claim = 1.0
    if not args.once and not args.loop:
        args.once = True

    if args.board_only:
        # Board publik: dua endpoint-nya tidak butuh login; dengan cookie
        # rank pribadi ikut tampil. Tidak ada aksi tulis apa pun di sini.
        cookie = load_cookie() if args.cookie else None
        if args.cookie and not cookie:
            log("Info: DHORSE_COOKIE tidak ada — board versi publik (rank pribadi kosong).")
        b = fetch_board(cookie)
        return 0 if b is not None else 2

    if args.cookie:
        cookie = load_cookie()
        if not cookie:
            log("BLOCKER (cookie): DHORSE_COOKIE belum di-set. Taruh di .env folder ini: "
                "DHORSE_COOKIE=\"<header Cookie dari sesi loginmu>\" — ambil sekali via export_cookie.py. "
                "Ingat: cookie = kredensial akun, perlakukan seperti password.")
            return 2
        banner("cookie (HTTP murni, tanpa browser)", args.min_claim, args.interval,
               loop=args.loop, dry=args.dry_run)
        cycle_no = 0
        while True:
            cycle_no += 1
            dead = False
            me_handle: str | None = None
            ck_outcome: str | None = None
            if not args.no_checkin:
                ck_outcome, me_state = run_cookie_checkin(cookie, do_checkin=not args.dry_run)
                if me_state is not None:
                    me_handle = me_state.handle
                if ck_outcome == "SESI_MATI":
                    dead = True
            st = None
            if not dead:
                st = run_cookie_cycle(cookie, do_claim=not args.dry_run, min_claim=args.min_claim)
                if st is not None and not st.logged_in:
                    dead = True
            if not args.no_board and not dead:
                # --once: selalu. --loop: siklus pertama, tiap 6 siklus
                # (±30 mnt), dan tepat sesudah check-in berhasil.
                if args.once or cycle_no == 1 or cycle_no % 6 == 0 or ck_outcome == "BERHASIL":
                    fetch_board(cookie, handle=me_handle, st=st)
            if args.once:
                return 0
            if dead:
                log("Loop cookie berhenti: sesi mati.")
                return 2
            sleep_s = args.interval
            if st is not None:
                bl = st.blocks_left()
                mins_est = (next_round_end_estimate() - datetime.now(WIB)).total_seconds() / 60.0
                if (bl is not None and bl <= 6) or mins_est <= 60:
                    sleep_s = 60
                if mins_est <= 15:
                    sleep_s = 30
            _human = f"±{sleep_s // 60} mnt" if sleep_s >= 60 else f"{sleep_s} dtk"
            log(f"⏳ Cek lagi {_human} lagi ...")
            time.sleep(sleep_s)

    bot = ClaimBot(headless=not args.headed, inspect=args.inspect,
                   do_checkin_feature=not args.no_checkin,
                   show_board=not args.no_board)
    while True:
        st = bot.run_cycle(do_claim=not args.dry_run, min_claim=args.min_claim)
        if args.once:
            return 0
        # tempo adaptif: rapatkan saat ronde mendekati akhir
        sleep_s = args.interval
        if st is not None:
            bl = st.blocks_left() if hasattr(st, "blocks_left") else None
            mins_est = (next_round_end_estimate() - datetime.now(WIB)).total_seconds() / 60.0
            if (st.minutes_left_hint is not None and st.minutes_left_hint <= 60) or \
               (bl is not None and bl <= 6) or mins_est <= 60:
                sleep_s = 60
            if (st.minutes_left_hint is not None and st.minutes_left_hint <= 15) or mins_est <= 15:
                sleep_s = 30
            if not st.logged_in:
                log("Loop berhenti: sesi mati, perlu login.py lagi.")
                return 2
        log(f"Tidur {sleep_s} dtk ...")
        time.sleep(sleep_s)


if __name__ == "__main__":
    sys.exit(main())
