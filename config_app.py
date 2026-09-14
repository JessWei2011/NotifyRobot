#!/usr/bin/env python3
"""本機自選股設定頁；僅監聽本機 127.0.0.1。"""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
CODE_PATTERN = re.compile(r"^[0-9A-Za-z]{4,6}$")


def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        return json.load(config_file)


def save_watchlist(items: object) -> list[dict[str, str]]:
    if not isinstance(items, list):
        raise ValueError("自選股格式不正確")
    validated: list[dict[str, str]] = []
    codes: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("每一筆自選股都必須包含代號與名稱")
        code = str(item.get("code", "")).strip().upper()
        name = str(item.get("name", "")).strip()
        if not CODE_PATTERN.fullmatch(code):
            raise ValueError(f"股票代號「{code}」格式不正確，請輸入 4～6 碼代號")
        if not name:
            raise ValueError(f"{code} 尚未填寫股票名稱")
        if code in codes:
            raise ValueError(f"股票代號 {code} 重複")
        codes.add(code)
        validated.append({"code": code, "name": name})

    config = load_config()
    config["watchlist"] = validated
    temporary_path = CONFIG_PATH.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_path.replace(CONFIG_PATH)
    return validated


PAGE = r'''<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NotifyRobot 設定</title>
<style>
:root { color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", sans-serif; }
body { margin:0; min-height:100vh; background:#101726; color:#eff4ff; display:grid; place-items:start center; }
main { width:min(720px, calc(100% - 32px)); margin:48px 0; }
h1 { margin:0 0 8px; font-size:28px; } .hint { color:#aebbd2; line-height:1.6; margin:0 0 28px; }
.card { background:#182238; border:1px solid #293a5b; border-radius:16px; padding:18px; box-shadow:0 16px 45px #0004; }
.row { display:grid; grid-template-columns:150px 1fr auto; gap:10px; margin:10px 0; }
input { min-width:0; box-sizing:border-box; border:1px solid #405679; border-radius:9px; padding:11px 12px; color:#eff4ff; background:#0d1525; font-size:16px; }
button { border:0; border-radius:9px; padding:10px 14px; font-size:15px; cursor:pointer; font-weight:600; }
.remove { background:#35213a; color:#ffc5dd; } .add { background:#263957; color:#cbe0ff; margin-top:8px; }
.save { width:100%; background:#4b8cff; color:white; margin-top:22px; padding:13px; } .save:disabled { opacity:.55; cursor:wait; }
#status { min-height:24px; margin:14px 2px 0; color:#aebbd2; } #status.ok { color:#8ee6b1; } #status.error { color:#ff9aad; }
@media (max-width:520px) { .row { grid-template-columns:1fr auto; } .row input:first-child { grid-column:1 / -1; } }
</style></head><body><main>
<h1>NotifyRobot 個股通知</h1>
<p class="hint">這是手動加上的通知清單。永豐持股同步恢復後，持股會與此清單合併；ETF 不會推送。</p>
<div class="card"><div id="list"></div><button class="add" id="add" type="button">＋ 新增個股</button><button class="save" id="save" type="button">儲存通知清單</button><div id="status" role="status"></div></div>
</main><script>
const list=document.querySelector('#list'), status=document.querySelector('#status'), save=document.querySelector('#save');
function row(stock={code:'',name:''}) { const el=document.createElement('div'); el.className='row'; el.innerHTML=`<input class="code" maxlength="6" placeholder="代號，例如 2330" value="${escapeHtml(stock.code)}"><input class="name" maxlength="30" placeholder="名稱，例如 台積電" value="${escapeHtml(stock.name)}"><button type="button" class="remove">刪除</button>`; el.querySelector('.remove').onclick=()=>el.remove(); list.append(el); }
function escapeHtml(text) { const el=document.createElement('span'); el.textContent=text||''; return el.innerHTML; }
function message(text, type='') { status.className=type; status.textContent=text; }
async function load() { const r=await fetch('/api/watchlist'); const data=await r.json(); data.watchlist.forEach(row); if(!data.watchlist.length) row(); }
document.querySelector('#add').onclick=()=>row();
save.onclick=async()=> { const watchlist=[...document.querySelectorAll('.row')].map(el=>({code:el.querySelector('.code').value.trim(),name:el.querySelector('.name').value.trim()})).filter(item=>item.code||item.name); save.disabled=true; message('儲存中…'); try { const r=await fetch('/api/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({watchlist})}); const data=await r.json(); if(!r.ok) throw new Error(data.error||'儲存失敗'); message(`已儲存 ${data.watchlist.length} 檔個股。下一次推播會使用新設定。`,'ok'); } catch(e) { message(e.message,'error'); } finally { save.disabled=false; } };
load().catch(()=>message('無法讀取 config.json','error'));
</script></body></html>'''


class ConfigHandler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if self.path == "/":
            content = PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/api/watchlist":
            self.send_json(HTTPStatus.OK, {"watchlist": load_config().get("watchlist", [])})
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/api/watchlist":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            self.send_json(HTTPStatus.OK, {"watchlist": save_watchlist(payload.get("watchlist"))})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8765), ConfigHandler)
    print("設定頁已啟動：http://127.0.0.1:8765")
    print("按 Ctrl+C 可關閉設定頁。")
    server.serve_forever()
