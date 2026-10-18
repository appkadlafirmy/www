#!/usr/bin/env python3
"""Turn PageSpeed + HTML findings (psi.py output) into polite, concrete problem statements.

usage: score.py PSI_DIR  -> prints a ranking, writes PSI_DIR/_scored.json
Only facts measured by Google or read from the page's HTML are used.
"""
import datetime, glob, json, os, re, sys

YEAR = datetime.date.today().year

def s(v):  # seconds, Polish decimal comma
    return ("%.1f" % (v / 1000)).replace(".", ",")

def problems(r):
    out = []
    if r.get("htmlFinal") and r.get("viewportMeta") is False:
        out.append((4, "strona nie ma wersji na telefon – na komórce wyświetla się pomniejszona wersja z komputera, którą trzeba przybliżać i przesuwać, a większość klientów szuka dziś właśnie z telefonu"))
    lcp = r.get("lcp")
    if lcp and lcp > 4000 and r.get("perf") is not None:
        out.append((3 if lcp > 6000 else 2, "według testu Google PageSpeed na telefonie główna treść strony pojawia się dopiero po ok. %s s (Google za dobry wynik uznaje poniżej 2,5 s), a szybkość strony ocenia na %d/100 – przy takim czasie część osób rezygnuje, zanim zobaczy ofertę" % (s(lcp), round(r["perf"] * 100))))
    fin = r.get("finalUrl") or r.get("htmlFinal") or ""
    if fin.startswith("http://"):
        out.append((3, "strona nie ma certyfikatu SSL (adres zaczyna się od http://), więc przeglądarka pokazuje przy nim ostrzeżenie „Niezabezpieczona”"))
    g = re.match(r"WordPress (\d+)\.(\d+)", r.get("generator") or "")
    if g and int(g.group(1)) < 5:
        out.append((2, "strona działa na bardzo starej wersji WordPressa (%s.%s), która od dawna nie dostaje poprawek bezpieczeństwa" % g.groups()))
    if r.get("frames") or r.get("flash"):
        out.append((2, "strona jest zbudowana w przestarzałej technologii (ramki / Flash), której Google nie lubi i która nie działa dobrze na telefonach"))
    y = r.get("copyYear")
    if y and y <= YEAR - 4:
        out.append((2, "w stopce widnieje rok %d, przez co strona sprawia wrażenie dawno nieaktualizowanej" % y))
    if r.get("htmlFinal") and r.get("telLinks") == 0:
        out.append((2, "numeru telefonu nie da się kliknąć na komórce – klient musi go przepisywać, zamiast zadzwonić jednym dotknięciem"))
    if r.get("metaDesc") == 0:
        out.append((1, "strona nie ma opisu dla Google (meta description), więc w wynikach wyszukiwania pokazuje się przypadkowy fragment tekstu"))
    return sorted(out, key=lambda x: -x[0])

def main():
    d = sys.argv[1]; res = []
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        if os.path.basename(f).startswith("_"): continue
        r = json.load(open(f))
        if r.get("psiError") and not r.get("htmlFinal"):
            continue
        p = problems(r)
        r.update(score=sum(w for w, _ in p), problems=[t for _, t in p])
        res.append(r)
    res.sort(key=lambda x: -x["score"])
    for x in res:
        print("%3d  %-34s %-9s %s" % (x["score"], x["firma"][:34], x["miasto"], " | ".join(t[:34] for t in x["problems"][:4])))
    json.dump(res, open(os.path.join(d, "_scored.json"), "w"), ensure_ascii=False, indent=1)

main()
