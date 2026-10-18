#!/usr/bin/env python3
"""Audit candidate websites with Google PageSpeed Insights (mobile) plus a plain HTML read.

usage: PAGESPEED_API_KEY=... psi.py candidates.tsv OUT_DIR
Writes OUT_DIR/<id>.json (findings) and OUT_DIR/<id>.jpg (Google's phone screenshot).
"""
import base64, concurrent.futures as cf, json, os, re, sys, urllib.parse, urllib.request

KEY = os.environ["PAGESPEED_API_KEY"]
API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"

def get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read(2_000_000).decode("utf-8", "replace")

def html_facts(url):
    try:
        final, h = get(url, 30)
    except Exception as e:
        return {"htmlError": str(e)[:120]}
    vp = re.search(r'<meta[^>]+name=["\']viewport["\'][^>]*>', h, re.I)
    gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', h, re.I)
    text = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", h))
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright|\(c\))\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", text, re.I)]
    return {"htmlFinal": final, "viewportMeta": bool(vp and re.search(r"width\s*=\s*device-width", vp.group(0), re.I)),
            "generator": gen.group(1) if gen else "", "copyYear": max(years) if years else None,
            "telLinks": len(re.findall(r'href=["\']tel:', h, re.I)), "frames": bool(re.search(r"<frameset|<frame\s", h, re.I)),
            "flash": bool(re.search(r"\.swf|shockwave", h, re.I)), "htmlTitle": (re.search(r"(?is)<title>(.*?)</title>", h) or [None, ""])[1].strip()[:120]}

def psi(url):
    q = urllib.parse.urlencode([("url", url), ("strategy", "mobile"), ("category", "performance"), ("category", "seo"),
                                ("category", "best-practices"), ("locale", "pl"), ("key", KEY)])
    for _ in range(2):
        try:
            _, body = get(API + "?" + q, 150)
            d = json.loads(body)
            if "lighthouseResult" in d: return d["lighthouseResult"]
        except Exception as e:
            err = str(e)
    return {"error": locals().get("err", "no result")}

def audit(row, out):
    branza, firma, miasto, ulica, email, url, tel = (row + [""] * 7)[:7]
    rid = re.sub(r"[^a-z0-9]+", "_", email.lower())
    path = os.path.join(out, rid + ".json")
    if os.path.exists(path): return json.load(open(path))
    r = {"id": rid, "branza": branza, "firma": firma, "miasto": miasto, "ulica": ulica, "email": email, "url": url, "tel": tel}
    r.update(html_facts(url))
    lr = psi(url)
    if "error" in lr or "audits" not in lr:
        r["psiError"] = str(lr.get("error", lr.get("runtimeError")))[:200]
    else:
        a = lr["audits"]; c = lr["categories"]
        sc = lambda k: (a.get(k) or {}).get("score")
        r.update({"finalUrl": lr.get("finalDisplayedUrl") or lr.get("finalUrl"), "perf": c["performance"]["score"], "seo": c["seo"]["score"],
                  "bp": c["best-practices"]["score"], "lcp": (a.get("largest-contentful-paint") or {}).get("numericValue"),
                  "fcp": (a.get("first-contentful-paint") or {}).get("numericValue"), "https": sc("is-on-https"),
                  "metaDesc": sc("meta-description"), "viewportScore": sc("viewport-insight"), "runtimeError": (lr.get("runtimeError") or {}).get("code")})
        shot = (a.get("final-screenshot") or {}).get("details", {}).get("data", "")
        if shot.startswith("data:image"):
            open(os.path.join(out, rid + ".jpg"), "wb").write(base64.b64decode(shot.split(",", 1)[1]))
    json.dump(r, open(path, "w"), ensure_ascii=False, indent=1)
    return r

def main():
    tsv, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    rows = [l.rstrip("\n").split("\t") for l in open(tsv, encoding="utf-8") if l.strip()]
    with cf.ThreadPoolExecutor(6) as ex:
        for r in ex.map(lambda row: audit(row, out), rows):
            print("%-34s perf=%s lcp=%s vp=%s https=%s %s" % (r["firma"][:34], r.get("perf"), r.get("lcp") and round(r["lcp"] / 1000, 1),
                  r.get("viewportMeta"), r.get("https"), r.get("psiError", "")[:60]), flush=True)

main()
