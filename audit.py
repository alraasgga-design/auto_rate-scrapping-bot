"""임시 점검: 각 칸이 페이지의 어느 문구에서 값을 가져왔는지 출력."""
import json, re
from pathlib import Path
import scraper

cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
for bank, b in cfg["banks"].items():
    texts, apis = scraper.fetch_pages(bank, b["pages"], False, b.get("click"))
    print("#" * 20, bank)
    for col, it in b["items"].items():
        if "api" in it:
            print(f"[{col}] {it['name']} = {scraper.extract_api(apis[it['page']], it['api'])}  (API {it['api']['min']})")
            continue
        val = scraper.extract(texts[it["page"]], it["label"])
        where = "?"
        for n, part in enumerate(texts[it["page"]].split(scraper.HIDDEN_MARK)):
            m = re.search(it["label"], part)
            if not m:
                continue
            r = scraper.RATE_RANGE.search(part, m.end()) or scraper.MIN_MAX.search(part, m.end())
            if r:
                ctx = part[max(0, m.start() - 60):r.end() + 10]
                where = ("화면" if n == 0 else "숨김") + " | " + re.sub(r"\s+", " ", ctx)
                break
        print(f"[{col}] {it['name']} = {val}\n      ← {where[:400]}")
    # 금리표 전체도 함께 출력 (대조용)
    for key, t in texts.items():
        vis = t.split(scraper.HIDDEN_MARK)[0].splitlines()
        print(f"  --- {key} 금리 줄")
        for ln in vis:
            if re.search(r"\d\.\d+\s*%", ln):
                print("     ", ln.strip()[:160])
