/* Spa Home – treści strony edytowane w panelu (wersja demo: zapis w przeglądarce). */
(function () {
  var KEY = "spahome-cms", INBOX = "spahome-inbox";
  var defaults = {
    v: 1,
    treatments: [
      { id: "t1", name: "Masaż relaksacyjny", nameEn: "Relaxing massage", desc: "Powolne, płynne ruchy z ciepłym olejkiem. Rozluźnia napięcia i wycisza głowę.", descEn: "Slow, flowing movements with warm oil. Relieves tension and calms the mind.", p60: 180, p90: 250, img: "img/plecy.jpg" },
      { id: "t2", name: "Masaż gorącymi kamieniami", nameEn: "Hot stone massage", desc: "Ciepłe kamienie bazaltowe głęboko rozgrzewają i rozluźniają mięśnie. Idealny na chłodne, męczące dni.", descEn: "Warm basalt stones deeply relax the muscles. Perfect for cold, tiring days.", p60: 220, p90: 290, img: "img/kamienie.jpg" },
      { id: "t3", name: "Masaż aromaterapeutyczny", nameEn: "Aromatherapy massage", desc: "Mieszanka olejków eterycznych dobrana do Ciebie – relaksująca, pobudzająca albo kojąca.", descEn: "A blend of essential oils chosen for you – relaxing, energising or soothing.", p60: 200, p90: 270, img: "img/aromaterapia.jpg" },
      { id: "t4", name: "Masaż twarzy i głowy", nameEn: "Face & head massage", desc: "Delikatna praca na twarzy, skórze głowy i karku. Odpręża i daje skórze zdrowy blask.", descEn: "Gentle work on the face, scalp and neck. Relieves tension and leaves the skin glowing.", p60: 150, p90: 210, img: "img/twarz.jpg" },
      { id: "t5", name: "Refleksologia stóp", nameEn: "Foot reflexology", desc: "Masaż stóp i łydek. Przynosi lekkość i ulgę, świetny po całym dniu na nogach.", descEn: "Massage of the feet and calves. Light, pleasant and great after a long day standing.", p60: 140, p90: 190, img: "img/stopy.jpg" }
    ],
    phone: "796 324 242",
    email: "vinneri.poland@gmail.com",
    hours: [{ d: "Poniedziałek – Niedziela", dEn: "Monday – Sunday", h: "10:00 – 24:00" }],
    hoursNote: "Czynne codziennie, także wieczorem",
    hoursNoteEn: "Open every day, also in the evening",
    promo: { on: false, text: "", textEn: "", until: "" },
    gallery: [
      { src: "img/twarz.jpg", alt: "Masaż twarzy" },
      { src: "img/kamienie.jpg", alt: "Masaż gorącymi kamieniami" },
      { src: "img/olejki.jpg", alt: "Olejki z lawendą" },
      { src: "img/stopy.jpg", alt: "Refleksologia stóp" },
      { src: "img/aromaterapia.jpg", alt: "Aromaterapia" },
      { src: "img/rytual.jpg", alt: "Gabinet masażu" }
    ],
    texts: {
      heroLead: "Masaże relaksacyjne i regenerujące w spokojnym, kameralnym wnętrzu przy pl. Piastowskim. Wyłącz telefon, weź głęboki oddech – resztą zajmiemy się my.",
      heroLeadEn: "Relaxing and therapeutic massages in a calm, intimate space at pl. Piastowski. Switch off your phone, take a deep breath – we take care of the rest.",
      aboutLead: "Spa Home to kameralny salon masażu w sercu Bydgoszczy. Każdą wizytę układamy pod Ciebie: zaczynamy od krótkiej rozmowy, dobieramy olejki i siłę masażu, a potem dajemy Ci tyle czasu, ile potrzebujesz.",
      aboutLeadEn: "Spa Home is an intimate massage studio in the heart of Bydgoszcz. Every visit is planned just for you: we start with a short conversation, choose the oils and pressure, and give you as much time as you need."
    }
  };

  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function read(k) { try { var s = localStorage.getItem(k); return s ? JSON.parse(s) : null; } catch (e) { return null; } }
  function write(k, v) { localStorage.setItem(k, JSON.stringify(v)); }
  function load() {
    var d = read(KEY);
    if (!d || d.v !== 1) return clone(defaults);
    var out = clone(defaults);
    for (var k in d) out[k] = d[k];
    out.texts = Object.assign(clone(defaults.texts), d.texts || {});
    out.promo = Object.assign(clone(defaults.promo), d.promo || {});
    return out;
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function promoActive(p) {
    if (!p || !p.on || !p.text) return false;
    if (!p.until) return true;
    var t = new Date(); t.setHours(0, 0, 0, 0);
    return new Date(p.until + "T23:59:59") >= t;
  }

  window.SpaCMS = {
    defaults: defaults, load: load, esc: esc, promoActive: promoActive,
    save: function (d) { write(KEY, d); },
    reset: function () { try { localStorage.removeItem(KEY); localStorage.removeItem(INBOX); } catch (e) {} },
    inbox: function () { return read(INBOX) || []; },
    saveInbox: function (l) { write(INBOX, l); }
  };

  /* ---------- apply to the public page ---------- */
  var list = document.getElementById("tList");
  if (!list) return;
  var d = load();

  // treatments
  list.innerHTML = d.treatments.map(function (t, i) {
    return '<li class="rv" style="--d:' + (i * .05).toFixed(2) + 's"><button class="t-item' + (i === 0 ? " on" : "") + '" type="button" data-img="' + i + '" data-p60="' + esc(t.p60) + '" data-p90="' + esc(t.p90) + '">' +
      '<h3 data-en="' + esc(t.nameEn || t.name) + '">' + esc(t.name) + '</h3><span class="t-price"><span class="price-flip">' + esc(t.p60) + '</span> zł</span>' +
      '<p data-en="' + esc(t.descEn || t.desc) + '">' + esc(t.desc) + '</p>' +
      '<span class="t-mimg"><img src="' + esc(t.img) + '" alt="" loading="lazy"></span></button></li>';
  }).join("");
  var photo = document.getElementById("tPhoto");
  photo.innerHTML = d.treatments.map(function (t, i) { return '<img' + (i === 0 ? ' class="on"' : "") + ' src="' + esc(t.img) + '" alt=""' + (i ? ' loading="lazy"' : "") + '>'; }).join("") +
    '<p class="cap" id="tCap">' + esc(d.treatments[0] ? d.treatments[0].name : "") + '</p>';
  var sel = document.getElementById("fTreat");
  if (sel) sel.innerHTML = d.treatments.map(function (t) { return '<option data-en="' + esc(t.nameEn || t.name) + '">' + esc(t.name) + '</option>'; }).join("");

  // phone
  var tel = "+48" + String(d.phone).replace(/\D/g, "").replace(/^48(?=\d{9}$)/, "");
  document.querySelectorAll('a[href^="tel:"]').forEach(function (a) { a.href = "tel:" + tel; });
  var telV = document.querySelector(".i-card a.v[href^='tel:']");
  if (telV) telV.textContent = d.phone;

  // hours
  var hrs = document.querySelector(".hours");
  if (hrs) {
    hrs.innerHTML = d.hours.map(function (h) { return '<span data-en="' + esc(h.dEn || h.d) + '">' + esc(h.d) + '</span><span>' + esc(h.h) + '</span>'; }).join("");
    var note = hrs.nextElementSibling;
    if (note) { note.textContent = d.hoursNote; note.setAttribute("data-en", d.hoursNoteEn || d.hoursNote); }
  }

  // texts
  var hl = document.querySelector(".hero-side p");
  if (hl) { hl.textContent = d.texts.heroLead; hl.setAttribute("data-en", d.texts.heroLeadEn || d.texts.heroLead); }
  var al = document.querySelector("#o-nas .lead");
  if (al) { al.textContent = d.texts.aboutLead; al.setAttribute("data-en", d.texts.aboutLeadEn || d.texts.aboutLead); }

  // promo
  if (promoActive(d.promo)) {
    var hero = document.querySelector(".hero");
    var bar = document.createElement("a");
    bar.className = "promo"; bar.href = "#rezerwacja";
    var until = "";
    if (d.promo.until) { var p = d.promo.until.split("-"); until = p[2] + "." + p[1]; }
    bar.innerHTML = '<span class="promo-in"><b data-en="Promotion">Promocja</b><span data-en="' + esc(d.promo.textEn || d.promo.text) + '">' + esc(d.promo.text) + '</span>' +
      (until ? '<i data-en="until ' + until + '">do ' + until + '</i>' : "") + '<u data-en="Book">Zarezerwuj →</u></span>';
    hero.parentNode.insertBefore(bar, hero.nextSibling);
    // also show it right away at the top of the hero, so it is visible without scrolling
    var eb = hero.querySelector(".eyebrow");
    if (eb) {
      var pill = document.createElement("a");
      pill.className = "promo-pill fade"; pill.href = "#rezerwacja"; pill.style.setProperty("--d", ".05s");
      pill.innerHTML = '<b data-en="Promotion">Promocja</b><span data-en="' + esc(d.promo.textEn || d.promo.text) + '">' + esc(d.promo.text) + '</span>' + (until ? '<i data-en="until ' + until + '">do ' + until + '</i>' : "") + '<u aria-hidden="true">→</u>';
      eb.parentNode.insertBefore(pill, eb);
    }
  }

  // gallery
  var gal = document.getElementById("gal");
  if (gal) {
    var pat = ["tall", "", "", "", "wide", ""];
    gal.innerHTML = d.gallery.map(function (g, i) {
      var c = pat[i % pat.length];
      return '<button class="' + (c ? c + " " : "") + 'rv" style="--d:' + ((i % 6) * .06).toFixed(2) + 's" type="button" aria-label="Powiększ zdjęcie"><img src="' + esc(g.src) + '" alt="' + esc(g.alt) + '" loading="lazy"></button>';
    }).join("");
  }

  // record booking requests for the panel inbox
  var form = document.getElementById("form");
  if (form) form.addEventListener("submit", function () {
    var name = (document.getElementById("fName").value || "").trim(), phone = (document.getElementById("fPhone").value || "").trim();
    if (!name || !phone) return;
    var slot = document.querySelector("#slots button[aria-pressed='true']");
    var l = SpaCMS.inbox();
    l.unshift({ id: "r" + Date.now(), at: new Date().toISOString(), treat: sel ? sel.value : "", dur: document.getElementById("fDur").value, date: document.getElementById("fDate").value, slot: slot ? (slot.dataset.pl || slot.textContent) : "", name: name, phone: phone, msg: document.getElementById("fMsg").value || "", status: "nowe" });
    try { SpaCMS.saveInbox(l.slice(0, 200)); } catch (e) {}
  }, true);

  // live refresh when the panel saves in another tab
  window.addEventListener("storage", function (e) { if (e.key === KEY) location.reload(); });
})();
