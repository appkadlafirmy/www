#!/usr/bin/env python3
"""Turn audit JSON into concrete, polite problem statements and a score.

usage: score.py AUDIT_DIR  -> prints a table, writes AUDIT_DIR/_scored.json
"""
import json, glob, os, sys, datetime

YEAR = datetime.date.today().year

def problems(r):
    out = []  # (weight, text)
    if not r.get("viewport") or r.get("scrollW", 0) > 420:
        out.append((4, "na telefonie strona się nie mieści na ekranie – trzeba ją przybliżać i przesuwać na boki, a większość klientów szuka dziś z komórki"))
    elif r.get("smallPct", 0) >= 35 and r.get("textCount", 0) > 15:
        out.append((3, "na telefonie spora część tekstu jest bardzo mała (poniżej 12 px), więc trudno go przeczytać bez przybliżania"))
    if not r.get("https"):
        out.append((3, "strona nie ma certyfikatu SSL, więc przeglądarka pokazuje przy adresie ostrzeżenie „Niezabezpieczona” – to odstrasza część osób"))
    y = r.get("copyYear")
    if y and y <= YEAR - 4:
        out.append((2, "w stopce widnieje rok %d, przez co strona sprawia wrażenie dawno nieaktualizowanej" % y))
    if r.get("telLinks", 0) == 0:
        out.append((2, "numeru telefonu nie da się kliknąć na komórce – klient musi go przepisywać, zamiast zadzwonić jednym dotknięciem"))
    if not (r.get("metaDesc") or "").strip():
        out.append((1, "strona nie ma opisu dla Google (meta description), więc w wynikach wyszukiwania wyświetla się przypadkowy fragment tekstu"))
    if r.get("flash") or r.get("frames") or r.get("tables", 0) > 2:
        out.append((2, "strona jest zbudowana w starej technologii (ramki / tabele), której Google nie lubi i która źle działa na telefonach"))
    if r.get("brokenImgs", 0) >= 2:
        out.append((1, "część zdjęć na stronie się nie wyświetla"))
    return sorted(out, key=lambda x: -x[0])

def main():
    d = sys.argv[1]; res = []
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        if os.path.basename(f).startswith("_"): continue
        r = json.load(open(f))
        if not r.get("ok") or r.get("status", 0) >= 400:
            res.append({**r, "score": -1, "problems": []}); continue
        p = problems(r)
        res.append({**{k: r[k] for k in ("branza", "firma", "miasto", "ulica", "email", "url", "tel")}, "finalUrl": r.get("finalUrl"),
                    "score": sum(w for w, _ in p), "problems": [t for _, t in p], "title": r.get("title", ""), "id": os.path.basename(f)[:-5]})
    res.sort(key=lambda x: -x["score"])
    for x in res: print("%3d  %-38s %-10s %s" % (x["score"], x["firma"][:38], x["miasto"], " | ".join(t[:40] for t in x["problems"][:4]) or x.get("error", "")[:60]))
    json.dump(res, open(os.path.join(d, "_scored.json"), "w"), ensure_ascii=False, indent=1)

main()
