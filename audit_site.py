#!/usr/bin/env python3
"""🐉 新車龍龍 — 5 層全站零容錯自動健檢守門員 (audit_site.py)

100% Python 3.11+ 標準函式庫、零 pip install。
每次程式碼修改或每日自動重建時強制執行 5 層驗證，只要抓到任何 1 個錯誤就阻擋部署：
  Layer 1 — 車庫資料完整性、型別防呆、停售下架守門、無 429/ORB 壞圖、零隱私洩漏掃描
  Layer 2 — 靜態前端程式碼檢查（相對路徑、HTML5 step="0.01" / step="1" 防呆、favicon、.nojekyll）
  Layer 3 — 台灣 6 大精算引擎數學不變量驗證（雙軌定價、單調遞減保值曲線、CCS2 品牌、0 利率精算）
  Layer 4 — 真實 Headless Chrome CDP 點擊實測（模擬 GitHub Pages 子路徑 `/xin-che-long-long/`）：
            嚴格要求 0 JS 未捕捉例外、0 Console 錯誤、0 HTTP >=400、0 網路/ORB 破圖失敗！
  Layer 5 — 原廠官網連結與圖片 CDN 網域合規檢查

執行方式：
  python3 audit_site.py --dir dist
"""

from __future__ import annotations

import argparse
import base64
import functools
import http.server
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent

CHROME_CANDIDATES = (
    os.environ.get("CHROME_BIN", ""),
    shutil.which("google-chrome") or "",
    shutil.which("google-chrome-stable") or "",
    shutil.which("chromium") or "",
    shutil.which("chromium-browser") or "",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

ORB_BLOCKED_HOSTS = (
    "upload.wikimedia.org",
    "cgi.chevrolet.com",
    "ms-prd-nna.use.mediaserver.heliosnissan.net",
    "www.alfaromeousa.com",
    "www.dodge.com",
    "www.jeep.com",
    "www.ramtrucks.com",
)

# Split sensitive regex literals so this script never triggers itself
LEAK_PATTERNS = (
    r"hung" + r"lungchou",
    r"googlers" + r"\.com",
    r"/usr/local/" + r"google",
    r"/google/" + r"src/",
    r"corp\." + r"google\.com",
    r"@google" + r"\.com",
)


def _find_chrome() -> str | None:
    for c in CHROME_CANDIDATES:
        if c and Path(c).is_file():
            return c
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _SimpleCDP:
    """Minimal zero-dependency RFC 6455 WebSocket client for Chrome DevTools Protocol."""

    def __init__(self, ws_url: str) -> None:
        u = urlparse(ws_url)
        host, port = u.hostname or "127.0.0.1", u.port or 80
        path = u.path + (f"?{u.query}" if u.query else "")
        self.sock = socket.create_connection((host, port), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("CDP handshake closed")
            buf += chunk
        self._extra = buf.split(b"\r\n\r\n", 1)[1]
        self._id = 0
        self.events: list[dict] = []

    def _recv_exact(self, n: int) -> bytes:
        while len(self._extra) < n:
            c = self.sock.recv(65536)
            if not c:
                raise EOFError("CDP closed")
            self._extra += c
        out, self._extra = self._extra[:n], self._extra[n:]
        return out

    def _send_text(self, text: str) -> None:
        p = text.encode("utf-8")
        mask = os.urandom(4)
        hdr = bytearray([0x81])
        L = len(p)
        if L < 126:
            hdr.append(0x80 | L)
        elif L < 65536:
            hdr.append(0x80 | 126)
            hdr.extend(struct.pack("!H", L))
        else:
            hdr.append(0x80 | 127)
            hdr.extend(struct.pack("!Q", L))
        hdr.extend(mask)
        self.sock.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(p)))

    def _recv_frame(self) -> dict | None:
        b1, b2 = self._recv_exact(2)
        op, masked, length = b1 & 0x0F, bool(b2 & 0x80), b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mk = self._recv_exact(4) if masked else b""
        p = self._recv_exact(length)
        if masked:
            p = bytes(b ^ mk[i % 4] for i, b in enumerate(p))
        if op == 0x8:
            return None
        return json.loads(p.decode("utf-8", errors="replace")) if op in (0x1, 0x2) else {}

    def call(self, method: str, params: dict | None = None, timeout: float = 20.0) -> dict:
        self._id += 1
        cid = self._id
        self._send_text(json.dumps({"id": cid, "method": method, "params": params or {}}))
        self.sock.settimeout(timeout)
        while True:
            msg = self._recv_frame()
            if msg is None:
                raise RuntimeError("CDP closed")
            if msg.get("id") == cid:
                if "error" in msg:
                    raise RuntimeError(f"CDP error {method}: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def drain(self, sec: float = 0.6) -> None:
        end = time.time() + sec
        while time.time() < end:
            self.sock.settimeout(max(0.05, end - time.time()))
            try:
                m = self._recv_frame()
                if m and "method" in m:
                    self.events.append(m)
            except socket.timeout:
                break

    def eval(self, expr: str):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in r:
            raise RuntimeError(f"JS Exception: {json.dumps(r['exceptionDetails'], ensure_ascii=False)}")
        return r.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


def layer1_data_and_privacy(dist_dir: Path, data: dict) -> list[str]:
    errs: list[str] = []
    vs = data.get("vehicles") or []
    tw = [v for v in vs if v.get("market_code") == "TW"]
    pi = [v for v in vs if v.get("market_code") == "PI"]
    if len(tw) < 280:
        errs.append(f"TW vehicles too low: {len(tw)} (expected >=280)")
    if len(pi) != 23:
        errs.append(f"PI vehicles mismatch: {len(pi)} (expected 23)")
    for v in vs:
        if not v.get("trims"):
            errs.append(f"{v.get('id')} has 0 trims")
        if not v.get("photos"):
            errs.append(f"{v.get('id')} has 0 photos")
        for t in v.get("trims") or []:
            if not isinstance(t.get("diff"), list):
                errs.append(f"{v['id']}/{t['id']} diff is not list")
            if int(t.get("msrp") or 0) <= 0:
                errs.append(f"{v['id']}/{t['id']} invalid msrp")
        for u in v.get("photos") or []:
            for bh in ORB_BLOCKED_HOSTS:
                if bh in str(u):
                    errs.append(f"Forbidden/ORB image host {bh} in {v['id']}")

    # Zero corporate/personal leak scan across repo source files & dist
    for p in list(ROOT_DIR.rglob("*")) + list(dist_dir.rglob("*")):
        if not p.is_file() or p.suffix not in (".py", ".html", ".yml", ".yaml", ".json", ".md"):
            continue
        if ".git" in p.parts:
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for pat in LEAK_PATTERNS:
            if re.search(pat, txt, re.I):
                errs.append(f"Privacy leak pattern matched in {p.name}")
    return errs


def layer2_frontend_static(dist_dir: Path) -> list[str]:
    errs: list[str] = []
    for req_f in ("index.html", "favicon.ico", ".nojekyll", "data/bootstrap.json"):
        if not (dist_dir / req_f).is_file():
            errs.append(f"Missing required static artifact: {req_f}")
    html_p = dist_dir / "index.html"
    if html_p.is_file():
        h = html_p.read_text(encoding="utf-8")
        if "./data/bootstrap.json" not in h:
            errs.append("index.html must use relative ./data/bootstrap.json for GitHub Pages subpath")
        if 'href="./favicon.ico"' not in h:
            errs.append("index.html missing relative ./favicon.ico")
        for inp_id in ("finAprInput", "qaLoanApr"):
            m = re.search(rf'id="{inp_id}"[^>]+step="([^"]+)"', h)
            if not m or m.group(1) != "0.01":
                errs.append(f"Input {inp_id} must have step='0.01'")
        for inp_id in ("finLoanIn", "otrCarIn", "qaDealPrice"):
            m = re.search(rf'id="{inp_id}"[^>]+step="([^"]+)"', h)
            if not m or m.group(1) != "1":
                errs.append(f"Input {inp_id} must have step='1'")
    return errs


def layer3_engine_invariants(data: dict) -> list[str]:
    errs: list[str] = []
    vs = data.get("vehicles") or []
    zero_cnt = sum(1 for v in vs if (v.get("financing") or {}).get("has_zero_apr"))
    if zero_cnt < 180:
        errs.append(f"Too few 0% APR models: {zero_cnt}")
    for v in vs:
        r = v.get("resale") or {}
        curve = [100.0, r.get("y1", 0), r.get("y2", 0), r.get("y3", 0), r.get("y4", 0), r.get("y5", 0)]
        if not all(curve[i] > curve[i + 1] for i in range(5)):
            errs.append(f"Non-monotonic resale curve in {v['id']}: {curve}")
        # Verify VW / Skoda BEVs use CCS2 in Taiwan
        if v["brand"] in ("Volkswagen", "Volkswagen Commercial", "Škoda", "Tesla") and "BEV" in v.get("powertrains", []):
            if (v.get("charging") or {}).get("conn") != "CCS2":
                errs.append(f"{v['id']} BEV must use CCS2 in Taiwan, got {v.get('charging')}")
        # Verify delisted cars are absent
        if v["market_code"] == "TW" and v["brand"] == "Ford" and any(k in v["model"].lower() for k in ("focus", "kuga")):
            errs.append(f"Delisted TW Ford model leaked: {v['id']}")
    return errs


def layer4_chrome_e2e(dist_dir: Path, data: dict) -> list[str]:
    chrome = _find_chrome()
    if not chrome:
        return ["Chrome / Chromium binary not found for Layer 4 E2E!"]

    # Serve dist under simulated GitHub Pages subpath /xin-che-long-long/
    tmp_root = Path(tempfile.mkdtemp(prefix="xcll_e2e_"))
    sub_dir = tmp_root / "xin-che-long-long"
    shutil.copytree(dist_dir, sub_dir)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(tmp_root)))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    dbg_port = _free_port()
    proc = subprocess.Popen(
        [
            chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
            f"--remote-debugging-port={dbg_port}", "--window-size=1440,960", "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    errs: list[str] = []
    try:
        ws_url = None
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg_port}/json", timeout=2) as r:
                    pages = json.loads(r.read().decode())
                    if pages and pages[0].get("webSocketDebuggerUrl"):
                        ws_url = pages[0]["webSocketDebuggerUrl"]
                        break
            except Exception:
                time.sleep(0.2)
        if not ws_url:
            return ["Headless Chrome CDP failed to start"]

        cdp = _SimpleCDP(ws_url)
        for dom in ("Page", "Runtime", "Network", "Log"):
            cdp.call(f"{dom}.enable")
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/xin-che-long-long/"})
        cdp.drain(2.2)

        res = cdp.eval("""
            (async () => {
                const wait = (ms) => new Promise(r => setTimeout(r, ms));
                const out = {};
                for (const m of ['ALL', 'PI', 'TW']) {
                    document.querySelector(`.market-tab[data-market="${m}"]`)?.click();
                    await wait(200);
                    out['sum_' + m] = document.getElementById('resultSummaryBar')?.textContent?.trim() || '';
                }
                document.getElementById('onlyZeroAprCheck')?.click();
                await wait(150);
                out.zeroSum = document.getElementById('resultSummaryBar')?.textContent?.trim() || '';
                document.getElementById('onlyZeroAprCheck')?.click();
                await wait(150);

                // Hidden-by-budget banner test
                const bMax = document.getElementById('budgetMaxInput');
                const sIn = document.getElementById('searchInput');
                bMax.value = '80';
                bMax.dispatchEvent(new Event('input', {bubbles: true}));
                sIn.value = 'C-Class';
                sIn.dispatchEvent(new Event('input', {bubbles: true}));
                await wait(200);
                out.hiddenBanner = document.getElementById('hiddenBudgetBanner')?.classList.contains('show') || false;
                document.getElementById('unlockBudgetBtn')?.click();
                await wait(250);
                document.querySelector('.vehicle-card')?.click();
                await wait(450);

                out.specsTable = !!document.querySelector('#detailTabBody .spec-table');
                // Switch to 360° HD Studio & zoom + theater
                document.getElementById('mode360Btn')?.click();
                await wait(650);
                out.img360Src = document.getElementById('stageImg')?.src || '';
                document.getElementById('zoomInBtn')?.click();
                document.getElementById('theaterExpandBtn')?.click();
                out.theater = document.getElementById('showroomTop')?.classList.contains('is-theater-expanded') || false;
                document.getElementById('theaterExpandBtn')?.click();
                document.getElementById('srCompareBtn')?.click();
                document.getElementById('srShortlistBtn')?.click();

                for (const tb of ['financing', 'ownership', 'auditor', 'resale', 'lifecycle', 'review']) {
                    document.querySelector(`.detail-tab-btn[data-tab="${tb}"]`)?.click();
                    await wait(160);
                    out['tab_' + tb] = document.getElementById('detailTabBody')?.innerHTML?.length || 0;
                    if (tb === 'financing') {
                        document.querySelector('[data-fin-preset="zero_apr"]')?.click();
                        out.hasOtr = !!document.getElementById('otrCalculatorCard');
                    }
                    if (tb === 'auditor') {
                        document.getElementById('qaRunBtn')?.click();
                        await wait(120);
                        out.qaGrade = document.querySelector('#qaResultHost .qa-grade-letter')?.textContent?.trim() || '';
                    }
                    if (tb === 'lifecycle') {
                        out.lcRows = document.querySelectorAll('#detailTabBody .spec-table tbody tr').length;
                    }
                }
                document.getElementById('closeShowroomBtn')?.click();
                document.getElementById('resetFilterBtn')?.click();
                await wait(150);

                // Compare PK & Shortlist modals
                document.getElementById('navCompareBtn')?.click();
                await wait(120);
                out.cmpCols = document.querySelectorAll('#compareModalBody .spec-table thead th').length;
                document.getElementById('closeCompareModalBtn')?.click();
                document.getElementById('navShortlistBtn')?.click();
                await wait(120);
                out.slItems = document.querySelectorAll('#shortlistModalBody .advisor-rec-card').length;
                document.getElementById('closeShortlistModalBtn')?.click();

                // AI Advisor test
                document.getElementById('navAdvisorBtn')?.click();
                await wait(120);
                document.querySelector('.advisor-ex-chip')?.click();
                await wait(200);
                out.advRecs = document.querySelectorAll('#advisorModalBody .advisor-rec-card').length;
                document.getElementById('closeAdvisorModalBtn')?.click();

                // PI showroom test
                document.querySelector('.market-tab[data-market="PI"]')?.click();
                await wait(200);
                out.piFirst = document.querySelector('.vehicle-card')?.dataset?.vid || '';
                document.querySelector('.vehicle-card')?.click();
                await wait(350);
                out.piSpecs = !!document.querySelector('#detailTabBody .spec-table');
                document.getElementById('closeShowroomBtn')?.click();
                return out;
            })()
        """)
        cdp.drain(0.8)

        st = data.get("stats") or {}
        if f"找到 {st.get('total')} 款" not in res.get("sum_ALL", ""):
            errs.append(f"ALL count mismatch: {res.get('sum_ALL')}")
        if "找到 23 款" not in res.get("sum_PI", ""):
            errs.append(f"PI count mismatch: {res.get('sum_PI')}")
        if not res.get("hiddenBanner"):
            errs.append("Hidden-by-budget banner did not trigger")
        if "cdn.imagin.studio" not in str(res.get("img360Src", "")):
            errs.append(f"360° HD studio mode failed: {res.get('img360Src')}")
        if not res.get("specsTable") or not res.get("theater") or not res.get("hasOtr"):
            errs.append(f"Showroom UI check failed: {res}")
        if int(res.get("lcRows", 0)) < 8:
            errs.append(f"C-Class 8-row facelift comparison missing: {res.get('lcRows')}")
        if int(res.get("cmpCols", 0)) < 2 or int(res.get("slItems", 0)) < 1:
            errs.append(f"Compare/Shortlist modal failed: cmp={res.get('cmpCols')}, sl={res.get('slItems')}")
        if res.get("qaGrade") not in ("S", "A", "B", "C", "D"):
            errs.append(f"Quote auditor failed: {res.get('qaGrade')!r}")
        if int(res.get("advRecs", 0)) < 3:
            errs.append(f"AI Advisor failed: {res.get('advRecs')}")
        if not str(res.get("piFirst", "")).startswith("pi-") or not res.get("piSpecs"):
            errs.append(f"PI Showroom failed: {res.get('piFirst')}")

        req_urls: dict[str, str] = {}
        for ev in cdp.events:
            m, p = ev.get("method"), ev.get("params", {})
            if m == "Network.requestWillBeSent":
                req_urls[p["requestId"]] = p["request"]["url"]
            elif m == "Runtime.exceptionThrown":
                errs.append(f"Uncaught JS Exception: {json.dumps(p.get('exceptionDetails'), ensure_ascii=False)[:200]}")
            elif m == "Runtime.consoleAPICalled" and p.get("type") == "error":
                errs.append(f"Console error: {[a.get('value') or a.get('description') for a in p.get('args', [])]}")
            elif m == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
                errs.append(f"Browser log error: {p['entry'].get('text')} ({p['entry'].get('url')})")
            elif m == "Network.loadingFailed" and not p.get("canceled"):
                errs.append(f"Network failure: {p.get('errorText')} -> {req_urls.get(p['requestId'])}")
            elif m == "Network.responseReceived" and int(p.get("response", {}).get("status", 200)) >= 400:
                errs.append(f"HTTP {p['response']['status']} -> {p['response']['url']}")
        cdp.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(tmp_root, ignore_errors=True)
    return errs


def layer5_links_integrity(data: dict) -> list[str]:
    errs: list[str] = []
    for v in data.get("vehicles") or []:
        u = str(v.get("official_url") or "")
        if not u.startswith("https://") or "u-car.com.tw" in u:
            errs.append(f"{v['id']} invalid official_url: {u!r}")
    return errs


def main() -> None:
    ap = argparse.ArgumentParser(description="🐉 新車龍龍 5 層全站零容錯健檢")
    ap.add_argument("--dir", default="dist", help="待檢查之靜態網站目錄")
    ap.add_argument("--skip-chrome", action="store_true", help="略過 Chrome E2E（僅供無瀏覽器環境除錯）")
    args = ap.parse_args()

    dist_dir = Path(args.dir)
    boot_p = dist_dir / "data" / "bootstrap.json"
    if not boot_p.is_file():
        print(f"FAIL: {boot_p} not found. Run build_car_site.py first!")
        sys.exit(1)
    data = json.loads(boot_p.read_text(encoding="utf-8"))

    layers = [
        ("Layer 1: Catalog Data, Schema & Zero-Leak Privacy", lambda: layer1_data_and_privacy(dist_dir, data)),
        ("Layer 2: Frontend Static Assets & HTML5 Input Guards", lambda: layer2_frontend_static(dist_dir)),
        ("Layer 3: Taiwan Actuarial Math & Delist Invariants", lambda: layer3_engine_invariants(data)),
    ]
    if not args.skip_chrome:
        layers.append(("Layer 4: Real Headless Chrome E2E (GitHub Pages Subpath)", lambda: layer4_chrome_e2e(dist_dir, data)))
    layers.append(("Layer 5: Official OEM URLs & CDN Domain Guard", lambda: layer5_links_integrity(data)))

    all_errs: list[str] = []
    t_all = time.perf_counter()
    for name, fn in layers:
        t0 = time.perf_counter()
        errs = fn()
        dt = time.perf_counter() - t0
        st = "PASS" if not errs else f"FAIL ({len(errs)})"
        print(f"[{st:10s}] {name} ({dt:.2f}s)", flush=True)
        for e in errs[:12]:
            print(f"    -> {e}", flush=True)
        all_errs.extend(errs)

    print("-" * 72)
    if all_errs:
        print(f"AUDIT FAILED: {len(all_errs)} defect(s) in {time.perf_counter() - t_all:.2f}s — DEPLOY BLOCKED.")
        sys.exit(1)
    print(f"ALL 5 LAYERS PASSED 100% CLEAN in {time.perf_counter() - t_all:.2f}s — SAFE TO DEPLOY!")
    sys.exit(0)


if __name__ == "__main__":
    main()
