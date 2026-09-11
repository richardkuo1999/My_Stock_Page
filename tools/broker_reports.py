"""broker_reports — 券商研究報告查詢（輕量索引 + 內文即時抓 Drive）

資料源：朋友分享的 Google Drive 資料夾，結構為
  tw_stocks/<代號-公司名>/<報告檔...>   個股報告（每檔一個子資料夾）
  sector/<YYMMDD_來源_主題..._分類.副檔名>  產業／總經／策略報告（扁平）
  Digitimes/<...>                          電子時報（科技供應鏈）
多數報告有配對的 .md 全文（朋友已把 PDF 轉好），本工具只碰 .md，不下載 PDF。

架構（選項 Y — 輕量索引）：
  本地只存「metadata 索引」（檔名解析出的欄位 + Drive file_id），不存內文。
  查詢走本地索引很快；需要讀某篇全文時才即時去 Drive 抓那一份 .md。

CLI（詳細見各子命令 --help；離線可測的在前，需憑證的在後）:
  python tools/broker_reports.py --stock 2330            # 查個股相關報告（列表+摘要）
  python tools/broker_reports.py --sector 記憶體          # 依主題/產業關鍵字查 sector 報告
  python tools/broker_reports.py --detail <file_id>       # 抓單篇 .md 全文（需 Drive 憑證）
  python tools/broker_reports.py --sync                   # 重建/更新本地 metadata 索引（需憑證）

回傳：一律 JSON。查詢類回 {"reports": [...]}；--detail 回 {"file_id","text",...}；
      失敗回 {"error": str}。

本檔分層：
  1. 純函式（檔名/資料夾解析、資料模型）— 不碰網路、可離線單元測試。← 本區
  2. 本地索引（SQLite）build/load/query。
  3. Drive API 存取（列檔、抓單篇 .md）。
  4. CLI 入口。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# sector/Digitimes 檔名最後一段的「分類」詞彙（實測看到這幾種）。
# 解析時用來把「分類」從主題中切出來；未知的一律歸 'unknown'。
KNOWN_CATEGORIES = {"sector", "news", "unsorted", "transcript", "archive"}

# 檔名日期為 6 碼 YYMMDD；YY 直接補 20xx（此資料庫皆 2025 之後）。
_DATE_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})$")


@dataclass
class ReportMeta:
    """一份報告的輕量 metadata（不含內文）。

    file_id / md_file_id 為 Drive 檔案 ID；查詢只用 metadata，讀全文時才用
    md_file_id 去 Drive 抓那一份 .md。scope 區分 'stock'（個股）或 'sector'。
    """

    file_id: str = ""          # 主檔（通常是 .md；沒有 .md 時退回 PDF/其他）Drive ID
    md_file_id: str = ""       # 配對 .md 的 Drive ID（有才可即時抓全文）
    filename: str = ""         # 原始檔名（含副檔名）
    scope: str = ""            # 'stock' | 'sector'
    stock_code: str = ""       # 個股代號（scope=stock 時）
    stock_name: str = ""       # 公司名（scope=stock 時）
    date: str = ""             # ISO 日期 'YYYY-MM-DD'（解析得到才有）
    broker: str = ""           # 來源／券商（sector 檔名第 2 段）
    topic: str = ""            # 主題（sector 檔名中段，可多詞）
    category: str = ""         # 分類（檔名最後一段，如 sector/news/transcript）
    mime: str = ""             # Drive mimeType（best-effort）

    def to_dict(self) -> dict:
        return asdict(self)


def _yymmdd_to_iso(token: str) -> str:
    """'YYMMDD' → 'YYYY-MM-DD'；不合法回空字串。

    此資料庫日期皆 2025 之後，YY 一律補 '20'。月/日超出範圍（如 00）視為無效，
    因為部分檔名用 '250900' 這種「月份不確定」寫法，日=00 時仍保留年月、日補 01。
    """
    m = _DATE_RE.match(token)
    if not m:
        return ""
    yy, mm, dd = m.group(1), m.group(2), m.group(3)
    month = int(mm)
    day = int(dd)
    if not (1 <= month <= 12):
        return ""
    if day == 0:  # 'YYMM00' → 當月，日補 01（保留可排序性）
        day = 1
    if not (1 <= day <= 31):
        return ""
    return f"20{yy}-{mm}-{day:02d}"


def parse_stock_folder(folder_name: str) -> tuple[str, str]:
    """解析個股資料夾名 '代號-公司名' → (code, name)。

    規則：以「第一個 '-'」切分——代號在前、其餘全是名稱（名稱本身可能含 '-'，
    如 '3673-TPK-KY'、'2637-慧洋-KY'）。無 '-' 或代號為空時，回 (整串, '')。
    'unknown' 名稱（如 '4573-unknown'）照原樣保留，讓呼叫端自行判斷。
    """
    folder_name = folder_name.strip()
    if "-" not in folder_name:
        return folder_name, ""
    code, name = folder_name.split("-", 1)
    return code.strip(), name.strip()


def parse_sector_filename(filename: str) -> dict:
    """解析 sector/Digitimes 扁平檔名 → metadata dict。

    典型格式：'YYMMDD_來源_主題..._分類.副檔名'
      例 '260911_中信_月營收評析_封測_半導體設備產業_sector.pdf'
         → date=2026-09-11, broker=中信, topic='月營收評析 封測 半導體設備產業',
           category=sector
         '260622_MS_DRAM_NAND_sector.md'
         → date=2026-06-22, broker=MS, topic='DRAM NAND', category=sector

    容錯：
      - 去副檔名後以 '_' 切段。
      - 第 1 段若是合法 YYMMDD 當日期，否則 date 留空、該段回歸主題。
      - 最後一段若在 KNOWN_CATEGORIES 當 category，否則 category='unknown' 且該段留在主題。
      - 第 2 段（日期之後）當 broker（來源/券商）。
      - 中間所有段合併成 topic（用空白連接，供關鍵字搜尋）。
    回 {date, broker, topic, category, ext}。任何缺項回空字串。
    """
    name = filename.strip()
    ext = ""
    if "." in name:
        name, ext = name.rsplit(".", 1)
        ext = ext.lower()

    parts = [p for p in name.split("_") if p != ""]
    result = {"date": "", "broker": "", "topic": "", "category": "", "ext": ext}
    if not parts:
        return result

    # 1) 日期（第 1 段）
    idx = 0
    iso = _yymmdd_to_iso(parts[0])
    if iso:
        result["date"] = iso
        idx = 1

    # 2) 分類（最後一段，若已知）
    if parts and parts[-1] in KNOWN_CATEGORIES:
        result["category"] = parts[-1]
        parts = parts[:-1]
    else:
        result["category"] = "unknown"

    remaining = parts[idx:]
    # 3) 來源／券商（日期後第一段）
    if remaining:
        result["broker"] = remaining[0]
        topic_parts = remaining[1:]
    else:
        topic_parts = []
    # 4) 主題（其餘合併）
    result["topic"] = " ".join(topic_parts)
    return result


def stem_of(filename: str) -> str:
    """去副檔名的檔名主幹，用來把 .md 和它配對的 .pdf/.docx 視為同一份報告。

    例 '260622_MS_DRAM_NAND_sector.md' 與 '..._sector.pdf' 的 stem 相同。
    注意：少數檔名主幹含 '.'（如 '260804_MS_光模塊政策解讀.pdf_sector'），
    僅切最後一個副檔名即可，因為配對檔的差異只在最末副檔名。
    """
    name = filename.strip()
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name


# 內文可即時抓取的純文字副檔名（優先 .md；.txt 次之）。PDF/docx 不抓。
TEXT_EXTS = {"md", "txt"}


def ext_of(filename: str) -> str:
    """回小寫副檔名（無則空字串）。"""
    if "." in filename:
        return filename.rsplit(".", 1)[1].lower()
    return ""


# ── 2. 本地輕量索引（SQLite；只存 metadata + Drive file_id，不存內文）──────────
#
# 為何 SQLite：單檔、免服務、內建在 Python；schema 對齊 ReportMeta。放在
# data/broker_reports.db（.gitignore 已排除 data/ 與 *.db）。查詢邏輯（評分/排序）
# 抽成純函式 _score_report / rank_reports，餵 list[ReportMeta] 即可離線單元測試，
# 不必真的開資料庫。

import os
import sqlite3
from datetime import datetime

# 索引預設路徑（相對 repo 根；呼叫端可覆寫）。
DEFAULT_DB_PATH = os.path.join("data", "broker_reports.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    file_id     TEXT PRIMARY KEY,
    md_file_id  TEXT,
    filename    TEXT,
    scope       TEXT,
    stock_code  TEXT,
    stock_name  TEXT,
    date        TEXT,
    broker      TEXT,
    topic       TEXT,
    category    TEXT,
    mime        TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_stock ON reports(stock_code);
CREATE INDEX IF NOT EXISTS idx_reports_scope ON reports(scope);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_COLUMNS = [
    "file_id", "md_file_id", "filename", "scope", "stock_code",
    "stock_name", "date", "broker", "topic", "category", "mime",
]


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """開啟（必要時建立）索引資料庫，套用 schema。回 sqlite3.Connection。"""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def build_index(records: list[ReportMeta], db_path: str = DEFAULT_DB_PATH) -> int:
    """把一批 ReportMeta 寫入索引（upsert by file_id）。回寫入筆數。

    用於 --sync：Drive 存取層列完檔、解析成 ReportMeta 後呼叫本函式落地。
    file_id 為主鍵 → 重跑只更新既有列、補上新列（增量友善）。
    """
    conn = connect(db_path)
    try:
        rows = [tuple(getattr(r, c) for c in _COLUMNS) for r in records]
        placeholders = ",".join(["?"] * len(_COLUMNS))
        conn.executemany(
            f"INSERT OR REPLACE INTO reports ({','.join(_COLUMNS)}) VALUES ({placeholders})",
            rows,
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('last_sync', ?)",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def _row_to_meta(row: sqlite3.Row) -> ReportMeta:
    return ReportMeta(**{c: (row[c] or "") for c in _COLUMNS})


def load_all(db_path: str = DEFAULT_DB_PATH) -> list[ReportMeta]:
    """讀出索引中所有報告（供離線測試 / 小規模掃描）。"""
    conn = connect(db_path)
    try:
        return [_row_to_meta(r) for r in conn.execute("SELECT * FROM reports")]
    finally:
        conn.close()


def index_stats(db_path: str = DEFAULT_DB_PATH) -> dict:
    """回索引概況（總數、個股/產業筆數、last_sync）供 CLI 顯示。"""
    conn = connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        stock = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE scope='stock'"
        ).fetchone()[0]
        sector = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE scope='sector'"
        ).fetchone()[0]
        row = conn.execute("SELECT value FROM meta WHERE key='last_sync'").fetchone()
        return {
            "total": total,
            "stock": stock,
            "sector": sector,
            "last_sync": row[0] if row else "",
        }
    finally:
        conn.close()


# ── 3. 查詢層（純評分邏輯 + 讀索引的子命令）──────────────────────────────────
#
# 評分先走「關鍵字重疊」起步（不需模型、離線可測）：把查詢字拆詞，數每份報告的
# 可搜文字（topic/broker/filename/stock_name）命中幾個 query 詞，命中越多分越高；
# 同分時新的（date 大）在前。語意搜尋當第二階段再疊加。

def _tokenize(text: str) -> list[str]:
    """極簡斷詞：英數以空白/底線切；中文逐字。回小寫 token 清單。

    中文不做分詞（避免相依），逐字比對已能命中「記憶體」「散熱」這類詞——因為
    報告主題字串也逐字含這些字。務實起步，語意層之後再強化。
    """
    text = (text or "").lower().replace("_", " ")
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if ch.isascii() and (ch.isalnum()):
            buf += ch
        else:
            if buf:
                tokens.append(buf)
                buf = ""
            if "\u4e00" <= ch <= "\u9fff":  # CJK 逐字成 token
                tokens.append(ch)
    if buf:
        tokens.append(buf)
    return tokens


def _searchable_text(r: ReportMeta) -> str:
    """一份報告可被關鍵字命中的欄位彙整。"""
    return " ".join([r.topic, r.broker, r.filename, r.stock_name, r.stock_code])


def _score_report(r: ReportMeta, query_tokens: list[str]) -> float:
    """回這份報告對查詢的相關度分數（0=完全不相關）。

    命中不同 query 詞的「涵蓋數」為主分（每個獨特命中 +1），有 .md 可讀 +0.1
    當微幅加權（能直接給 agent 全文的優先），純為排序穩定用。
    """
    if not query_tokens:
        return 0.0
    hay = set(_tokenize(_searchable_text(r)))
    hits = sum(1 for q in set(query_tokens) if q in hay)
    if hits == 0:
        return 0.0
    score = float(hits)
    if r.md_file_id:
        score += 0.1
    return score


def rank_reports(
    reports: list[ReportMeta], query: str, limit: int = 10
) -> list[ReportMeta]:
    """依相關度排序（純函式，離線可測）。分數 0 的剔除；同分新的在前。"""
    q_tokens = _tokenize(query)
    scored = [(r, _score_report(r, q_tokens)) for r in reports]
    scored = [(r, s) for r, s in scored if s > 0]
    scored.sort(key=lambda rs: (rs[1], rs[0].date), reverse=True)
    return [r for r, _ in scored[:limit]]


def query_stock(
    code: str, limit: int = 10, db_path: str = DEFAULT_DB_PATH
) -> list[ReportMeta]:
    """查某個股的報告：抓該 stock_code 的所有列，日期新到舊，取前 limit。"""
    code = code.strip().upper()
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM reports WHERE scope='stock' AND stock_code=? "
            "ORDER BY date DESC LIMIT ?",
            (code, limit),
        ).fetchall()
        return [_row_to_meta(r) for r in rows]
    finally:
        conn.close()


def query_sector(
    keyword: str, limit: int = 10, db_path: str = DEFAULT_DB_PATH
) -> list[ReportMeta]:
    """依關鍵字查 sector 報告：先用 SQL LIKE 粗篩，再用 rank_reports 精排。

    LIKE 粗篩降低要評分的筆數（sector 上千份）；中文逐字、英文詞皆可命中。
    """
    kw = keyword.strip()
    conn = connect(db_path)
    try:
        like = f"%{kw}%"
        rows = conn.execute(
            "SELECT * FROM reports WHERE scope='sector' AND "
            "(topic LIKE ? OR filename LIKE ? OR broker LIKE ?)",
            (like, like, like),
        ).fetchall()
        candidates = [_row_to_meta(r) for r in rows]
        return rank_reports(candidates, kw, limit=limit)
    finally:
        conn.close()




# ── 4. Google Drive 存取層（OAuth 使用者授權；列檔建索引 + 抓單篇 .md）─────────
#
# 認證：OAuth 使用者流程（用你的 Google 帳號讀「朋友分享給你」的資料夾）。
#   credentials.json  = Google Cloud OAuth client secret（你下載，放專案根，gitignore）
#   token.json        = 第一次授權後產生的存取/更新權杖（自動產生，gitignore）
# 兩者皆為機密，切勿 commit（見 .gitignore 的 broker reports 區）。
#
# 同步範圍（依已確認的 Drive 結構）：
#   納入：tw_stocks/<代號-名>/ 下所有檔、sector/ 扁平檔、Digitimes/ 扁平檔。
#   跳過：raw*.zip、_archive、_unsorted、us/cn/jp/kr_stocks（agent 主打台股）。
# 只把「可讀全文」的 .md/.txt 當主檔記 file_id 供即時抓；PDF 僅記為配對（不下載）。

import io as _io

# OAuth scope：只讀（drive.readonly 已足夠列檔+下載；最小權限原則）。
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_ROOT_FOLDER_ID = "1QpNct5743r8LBb8WKVkPe91JaAiHf9Ay"  # 朋友分享的根資料夾
_CREDENTIALS_PATH = os.getenv("BROKER_DRIVE_CREDENTIALS", "credentials.json")
_TOKEN_PATH = os.getenv("BROKER_DRIVE_TOKEN", "token.json")

# 頂層要跳過的資料夾名（大小寫不敏感比對）。
_SKIP_TOP = {"_archive", "_unsorted", "us_stocks", "cn_stocks", "jp_stocks", "kr_stocks"}


def _load_creds():
    """載入 / 更新 OAuth 憑證（不 build service）。供主流程與各執行緒共用同一份
    憑證、但各自 build 自己的 service（googleapiclient 的 service/http 非執行緒安全）。
    """
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None
    if os.path.exists(_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(_TOKEN_PATH, _DRIVE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(_CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"找不到 {_CREDENTIALS_PATH}；請先跑 OAuth 設定精靈取得 Google 憑證"
                )
            flow = InstalledAppFlow.from_client_secrets_file(_CREDENTIALS_PATH, _DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def _build_service(creds):
    """用既有 creds build 一個新的 Drive service（每執行緒各建一個，確保安全）。"""
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _drive_service():
    """建立並回傳已授權的 Drive API service（單執行緒用）。

    需要 credentials.json（OAuth client secret）；首次會開瀏覽器授權並存 token.json，
    之後用 refresh token 自動續期。缺 credentials.json 時丟 FileNotFoundError（CLI 轉成
    清楚的 error 訊息）。相依套件缺時丟 ImportError。
    """
    return _build_service(_load_creds())


def _list_children(service, folder_id: str) -> list[dict]:
    """列出某資料夾的直接子項（分頁全取）。回 [{id,name,mimeType}]。"""
    items: list[dict] = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        items.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


_FOLDER_MIME = "application/vnd.google-apps.folder"


def _pair_files_to_reports(files: list[dict], scope: str, stock=None) -> list[ReportMeta]:
    """把一組同層檔案（同一資料夾內）配對成 ReportMeta 清單。

    以 stem 分組：同 stem 的 .md + .pdf 視為同一份報告。主檔優先取可讀全文的
    .md/.txt（記 md_file_id + file_id）；若某 stem 只有 PDF，仍收錄（file_id=PDF、
    md_file_id 空、has_fulltext=false），讓 agent 至少知道有這份報告存在。

    stock: (code, name) tuple（scope='stock' 時）供填 stock 欄位。
    """
    groups: dict[str, dict] = {}
    for f in files:
        name = f.get("name", "")
        if f.get("mimeType") == _FOLDER_MIME:
            continue
        ext = ext_of(name)
        stem = stem_of(name)
        g = groups.setdefault(stem, {"md": None, "other": None})
        if ext in TEXT_EXTS:
            g["md"] = f
        else:
            g.setdefault("other", None)
            if g["other"] is None:
                g["other"] = f

    reports: list[ReportMeta] = []
    for stem, g in groups.items():
        md = g.get("md")
        other = g.get("other")
        primary = md or other
        if not primary:
            continue
        primary_name = primary.get("name", "")
        meta = ReportMeta(
            file_id=primary.get("id", ""),
            md_file_id=(md.get("id", "") if md else ""),
            filename=primary_name,
            scope=scope,
            mime=primary.get("mimeType", ""),
        )
        if scope == "sector":
            parsed = parse_sector_filename(primary_name)
            meta.date = parsed["date"]
            meta.broker = parsed["broker"]
            meta.topic = parsed["topic"]
            meta.category = parsed["category"]
        elif scope == "stock" and stock:
            meta.stock_code, meta.stock_name = stock
            parsed = parse_sector_filename(primary_name)  # 個股檔名多同格式，盡量抽日期/主題
            meta.date = parsed["date"]
            meta.broker = parsed["broker"]
            meta.topic = parsed["topic"]
        reports.append(meta)
    return reports


def drive_sync(db_path: str = DEFAULT_DB_PATH) -> dict:
    """列 Drive → 解析 → 重建/更新本地 metadata 索引。回摘要 dict。

    走訪 tw_stocks/<代號-名>/、sector/、Digitimes/，跳過 _SKIP_TOP 與 zip。
    不下載任何內文，只記 metadata + file_id。回 {indexed, stock, sector, ...}。
    """
    try:
        creds = _load_creds()
        service = _build_service(creds)
    except FileNotFoundError as e:
        return {"error": str(e)}
    except ImportError as e:
        return {"error": f"缺 Google 相依套件：{e}"}

    all_reports: list[ReportMeta] = []
    top = _list_children(service, _ROOT_FOLDER_ID)
    top_by_name = {t["name"]: t for t in top}

    # 1) tw_stocks/<代號-名>/ — 每個子資料夾一檔股票。
    #    瓶頸：426 個資料夾各需一次 Drive 列檔往返。改用執行緒池「並行」列檔，
    #    把總時間從「426×往返」壓成約「426÷併發×往返」。
    #    執行緒安全：googleapiclient 的 service（內含單一 http 連線）非執行緒安全，
    #    故每執行緒用 thread-local 各自 _build_service(creds)（共用同一份 OAuth
    #    憑證，但各自的 http 連線）。併發數保守設 16，避免觸發 Drive 讀取速率限制。
    from concurrent.futures import ThreadPoolExecutor
    import threading

    _tls = threading.local()

    def _thread_service():
        svc = getattr(_tls, "svc", None)
        if svc is None:
            svc = _build_service(creds)
            _tls.svc = svc
        return svc

    tw = top_by_name.get("tw_stocks")
    stock_count = 0
    if tw and tw.get("mimeType") == _FOLDER_MIME:
        subfolders = [
            s for s in _list_children(service, tw["id"])
            if s.get("mimeType") == _FOLDER_MIME
        ]

        def _one_stock(sub: dict) -> list[ReportMeta]:
            code, name = parse_stock_folder(sub["name"])
            files = _list_children(_thread_service(), sub["id"])
            return _pair_files_to_reports(files, scope="stock", stock=(code, name))

        with ThreadPoolExecutor(max_workers=16) as pool:
            for reps in pool.map(_one_stock, subfolders):
                all_reports.extend(reps)
                stock_count += len(reps)

    # 2) sector/ 與 Digitimes/ — 扁平檔案，scope=sector（各一次列檔，無需並行）
    sector_count = 0
    for folder_name in ("sector", "Digitimes"):
        node = top_by_name.get(folder_name)
        if node and node.get("mimeType") == _FOLDER_MIME:
            files = _list_children(service, node["id"])
            reps = _pair_files_to_reports(files, scope="sector")
            all_reports.extend(reps)
            sector_count += len(reps)

    indexed = build_index(all_reports, db_path=db_path)
    return {
        "indexed": indexed,
        "stock": stock_count,
        "sector": sector_count,
        "skipped_top": sorted(_SKIP_TOP),
    }


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """用 PyMuPDF 從 PDF bytes 抽純文字（逐頁串接）。無法解析時回空字串。

    PyMuPDF（fitz）已是專案相依（見 requirements.txt 的 PyMuPDF）。掃描型（圖片）
    PDF 抽不到文字會回空——本工具不做 OCR，屬已知限制。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(parts).strip()
    except Exception:  # noqa: BLE001 — 壞檔/加密等一律視為抽不到
        return ""


def drive_fetch_md(file_id: str) -> dict:
    """即時抓單篇報告全文。.md/.txt 直接回純文字；PDF 用 PyMuPDF 抽文字。

    給 CLI --detail 用：agent 先用查詢拿到 file_id（有 md 就用 md_file_id，只有 PDF
    就用 file_id），需要細讀時才呼叫本函式抓全文。回 {file_id, kind, chars, text}
    或 {error}。kind ∈ {'text','pdf'}；掃描型 PDF 抽不到字時 text 為空並附提示。
    """
    file_id = (file_id or "").strip()
    if not file_id:
        return {"error": "請提供 file_id"}
    try:
        from googleapiclient.http import MediaIoBaseDownload
        service = _drive_service()
    except FileNotFoundError as e:
        return {"error": str(e)}
    except ImportError as e:
        return {"error": f"缺 Google 相依套件：{e}"}

    try:
        # 先查 mimeType/name 判斷是純文字還是 PDF（決定要不要用 PyMuPDF 抽）。
        meta = service.files().get(
            fileId=file_id, fields="name, mimeType", supportsAllDrives=True
        ).execute()
        name = meta.get("name", "")
        mime = meta.get("mimeType", "")

        request = service.files().get_media(fileId=file_id)
        buf = _io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        raw = buf.getvalue()

        is_pdf = mime == "application/pdf" or ext_of(name) == "pdf"
        if is_pdf:
            text = _extract_pdf_text(raw)
            if not text:
                return {
                    "file_id": file_id, "kind": "pdf", "chars": 0, "text": "",
                    "note": "此 PDF 抽不到文字（可能為掃描/圖片型），本工具不做 OCR",
                }
            return {"file_id": file_id, "kind": "pdf", "chars": len(text), "text": text}

        text = raw.decode("utf-8", errors="replace")
        return {"file_id": file_id, "kind": "text", "chars": len(text), "text": text}
    except Exception as e:  # noqa: BLE001 — 網路/權限錯誤統一回 error
        return {"error": f"抓取 {file_id} 失敗：{e}"}


# ── 4/CLI. 入口 ─────────────────────────────────────────────────────────────
# 查詢類（--stock/--sector/--stats）只讀本地索引，離線可用。
# --detail/--sync 需 Drive 存取層（見同檔後續實作的 drive_* 函式）；未就緒時
# 回清楚的 error（不讓 CLI 崩），因為 Drive 層與 OAuth 憑證是後續任務。

import json as _json
import sys as _sys


def _reports_json(reports: list[ReportMeta]) -> dict:
    """把 ReportMeta 清單包成給 agent 的精簡 JSON（不含內文）。"""
    return {
        "reports": [
            {
                "file_id": r.file_id,
                "md_file_id": r.md_file_id,
                "date": r.date,
                "broker": r.broker,
                "topic": r.topic or r.stock_name,
                "filename": r.filename,
                "has_fulltext": bool(r.md_file_id),
            }
            for r in reports
        ]
    }


def _main(argv: list[str]) -> int:
    if not argv:
        print(_json.dumps({"error": "用法見檔案開頭 docstring（--stock/--sector/--detail/--sync）"}, ensure_ascii=False))
        return 1

    cmd = argv[0]

    def _opt(flag: str, default: str | None = None) -> str | None:
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    limit = int(_opt("--limit", "10") or 10)

    if cmd == "--stock":
        if len(argv) < 2:
            print(_json.dumps({"error": "用法: --stock <代號> [--limit N]"}, ensure_ascii=False))
            return 1
        result = _reports_json(query_stock(argv[1], limit=limit))
        print(_json.dumps(result, ensure_ascii=False))
        return 0

    if cmd == "--sector":
        if len(argv) < 2:
            print(_json.dumps({"error": "用法: --sector <關鍵字> [--limit N]"}, ensure_ascii=False))
            return 1
        result = _reports_json(query_sector(argv[1], limit=limit))
        print(_json.dumps(result, ensure_ascii=False))
        return 0

    if cmd == "--stats":
        print(_json.dumps(index_stats(), ensure_ascii=False))
        return 0

    if cmd in ("--detail", "--sync"):
        # 需 Drive 存取層（後續任務）。尚未實作時回明確 error，不崩。
        try:
            if cmd == "--detail":
                if len(argv) < 2:
                    print(_json.dumps({"error": "用法: --detail <file_id>"}, ensure_ascii=False))
                    return 1
                result = drive_fetch_md(argv[1])  # noqa: F821 — 由 Drive 層提供
            else:
                result = drive_sync()  # noqa: F821 — 由 Drive 層提供
        except NameError:
            print(_json.dumps(
                {"error": f"{cmd} 需要 Google Drive 存取層與 OAuth 憑證，尚未設定完成"},
                ensure_ascii=False,
            ))
            return 1
        print(_json.dumps(result, ensure_ascii=False))
        return 0 if "error" not in result else 1

    print(_json.dumps({"error": f"未知子命令：{cmd}"}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    _sys.exit(_main(_sys.argv[1:]))
