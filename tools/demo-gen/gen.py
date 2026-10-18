#!/usr/bin/env python3
"""Generate per-lead demo pages from industry templates.

usage: gen.py LEADS_DIR OUT_DIR [--only EMAIL ...] [--limit N]
LEADS_DIR holds one JSON file per lead (ArtifactData export).
Writes OUT_DIR/<slug>/index.html and OUT_DIR/index.json (email -> slug).
"""
import json, os, re, sys, html, glob, unicodedata, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP = {"unsubscribed", "not_interested", "bounced"}
FAMILIES = {"fach": json.load(open(os.path.join(HERE, "fach.json"), encoding="utf-8"))}
TPL = {f: open(os.path.join(HERE, f + ".html"), encoding="utf-8").read() for f in FAMILIES}
E = html.escape

def slugify(s):
    s = s.replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48].strip("-") or "firma"

def initials(name):
    w = [x for x in re.split(r"[\s\-.,&]+", name) if x and x[0].isalnum()]
    return (w[0][0] + (w[1][0] if len(w) > 1 else "")).upper() if w else "★"

def street(notes, city):
    m = re.search(r"Adres:\s*([^.]+)\.", notes or "")
    if not m: return ""
    s = m.group(1).strip()
    if s.lower().endswith(", " + city.lower()): s = s[: -len(city) - 2].strip()
    return "" if s.lower() == city.lower() else s

def find(branza):
    for fam, d in FAMILIES.items():
        if branza in d: return fam, d[branza]
    return None, None

def render(lead, fam, c, depth="../"):
    firma, city = lead["firma"].strip(), lead["miasto"].strip()
    st = street(lead.get("notes"), city)
    img = [depth + "assets/" + fam + "/" + i + ".jpg" for i in c["img"]]
    gal_src = ((c["img"][1:] + c["img"][:1]) * 4)[:5] if len(c["img"]) >= 4 else (c["img"][1:] + c["img"][:1])
    labels = [s[0] for s in c["services"]]
    rep = {
        "firma": E(firma), "miasto": E(city), "label": E(c["label"]), "acc": c["acc"],
        "ini": E(initials(firma)), "h1": c["h1"], "lead": E(c["lead"]),
        "lead_plain": E(c["lead"]), "email": E(lead["email"]),
        "nazwa_pelna": E((lead.get("nazwaPelna") or firma).strip()),
        "img0": img[0], "img1": img[1] if len(img) > 1 else img[0],
        "adres_line": E(("Bazujemy przy ul. " + st + ". ") if st else ""),
        "adres_full": E((st + ", " if st else "") + city),
        "map_q": urllib.parse.quote((st + ", " if st else "") + city),
        "facts": "".join('<span><svg><use href="#chk"/></svg>%s</span>' % E(f) for f in c["facts"]),
        "ticker": "".join("<span>%s</span>" % E(l) for l in labels),
        "services": "".join(
            '<article class="svc rv" style="--d:%.2fs"><span class="n">%02d</span><span class="go" aria-hidden="true"><svg class="arr"><use href="#arr"/></svg></span><h3>%s</h3><p>%s</p></article>'
            % (i % 3 * .08, i + 1, E(t), E(d)) for i, (t, d) in enumerate(c["services"])),
        "why": "".join('<div class="pt rv" style="--d:%.2fs"><i>%d</i><div><h3>%s</h3><p>%s</p></div></div>' % (i * .06, i + 1, E(t), E(d)) for i, (t, d) in enumerate(c["why"])),
        "q_services": "".join('<button type="button" class="opt" aria-pressed="false" data-v="%s"><span class="r"></span><span><b>%s</b></span></button>' % (E(t), E(t)) for t in labels),
        "q_scope": "".join('<button type="button" class="opt" aria-pressed="false" data-v="%s"><span class="r"></span><span><b>%s</b><small>%s</small></span></button>' % (E(t), E(t), E(d)) for t, d in c["scope"]),
        "gallery": "".join('<figure class="rv" style="--d:%.2fs"><img src="%s" alt="" loading="lazy">%s</figure>' % (i % 4 * .06, depth + "assets/" + fam + "/" + g + ".jpg", '<figcaption>%s</figcaption>' % E(labels[i % len(labels)])) for i, g in enumerate(gal_src)),
        "gal_n": str(len(gal_src)),
        "faq": "".join('<details><summary>%s<i>+</i></summary><p>%s</p></details>' % (E(q), E(a)) for q, a in c["faq"]),
    }
    out = TPL[fam]
    for k, v in rep.items(): out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{\w+\}\}", out)
    if left: raise SystemExit("unfilled placeholders: %s" % sorted(set(left)))
    return out

def main():
    a = sys.argv[1:]
    src, dst = a[0], a[1]
    only = set(a[a.index("--only") + 1:]) if "--only" in a else None
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
    idx_path = os.path.join(dst, "index.json")
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {}
    used = set(idx.values()); n = 0; miss = {}
    for f in sorted(glob.glob(os.path.join(src, "*.json"))):
        lead = json.load(open(f, encoding="utf-8"))
        if only and lead["email"] not in only: continue
        if lead.get("status") in SKIP: continue
        fam, c = find(lead.get("branza", ""))
        if not fam: miss[lead.get("branza")] = miss.get(lead.get("branza"), 0) + 1; continue
        slug = idx.get(lead["email"])
        if not slug:
            base = slugify(lead["firma"] + "-" + lead["miasto"]); slug = base; k = 2
            while slug in used: slug = "%s-%d" % (base, k); k += 1
            used.add(slug); idx[lead["email"]] = slug
        os.makedirs(os.path.join(dst, slug), exist_ok=True)
        open(os.path.join(dst, slug, "index.html"), "w", encoding="utf-8").write(render(lead, fam, c))
        n += 1
        if limit and n >= limit: break
    json.dump(idx, open(idx_path, "w"), ensure_ascii=False, indent=0, sort_keys=True)
    print("generated", n, "| no template yet:", sum(miss.values()), miss)

if __name__ == "__main__":
    main()
