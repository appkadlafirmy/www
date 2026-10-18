#!/usr/bin/env python3
"""Generate per-lead demo pages from industry templates.

usage: gen.py LEADS_DIR OUT_DIR [--only EMAIL ...] [--limit N]
LEADS_DIR holds one JSON file per lead (ArtifactData export).
Writes OUT_DIR/<slug>/index.html; slugs.json (email -> slug) keeps URLs stable.
"""
import json, os, re, sys, html, glob, hashlib, unicodedata, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP = {"unsubscribed", "not_interested", "bounced"}
# leads that already got a hand-made demo
SKIP_EMAILS = {"vinneri.poland@gmail.com", "ulatowscy@poczta.fm", "martiignatowicz@gmail.com", "agata.faron@vp.pl"}
# family -> template file; each family has <family>.json and images in assets/<family>/
TEMPLATE_OF = {"fach": "fach", "dom": "fach", "auto": "fach", "krawiec": "fach", "foto": "fach", "salon": "salon", "food": "food", "nocleg": "nocleg"}
FAMILIES = {f: json.load(open(os.path.join(HERE, f + ".json"), encoding="utf-8"))
            for f in TEMPLATE_OF if os.path.exists(os.path.join(HERE, f + ".json"))}
TPL = {t: open(os.path.join(HERE, t + ".html"), encoding="utf-8").read() for t in set(TEMPLATE_OF.values())}
CSS = {}

def split_css(name, html_src):
    """Move the template's CSS into a shared file; per-page values stay inline as custom properties."""
    a, b = html_src.index("<style>") + 7, html_src.index("</style>")
    css = html_src[a:b]
    r0 = css.index(":root {"); r1 = css.index("\n  }", r0) + 3
    root, rest = css[r0:r1], css[r1 + 1:]
    keys = sorted(set(re.findall(r"\{\{(\w+)\}\}", rest)))
    for k in keys: rest = rest.replace("{{" + k + "}}", "var(--t-" + k + ")")
    root += "".join(" --t-%s: {{%s}};" % (k, k) for k in keys) + " }"
    CSS[name] = rest.strip() + "\n"
    ver = hashlib.md5(CSS[name].encode()).hexdigest()[:8]
    return html_src[:a] + "\n  " + root + "\n" + html_src[b:].replace("</style>", '</style>\n<link rel="stylesheet" href="../assets/%s.css?v=%s">' % (name, ver), 1)

TPL = {t: split_css(t, s) for t, s in TPL.items()}
# default wording of the service template; a branza can override any key under "txt"
TXT = {
    "t_cta": "Darmowa wycena", "t_cta2": "Wyceń zlecenie", "t_q": "Wycena", "t_gal": "Realizacje",
    "t_slot": "Wybierz dzień oględzin", "t_slot_go": "umów oględziny",
    "t_why": "Robota zrobiona tak, <em>jak dla siebie</em>.",
    "t_steps": "Od wiadomości do <em>gotowej roboty</em>.",
    "steps": [["Wiadomość", "Opisz krótko, co trzeba zrobić. Odpisujemy zwykle tego samego dnia."],
              ["Oględziny", "Przyjeżdżamy, mierzymy i doradzamy najlepsze rozwiązanie."],
              ["Wycena", "Dostajesz konkretną cenę i termin – bez drobnego druku."],
              ["Realizacja", "Robimy swoje, sprzątamy i odbieramy pracę razem z Tobą."]],
    "t_qh": "Wycena w <em>4 krokach</em>.", "t_qsub": "Zaznacz kilka rzeczy, a my odezwiemy się z wyceną. Bez zobowiązań.",
    "qli": ["Odpowiedź zwykle tego samego dnia", "Bezpłatne oględziny na miejscu", "Cena podana przed rozpoczęciem prac"],
    "t_scope": "Jaki to zakres?", "t_galh": "Zobacz, jak <em>pracujemy</em>.",
    "t_galnote": "tu pojawią się Wasze prawdziwe realizacje.", "t_fin": "Masz zlecenie?",
    "t_finp": "Opisz krótko, czego potrzebujesz, a wrócimy z terminem i wyceną.", "t_subj": "Zapytanie o wycenę",
}
E = html.escape

def slugify(s):
    s = s.replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48].strip("-") or "firma"

LEGAL = re.compile(r"\s*(sp\.\s*z\s*o\.\s*o\.|sp\.\s*j\.|s\.c\.|spółka cywilna)\s*$", re.I)
PREFIX = re.compile(r"^((przedsiębiorstwo|produkcyjno|handlowo|usługowo|usługowe|handlowe|produkcyjne|p\.?h\.?u\.?|f\.?h\.?u\.?|z\.?u\.?h\.?)[\s\-]+)+", re.I)

def display_name(name):
    """Short brand name for headings: no legal suffix, no 'PHU' style prefix, no trailing owner after '. '."""
    n = LEGAL.sub("", name.strip())
    n2 = PREFIX.sub("", n).strip(" -")
    if len(n2) >= 3: n = n2[0].upper() + n2[1:]
    first = n.split(". ")[0]
    if ". " in n and len(first) >= 3 and "." not in first: n = first
    return n.strip(" .-") or name.strip()

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
        if branza in d and not branza.startswith("_"): return fam, d[branza]
    return None, None

STYLES = {
    "serif": {"font_q": "family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400", "font": '"Fraunces", Georgia, serif',
              "h_w": "400", "h1_w": "400", "h_ls": "-.015em", "h1_ls": "-.03em", "em_style": "italic"},
    "sans": {"font_q": "family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800", "font": '"Bricolage Grotesque", ui-sans-serif, sans-serif',
             "h_w": "700", "h1_w": "800", "h_ls": "-.02em", "h1_ls": "-.03em", "em_style": "normal"},
}
SALON_TXT = {"t_pl": "Cennik", "t_plh": "Zabiegi i <em>ceny</em>", "t_pl_btn": "Zobacz cennik", "t_cta": "Zarezerwuj wizytę",
             "t_book": "Rezerwacja", "t_bookh": "Zarezerwuj <em>w minutę</em>", "t_what": "Wybrana usługa", "t_send": "Rezerwuję",
             "t_booksub": "Wybierz usługę, dzień i godzinę – potwierdzimy wizytę wiadomością.",
             "bk_li": ["Potwierdzenie zwykle tego samego dnia", "Zmiana terminu bez problemu", "Przypomnienie dzień przed wizytą"],
             "t_about": "O nas", "t_abouth": "Miejsce, do którego <em>chce się wracać</em>.", "t_galh": "Zajrzyj <em>do środka</em>.",
             "t_visith": "Zapraszamy <em>do nas</em>.", "t_subj": "Rezerwacja", "t_fin": "Zarezerwuj <em>chwilę dla siebie</em>.",
             "t_finp": "Wybierz dogodny termin online – potwierdzimy go wiadomością."}
DAYS = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"]

def hours_rows(h):
    rows, i = [], 0
    while i < 7:
        j = i
        while j + 1 < 7 and h[j + 1] == h[i]: j += 1
        lab = DAYS[i] if i == j else DAYS[i] + " – " + DAYS[j]
        val = "%d:00 – %d:00" % tuple(h[i]) if h[i] else "nieczynne"
        ds = ",".join(str(k) for k in range(i, j + 1))
        rows.append('<span data-d="%s">%s</span><span data-d="%s">%s</span>' % (ds, lab, ds, val))
        i = j + 1
    return "".join(rows)

def render_salon(lead, fam, c, depth):
    firma, city = display_name(lead["firma"]), lead["miasto"].strip()
    st = street(lead.get("notes"), city)
    im = lambda k: depth + "assets/" + fam + "/" + k + ".jpg"
    img = c["img"]
    first = c["cats"][0][2][0]
    rep = dict(STYLES[c["style"]])
    rep.update({
        "firma": E(firma), "miasto": E(city), "label": E(c["label"]), "acc": c["acc"], "acc_ink": c["acc_ink"],
        "bg": c["bg"], "bg2": c["bg2"], "line": c["line"], "ini": E(initials(firma)), "h1": c["h1"],
        "lead": E(c["lead"]), "lead_plain": E(c["lead"]), "email": E(lead["email"]), "sticker": E(c["sticker"]),
        "nazwa_pelna": E((lead.get("nazwaPelna") or firma).strip()),
        "img0": im(img[0]), "img1": im(img[1]), "img2": im(c["cats"][0][1]), "img3": im(img[3]), "img4": im(img[4]),
        "adres_meta": E((" · ul. " + st) if st else ""), "adres_full": E((st + ", " if st else "") + city),
        "map_q": urllib.parse.quote((st + ", " if st else "") + city),
        "chips": "".join('<span class="chip"><i></i>%s</span>' % E(x) for x in c["chips"]),
        "ticker": "".join("<span>%s</span>" % E(it[0]) for cat in c["cats"] for it in cat[2][:2]),
        "tabs": "".join('<button class="tab" role="tab" aria-selected="%s" data-img="%s">%s</button>' % ("true" if i == 0 else "false", im(cat[1]), E(cat[0])) for i, cat in enumerate(c["cats"])),
        "panels": "".join('<div class="panel%s" role="tabpanel">%s</div>' % (" on" if i == 0 else "", "".join(
            '<div class="row-i"><h3>%s</h3><span class="pr">%s zł</span><p>%s</p><span class="du">%s</span><button class="pick" type="button" aria-label="Wybierz: %s" data-n="%s" data-m="%s · %s zł"><svg class="arr"><use href="#plus"/></svg></button></div>'
            % (E(n), (("od " if c.get("from") else "") + str(p)), E(cat[0]), E(dur), E(n), E(n), E(dur), p) for n, dur, p in cat[2])) for i, cat in enumerate(c["cats"])),
        "first_name": E(first[0]), "first_meta": E("%s · %s zł" % (first[1], first[2])),
        "about": E(c["about"]),
        "why": "".join('<div class="pt rv" style="--d:%.2fs"><i>%d</i><div><h3>%s</h3><p>%s</p></div></div>' % (i * .08, i + 1, E(t), E(x)) for i, (t, x) in enumerate(c["why"])),
        "gallery": "".join('<figure class="rv" style="--d:%.2fs"><img src="%s" alt="" loading="lazy"></figure>' % (i % 3 * .08, im(k)) for i, k in enumerate(dict.fromkeys(img[1:] + img[:1]))),
        "faq": "".join('<details><summary>%s<i>+</i></summary><p>%s</p></details>' % (E(q), E(a)) for q, a in c["faq"]),
        "hours": hours_rows(c["hours"]), "hours_js": json.dumps(c["hours"]), "slot_min": str(c.get("slot", 60)),
    })
    t = dict(SALON_TXT); t.update(c.get("txt", {}))
    rep["bk_li"] = "".join('<li><svg><use href="#chk"/></svg>%s</li>' % E(x) for x in t.pop("bk_li"))
    rep.update(t)
    return fill("salon", rep)

FOOD_TXT = {"t_cta": "Zamów online", "t_menu": "Menu", "t_menuh": "Menu", "t_sp": "Na zamówienie", "t_order": "Twoje zamówienie",
            "t_menusub": "Dodaj produkty przyciskiem +, wybierz godzinę i wyślij zamówienie – potwierdzimy je odpowiedzią.",
            "t_why": "Dlaczego <em>my</em>", "t_galh": "Galeria", "t_visith": "Zapraszamy <em>do nas</em>.",
            "t_fin": "Zamów online", "t_finp": "", "modes": ["Odbiór osobisty", "Dostawa"]}

def fmt_price(p):
    return ("%.2f" % p).replace(".", ",").replace(",00", "") + " zł"

def base_rep(lead, fam, c):
    firma, city = display_name(lead["firma"]), lead["miasto"].strip()
    st = street(lead.get("notes"), city)
    rep = dict(STYLES[c["style"]])
    rep.update({
        "firma": E(firma), "miasto": E(city), "label": E(c["label"]), "ini": E(initials(firma)), "h1": c["h1"],
        "lead": E(c["lead"]), "lead_plain": E(c["lead"]), "email": E(lead["email"]),
        "nazwa_pelna": E((lead.get("nazwaPelna") or firma).strip()),
        "adres_full": E((st + ", " if st else "") + city), "adres_meta": E((" · ul. " + st) if st else ""),
        "map_q": urllib.parse.quote((st + ", " if st else "") + city),
        "faq": "".join('<details><summary>%s<i>+</i></summary><p>%s</p></details>' % (E(q), E(a)) for q, a in c["faq"]),
    })
    for k in ("acc", "acc_ink", "bg", "bg2", "line", "ink"):
        if k in c: rep[k] = c[k]
    if "hours" in c: rep["hours"] = hours_rows(c["hours"]); rep["hours_js"] = json.dumps(c["hours"])
    return rep

# page variant: hero "A" (template default) or "B" (alternative), light or dark theme
VARIANT = {"hero": "A", "dark": False}

def apply_variant(out):
    drop = "B" if VARIANT["hero"] == "A" else "A"
    out = re.sub(r"<!--HERO:%s-->.*?<!--/HERO:%s-->\n?" % (drop, drop), "", out, flags=re.S)
    out = re.sub(r"<!--/?HERO:[AB]-->\n?", "", out)
    return out

CUR_LEAD = {}

def phone_bits(lead):
    """Call button and contact lines when the lead has a phone number (leads found with a website)."""
    tel = (lead.get("tel") or "").strip(); e = E(lead["email"])
    if not tel:
        return {"mbar_l": '<a class="btn b-line" href="mailto:%s">Napisz</a>' % e, "tel_p": "", "tel_ic": ""}
    num = re.sub(r"[^0-9+]", "", tel); num = num if num.startswith("+") else "+48" + num.lstrip("0")
    return {"mbar_l": '<a class="btn b-line" href="tel:%s">Zadzwoń</a>' % num,
            "tel_p": '<p><a href="tel:%s">%s</a></p>' % (num, E(tel)),
            "tel_ic": '<div class="ic"><small>Telefon</small><a class="v" href="tel:%s">%s</a></div>' % (num, E(tel))}

def fill(tpl, rep):
    rep = dict(rep); rep.update(phone_bits(CUR_LEAD))
    rep["body_cls"] = " ".join(filter(None, ["hb" if VARIANT["hero"] == "B" else "ha", "hs" if (tpl == "fach") == (VARIANT["hero"] == "B") else "hf", "dk" if VARIANT["dark"] else ""]))
    out = apply_variant(TPL[tpl])
    for k, v in rep.items(): out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{\w+\}\}", out)
    if left: raise SystemExit("unfilled placeholders: %s" % sorted(set(left)))
    return out

def render_food(lead, fam, c, depth):
    im = lambda k: depth + "assets/" + fam + "/" + k + ".jpg"
    img = c["img"]; rep = base_rep(lead, fam, c)
    pre = "od " if c.get("from") else ""
    rep.update({
        "img0": im(img[0]), "img1": im(img[1]), "img2": im(img[2]), "img3": im(img[3]), "badge": E(c["badge"]),
        "chips": "".join('<span><svg><use href="#chk"/></svg>%s</span>' % E(x) for x in c["chips"]),
        "ticker": "".join("<span>%s</span>" % E(it[0]) for cat in c["menu"] for it in cat[1][:2]),
        "tabs": "".join('<button class="tab" role="tab" aria-selected="%s">%s</button>' % ("true" if i == 0 else "false", E(cat[0])) for i, cat in enumerate(c["menu"])),
        "panels": "".join('<div class="panel%s" role="tabpanel">%s</div>' % (" on" if i == 0 else "", "".join(
            '<div class="item" data-n="%s" data-p="%s"><h3>%s</h3><span class="pr">%s%s</span><p>%s</p><span class="qty"><button class="sub2" type="button" aria-label="Usuń jedną: %s">−</button><b>0</b><button class="add" type="button" aria-label="Dodaj: %s">+</button></span></div>'
            % (E(n), p, E(n), pre, fmt_price(p), E(ds), E(n), E(n)) for n, ds, p in cat[1])) for i, cat in enumerate(c["menu"])),
        "sp_h": c["sp"]["t"], "sp_d": E(c["sp"]["d"]), "sp_btn": E(c["sp"]["btn"]), "sp_subj": urllib.parse.quote(c["sp"]["subj"]),
        "sp_li": "".join('<li><svg><use href="#chk"/></svg>%s</li>' % E(x) for x in c["sp"]["li"]),
        "why": "".join('<div class="w rv" style="--d:%.2fs"><i>0%d</i><h3>%s</h3><p>%s</p></div>' % (i * .08, i + 1, E(t), E(x)) for i, (t, x) in enumerate(c["why"])),
        "gallery": "".join('<figure class="rv" style="--d:%.2fs"><img src="%s" alt="" loading="lazy"></figure>' % (i % 4 * .08, im(k)) for i, k in enumerate(img[1:] + img[:1])),
        "step_h": str(c.get("step_h", 1)),
    })
    t = dict(FOOD_TXT); t.update(c.get("txt", {}))
    modes = t.pop("modes")
    rep["modes"] = "".join('<button type="button" aria-pressed="%s" data-v="%s">%s</button>' % ("true" if i == 0 else "false", E(m), E(m)) for i, m in enumerate(modes))
    rep["mode0"] = E(modes[0])
    rep.update(t)
    return fill("food", rep)

NOCLEG_TXT = {"t_pl": "Pokoje", "t_plh": "Wybierz <em>pokój</em>", "t_pl_btn": "Zobacz pokoje", "t_cta": "Sprawdź termin",
              "t_book": "Rezerwacja", "t_bookh": "Sprawdź <em>wolne terminy</em>", "t_what": "Wybrany pokój", "t_send": "Zapytaj o pobyt",
              "t_booksub": "Zaznacz daty przyjazdu i wyjazdu – odpiszemy z potwierdzeniem dostępności.",
              "bk_li": ["Rezerwacja bez prowizji serwisów", "Odpowiedź zwykle tego samego dnia", "Elastyczne godziny zameldowania"],
              "t_about": "O nas", "t_abouth": "Miejsce, w którym <em>odpoczniesz</em>.", "t_galh": "Zajrzyj <em>do środka</em>.",
              "t_visith": "Jak do nas <em>trafić</em>.", "t_subj": "Zapytanie o pobyt", "t_fin": "Zaplanuj <em>swój pobyt</em>.",
              "t_finp": "Sprawdź wolne terminy i zapytaj o pobyt – odpiszemy z potwierdzeniem."}

def render_nocleg(lead, fam, c, depth):
    im = lambda k: depth + "assets/" + fam + "/" + k + ".jpg"
    img = c["img"]; rep = base_rep(lead, fam, c)
    r0 = c["rooms"][0]
    rep.update({
        "img0": im(img[0]), "img1": im(img[1]), "img3": im(img[3]), "img4": im(img[4]), "sticker": E(c["sticker"]),
        "chips": "".join('<span class="chip"><i></i>%s</span>' % E(x) for x in c["chips"]),
        "ticker": "".join("<span>%s</span>" % E(x) for x in [r[0] for r in c["rooms"]] + c["chips"]),
        "rooms": "".join(
            '<article class="room rv" style="--d:%.2fs"><div class="ph"><img src="%s" alt="" loading="lazy"></div><div class="bd2"><h3>%s</h3><p class="sub" style="margin:0;font-size:14.5px">do %d os.</p><div class="ft">%s</div><div class="rb"><span><b>%d zł</b> <small>/ noc</small></span><button class="btn b-acc" type="button" data-n="%s" data-m="do %d os. · %d zł / noc" data-p="%d" data-g="%d">Wybierz</button></div></div></article>'
            % (i * .08, im(ph), E(n), g, "".join("<span>%s</span>" % E(f) for f in ft), p, E(n), g, p, p, g) for i, (n, ph, g, p, ft) in enumerate(c["rooms"])),
        "first_name": E(r0[0]), "first_meta": E("do %d os. · %d zł / noc" % (r0[2], r0[3])), "first_price": str(r0[3]), "first_max": str(r0[2]),
        "about": E(c["about"]), "checkin": c["checkin"], "checkout": c["checkout"],
        "why": "".join('<div class="pt rv" style="--d:%.2fs"><i>%d</i><div><h3>%s</h3><p>%s</p></div></div>' % (i * .08, i + 1, E(t), E(x)) for i, (t, x) in enumerate(c["why"])),
        "gallery": "".join('<figure class="rv" style="--d:%.2fs"><img src="%s" alt="" loading="lazy"></figure>' % (i % 3 * .08, im(k)) for i, k in enumerate(dict.fromkeys(img[1:] + img[:1]))),
    })
    t = dict(NOCLEG_TXT); t.update(c.get("txt", {}))
    rep["bk_li"] = "".join('<li><svg><use href="#chk"/></svg>%s</li>' % E(x) for x in t.pop("bk_li"))
    rep.update(t)
    return fill("nocleg", rep)

def render(lead, fam, c, depth="../"):
    if TEMPLATE_OF[fam] == "nocleg": return render_nocleg(lead, fam, c, depth)
    if TEMPLATE_OF[fam] == "salon": return render_salon(lead, fam, c, depth)
    if TEMPLATE_OF[fam] == "food": return render_food(lead, fam, c, depth)
    firma, city = display_name(lead["firma"]), lead["miasto"].strip()
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
    t = dict(TXT); t.update(FAMILIES[fam].get("_txt", {})); t.update(c.get("txt", {}))
    for i, (a, b) in enumerate(t.pop("steps")): rep["s%dt" % (i + 1)] = E(a); rep["s%dd" % (i + 1)] = E(b)
    rep["t_qli"] = "".join('<li><svg><use href="#chk"/></svg>%s</li>' % E(x) for x in t.pop("qli"))
    rep.update(t)
    return fill(TEMPLATE_OF[fam], rep)

def main():
    a = sys.argv[1:]
    src, dst = a[0], a[1]
    only = set(x for x in a[a.index("--only") + 1:] if "@" in x) if "--only" in a else None
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
    force = int(a[a.index("--variant") + 1]) if "--variant" in a else None  # QA: render every page as one variant
    idx_path = os.path.join(HERE, "slugs.json")  # keeps each lead on the same URL between runs
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {}
    used = set(idx.values()); n = 0; miss = {}
    var_path = os.path.join(HERE, "variants.json")  # email -> 0..3, kept between runs
    variants = json.load(open(var_path)) if os.path.exists(var_path) else {}
    cnt = {}
    for f in sorted(glob.glob(os.path.join(src, "*.json"))):
        lead = json.load(open(f, encoding="utf-8"))
        if only and lead["email"] not in only: continue
        if lead.get("status") in SKIP or lead["email"] in SKIP_EMAILS: continue
        fam, c = find(lead.get("branza", ""))
        if not fam: miss[lead.get("branza")] = miss.get(lead.get("branza"), 0) + 1; continue
        slug = idx.get(lead["email"])
        if not slug:
            base = slugify(lead["firma"] + "-" + lead["miasto"]); slug = base; k = 2
            while slug in used: slug = "%s-%d" % (base, k); k += 1
            used.add(slug); idx[lead["email"]] = slug
        v = variants.get(lead["email"])
        if v is None:  # balance the 4 combinations inside each industry
            b = lead.get("branza", ""); v = cnt.get(b, 0) % 4; cnt[b] = cnt.get(b, 0) + 1
            variants[lead["email"]] = v
        if force is not None: v = force
        VARIANT["hero"] = "A" if v in (0, 3) else "B"; VARIANT["dark"] = v in (1, 3)
        CUR_LEAD.clear(); CUR_LEAD.update(lead)
        os.makedirs(os.path.join(dst, slug), exist_ok=True)
        open(os.path.join(dst, slug, "index.html"), "w", encoding="utf-8").write(render(lead, fam, c))
        n += 1
        if limit and n >= limit: break
    os.makedirs(os.path.join(dst, "assets"), exist_ok=True)
    for t, css in CSS.items(): open(os.path.join(dst, "assets", t + ".css"), "w", encoding="utf-8").write(css)
    json.dump(variants, open(var_path, "w"), indent=0, sort_keys=True)
    json.dump(idx, open(idx_path, "w"), ensure_ascii=False, indent=0, sort_keys=True)
    # public email -> folder map, read by the follow-up automation for {{demo}}
    live = {e: s for e, s in idx.items() if os.path.isdir(os.path.join(dst, s))}
    json.dump(live, open(os.path.join(dst, "slugs.json"), "w"), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print("generated", n, "| no template yet:", sum(miss.values()), miss)

if __name__ == "__main__":
    main()
