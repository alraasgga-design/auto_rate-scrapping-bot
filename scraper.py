"""카카오뱅크·케이뱅크·토스뱅크 대출 금리를 읽어 기자님 전용 구글 시트(은행별 탭, 하루 한 줄)에 쌓는다.

사용법
  python scraper.py --discover     # 각 페이지 본문 텍스트와 JSON 응답을 debug/에 저장 (라벨·API 찾기용)
  python scraper.py --dry-run      # 수집만 하고 시트에는 쓰지 않음
  python scraper.py                # 오늘(KST) 날짜로 한 줄 추가. 이미 오늘 줄이 있으면 건너뜀
  python scraper.py --force        # 오늘 줄이 있어도 새 값으로 덮어씀
"""
import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote_plus

import gspread

from playwright.sync_api import sync_playwright

KST = dt.timezone(dt.timedelta(hours=9))
# "4.18~6.04%", "연 4.80 ~ 13.16%", "최저 연 5.44% ~ 최고 연 15.00%" 모두 인식
RATE_RANGE = re.compile(r"(\d{1,2}\.\d{1,3})\s*%?\s*[~∼～]\s*(?:최고\s*)?(?:연\s*)?(\d{1,2}\.\d{1,3})\s*%")
DEBUG_DIR = Path("debug")


HIDDEN_MARK = "\n<<<HIDDEN>>>\n"


def click_tab(page, label: str) -> str | None:
    """'금리정보' 같은 탭·아코디언을 눌러 펼친다. 실패하면 오류 문구를 돌려준다."""
    last = "해당 글자를 찾지 못함"
    for loc in (page.get_by_role("tab", name=label, exact=True), page.get_by_role("button", name=label, exact=True),
                page.get_by_role("link", name=label, exact=True), page.get_by_text(label, exact=True),
                page.get_by_text(label)):
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                el.scroll_into_view_if_needed(timeout=3_000)
                el.click(timeout=3_000)
                page.wait_for_timeout(2_000)
                return None
            except Exception as e:
                last = str(e).splitlines()[0]
    # 마지막 수단: 자바스크립트로 직접 클릭
    ok = page.evaluate("""(label) => {
        const el = [...document.querySelectorAll('a,button,li,span,div,h2,h3,h4,strong')]
            .find(e => e.textContent.trim() === label);
        if (!el) return false; el.click(); return true; }""", label)
    if ok:
        page.wait_for_timeout(2_000)
        return None
    return last


def fetch_pages(bank: str, pages: dict, discover: bool, clicks: dict | None = None) -> dict:
    """URL별로 렌더링된 본문 텍스트를 돌려준다. clicks에 적힌 탭(예: '금리정보')은 눌러서 펼친다.
    discover면 XHR JSON도 저장한다."""
    texts, apis = {}, {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul")
        for key, url in pages.items():
            page = ctx.new_page()
            captured = []
            page.on("response", lambda r, c=captured: c.append(r) if "json" in r.headers.get("content-type", "") else None)
            # 은행 페이지가 광고·통계 요청을 계속 보내 networkidle에 영영 도달하지 못하는 날이 있어
            # (2026-10-21 케이뱅크 아담대) 기본 로딩만 기다리고, 실패하면 한 번 더 연다
            err = None
            for _ in range(2):
                try:
                    page.goto(url, wait_until="load", timeout=60_000)
                    err = None
                    break
                except Exception as e:
                    err = str(e).splitlines()[0]
            if err:
                print(f"[{bank}] {key} 페이지 열기 실패: {url}\n  {err}")
                texts[key], apis[key] = "", []
                page.close()
                continue
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:
                pass
            # 금리 문구가 나타날 때까지 대기 (SPA 대응)
            try:
                page.wait_for_function("() => /\\d\\.\\d+\\s*%/.test(document.body.innerText)", timeout=15_000)
            except Exception:
                pass
            popups = []
            page.on("popup", lambda pg: popups.append(pg))
            for label in (clicks or {}).get(key, []):
                err = click_tab(page, label)
                if err:
                    print(f"[{bank}] {key} '{label}' 탭을 누르지 못함: {err}")
            visible = page.inner_text("body")
            for pg in popups:
                try:
                    pg.wait_for_load_state("networkidle", timeout=15_000)
                    visible += "\n" + pg.inner_text("body")
                except Exception:
                    pass
            # 접힌 탭·아코디언 안의 글자까지 포함한 전체 텍스트 (화면에 안 보여도 HTML에 있으면 잡힘)
            hidden = page.evaluate("() => document.body.textContent")
            texts[key] = visible + HIDDEN_MARK + hidden
            apis[key] = []
            for r in captured:
                try:
                    apis[key].append((r.url, r.json()))
                except Exception:
                    pass
            if discover:
                DEBUG_DIR.mkdir(exist_ok=True)
                (DEBUG_DIR / f"{bank}_{key}.txt").write_text(visible, encoding="utf-8")
                (DEBUG_DIR / f"{bank}_{key}_all.txt").write_text(hidden, encoding="utf-8")
                (DEBUG_DIR / f"{bank}_{key}.html").write_text(page.content(), encoding="utf-8")
                for i, (u, body) in enumerate(apis[key]):
                    (DEBUG_DIR / f"{bank}_{key}_api{i}.json").write_text(
                        json.dumps({"url": u, "body": body}, ensure_ascii=False, indent=1), encoding="utf-8")
            page.close()
        browser.close()
    return texts, apis


def json_get(obj, path: str):
    """'a.b[pdNm=신용대출].c' 형태 경로로 JSON 값을 꺼낸다. 값은 URL 인코딩이 풀린 문자열로 비교한다."""
    for part in path.split("."):
        m = re.fullmatch(r"(\w+)\[(\w+)=(.+)\]", part)
        if m:
            key, fk, fv = m.groups()
            obj = next((x for x in obj.get(key, []) if unquote_plus(str(x.get(fk, ""))) == fv), None)
        else:
            obj = obj.get(part) if isinstance(obj, dict) else None
        if obj is None:
            return None
    return obj


def extract_api(apis: list, spec: dict) -> str | None:
    """은행 내부 API 응답(JSON)에서 최저·최고 금리를 꺼낸다. spec: {url, min, max}"""
    for url, body in apis:
        if spec["url"] not in url:
            continue
        root = body.get("_msg_", {}).get("_body_", body)
        lo, hi = json_get(root, spec["min"]), json_get(root, spec["max"])
        if lo and hi:
            return f"{lo}~{hi}"
    return None


def extract(text: str, label: str) -> str | None:
    """라벨 뒤에 처음 나오는 금리 구간을 '최저~최고' 형태로 반환.
    화면에 보이는 글자에서 먼저 찾고, 없으면 접힌 영역까지 포함한 전체 글자에서 찾는다."""
    for part in text.split(HIDDEN_MARK):
        m = re.search(label, part)
        if not m:
            continue
        r = RATE_RANGE.search(part, m.end())
        if r:
            return f"{r.group(1)}~{r.group(2)}"
    return None


def write_row(sh, tab: str, names: list, values: list, today: dt.date, force: bool) -> str:
    """은행별 탭에 '날짜 | 상품1 | 상품2 ...' 한 줄을 추가한다. 탭·헤더가 없으면 만든다."""
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=1000, cols=len(names) + 1)
    header = ["날짜"] + names
    if ws.row_values(1) != header:
        ws.update(range_name="A1", values=[header])
    row = [today.isoformat()] + [v or "" for v in values]
    dates = ws.col_values(1)
    if row[0] in dates:
        r = dates.index(row[0]) + 1
        if force:
            ws.update(range_name=f"A{r}", values=[row])
            return "오늘 줄을 덮어씀"
        # 앞선 실행에서 빈칸으로 남은 칸만 새 값으로 채운다 (예비 실행이 누락분을 메움)
        old = ws.row_values(r) + [""] * len(row)
        merged = [o if o else n for o, n in zip(old, row)]
        if merged == old[:len(row)]:
            return "오늘 줄이 이미 있어 건너뜀"
        ws.update(range_name=f"A{r}", values=[merged])
        return "오늘 줄의 빈칸을 채움"
    ws.append_row(row, value_input_option="RAW")
    return "새 줄 추가"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))
    today = dt.datetime.now(KST).date()

    results = {}
    for bank, b in cfg["banks"].items():
        texts, apis = fetch_pages(bank, b["pages"], args.discover, b.get("click"))
        results[bank] = {
            col: extract_api(apis[it["page"]], it["api"]) if "api" in it else extract(texts[it["page"]], it["label"])
            for col, it in b["items"].items()
        }
        print(bank, results[bank])

    if args.discover or args.dry_run:
        return

    # GitHub Actions는 키 내용(GOOGLE_SERVICE_ACCOUNT_JSON), 내 PC는 키 파일 경로(GOOGLE_SERVICE_ACCOUNT_FILE)를 쓴다
    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        gc = gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]))
    else:
        gc = gspread.service_account(filename=os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"))
    sh = gc.open_by_key(cfg["spreadsheet_id"])
    for bank, values in results.items():
        items = cfg["banks"][bank]["items"]
        missing = [it["name"] for col, it in items.items() if values[col] is None]
        if missing:
            print(f"[{bank}] 금리를 찾지 못한 상품: {', '.join(missing)}")
        msg = write_row(sh, cfg["banks"][bank]["tab"], [it["name"] for it in items.values()],
                        [values[col] for col in items], today, args.force)
        print(f"[{bank}] {msg}")

if __name__ == "__main__":
    main()
