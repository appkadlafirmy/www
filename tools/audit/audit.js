// Audits each candidate site on a phone viewport and extracts its content.
// usage: node audit.js candidates.tsv OUT_DIR
const { chromium } = require('playwright');
const fs = require('fs');
const [,, tsv, out] = process.argv;
fs.mkdirSync(out, { recursive: true });
const rows = fs.readFileSync(tsv, 'utf8').trim().split('\n').map(l => l.split('\t'));
const UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';
(async () => {
  const b = await chromium.launch();
  for (const [branza, firma, miasto, ulica, email, url, tel] of rows) {
    const id = email.replace(/[^a-z0-9]+/gi, '_');
    if (fs.existsSync(`${out}/${id}.json`)) continue;
    const r = { branza, firma, miasto, ulica, email, url, tel, ok: false };
    const ctx = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 390, height: 844 }, userAgent: UA, isMobile: true, hasTouch: true });
    const p = await ctx.newPage();
    let bytes = 0, broken = 0;
    p.on('response', async res => { const l = +res.headers()['content-length'] || 0; bytes += l; if (res.request().resourceType() === 'image' && res.status() >= 400) broken++; });
    try {
      let resp = null;
      for (let k = 0; k < 3 && !resp; k++) {
        try { resp = await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 40000 }); }
        catch (e) { if (k === 2) throw e; await p.waitForTimeout(2000); }
      }
      // third-party scripts are slow through this sandbox's proxy, so load time is not measured
      await Promise.race([p.waitForLoadState('load').catch(() => {}), p.waitForTimeout(8000)]);
      await p.waitForTimeout(1000);
      r.status = resp ? resp.status() : 0;
      r.finalUrl = p.url();
      r.https = r.finalUrl.startsWith('https://');
      Object.assign(r, await p.evaluate(() => {
        const vis = e => { const s = getComputedStyle(e); const rc = e.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && rc.width > 0 && rc.height > 0; };
        const vp = document.querySelector('meta[name=viewport]');
        const texts = [...document.querySelectorAll('p, li, a, span, td, div')].filter(e => e.childNodes.length && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 3) && vis(e));
        const small = texts.filter(e => parseFloat(getComputedStyle(e).fontSize) < 12).length;
        const body = document.body ? document.body.innerText : '';
        const years = [...body.matchAll(/(?:©|copyright|\(c\))\s*(?:\d{4}\s*[-–]\s*)?(\d{4})/gi)].map(m => +m[1]);
        const tels = document.querySelectorAll('a[href^="tel:"]').length;
        const md = document.querySelector('meta[name=description]');
        const imgs = [...document.images].filter(i => i.naturalWidth >= 500).map(i => i.currentSrc || i.src).filter((v, i, a) => a.indexOf(v) === i).slice(0, 12);
        const heads = [...document.querySelectorAll('h1,h2,h3')].map(h => h.innerText.trim()).filter(Boolean).slice(0, 30);
        const lis = [...document.querySelectorAll('li')].map(l => l.innerText.trim()).filter(t => t.length > 3 && t.length < 90).slice(0, 60);
        const paras = [...document.querySelectorAll('p')].map(x => x.innerText.trim()).filter(t => t.length > 40).slice(0, 25);
        return {
          viewport: !!(vp && /width\s*=\s*device-width/.test(vp.content)),
          scrollW: document.documentElement.scrollWidth,
          smallPct: texts.length ? Math.round(small / texts.length * 100) : 0,
          textCount: texts.length,
          copyYear: years.length ? Math.max(...years) : null,
          telLinks: tels,
          title: document.title,
          metaDesc: md ? md.content : '',
          h1: document.querySelectorAll('h1').length,
          flash: !!document.querySelector('embed[type*=flash], object[type*=flash]'),
          frames: document.querySelectorAll('frame, iframe[src*="index"]').length,
          tables: document.querySelectorAll('table table').length,
          generator: (document.querySelector('meta[name=generator]') || {}).content || '',
          imgs, heads, lis, paras, bodyText: body.slice(0, 6000),
        };
      }));
      r.bytes = bytes; r.brokenImgs = broken; r.ok = true;
      await p.screenshot({ path: `${out}/${id}_m.png` });
      await p.setViewportSize({ width: 1366, height: 800 });
      await p.waitForTimeout(500);
      await p.screenshot({ path: `${out}/${id}_d.png` });
    } catch (e) { r.error = String(e.message).slice(0, 200); }
    fs.writeFileSync(`${out}/${id}.json`, JSON.stringify(r, null, 1));
    console.log((r.ok ? 'ok ' : 'ERR') + ' ' + firma + ' ' + (r.error || ''));
    await ctx.close();
  }
  await b.close();
})();
