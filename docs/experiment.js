/* Experiment engine for the isometric Melbourne map.
 *
 * URL parameters:
 *   study  name of a config in studies/<study>.json (required)
 *   pid    participant id (asked for on screen in lab mode if absent)
 *   arm    force a treatment arm id; otherwise assigned at random from the seed
 *   set    force a choice-set id (studies with explicit choice sets)
 *   seed   integer seed; defaults to a hash of study + pid
 *   mode   "survey" (default; posts data to the embedding page) or "lab" (stores data in this browser)
 *
 * Studies with a "home" block ask the participant for their address first. A "place" attribute then
 * puts each option on their own street, a set distance away, or elsewhere in Melbourne.
 *
 * Output is one row per option per task (long format), clustered by pid.
 */
(async function () {
  'use strict';
  const app = document.getElementById('app');
  const params = new URLSearchParams(location.search);
  const mode = params.get('mode') === 'lab' ? 'lab' : 'survey';
  const LETTERS = 'ABCDEFGH';

  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') n.className = v; else if (k.startsWith('on')) n[k] = v; else n.setAttribute(k, v);
    }
    kids.flat().forEach(c => n.append(c));
    return n;
  };
  const fail = msg => { app.replaceChildren(el('p', { class: 'error' }, msg)); };

  // ---------- deterministic randomness ----------
  function hash(str) { let h = 2166136261; for (const c of str) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
  function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  const pick = (r, arr, weights) => {
    if (!weights) return arr[Math.floor(r() * arr.length)];
    let x = r() * weights.reduce((a, b) => a + b, 0);
    for (let i = 0; i < arr.length; i++) { x -= weights[i]; if (x < 0) return arr[i]; }
    return arr[arr.length - 1];
  };
  const shuffle = (r, arr) => { const a = arr.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

  // ---------- load ----------
  const studyId = params.get('study');
  if (!studyId || !/^[\w-]+$/.test(studyId)) return fail('No study given. Add ?study=<name> to the address.');
  let meta, study;
  try {
    [meta, study] = await Promise.all([
      fetch('map.json').then(r => r.json()),
      fetch(`studies/${studyId}.json`).then(r => { if (!r.ok) throw new Error(); return r.json(); })
    ]);
  } catch (e) { return fail(`Could not load study "${studyId}".`); }

  function project(lon, lat) {
    const u = lon - meta.proj.lon0, v = lat - meta.proj.lat0; let x = 0, y = 0;
    meta.proj.terms.forEach(([i, j], k) => { const t = Math.pow(u, i) * Math.pow(v, j); x += meta.proj.cx[k] * t; y += meta.proj.cy[k] * t; });
    return { x, y };
  }
  // offset in metres east/north of a lon/lat point
  const shift = (lon, lat, east = 0, north = 0) => [lon + east / (111320 * Math.cos(lat * Math.PI / 180)), lat + north / 110574];

  // ---------- participant ----------
  let pid = params.get('pid');
  if (!pid) {
    if (mode === 'lab') pid = await askPid();
    else pid = 'anon-' + Math.random().toString(36).slice(2, 10);
  }
  function askPid() {
    return new Promise(resolve => {
      const input = el('input', { type: 'text', id: 'pid', autocomplete: 'off' });
      const go = el('button', { type: 'submit' }, 'Continue');
      const form = el('form', {}, el('h1', {}, study.title || 'Study'), el('p', {}, el('label', { for: 'pid' }, 'Participant ID')), el('p', {}, input, ' ', go));
      form.onsubmit = ev => { ev.preventDefault(); if (input.value.trim()) resolve(input.value.trim()); };
      app.replaceChildren(form); input.focus();
    });
  }
  const seed = params.has('seed') ? (+params.get('seed') >>> 0) : hash(studyId + '|' + pid);
  const r = rng(seed);

  // ---------- between-subject treatment arm ----------
  const arms = study.arms && study.arms.length ? study.arms : [{ id: 'none' }];
  let arm = arms.find(a => a.id === params.get('arm'));
  const armForced = !!arm;
  if (!arm) arm = pick(r, arms, arms.map(a => a.weight ?? 1));
  const cfg = key => (arm[key] !== undefined ? arm[key] : study[key]);
  const view = Object.assign({ zoom: 1.2, lock: false }, study.view || {}, arm.view || {});
  const hidden = new Set(arm.hideAttributes || []);
  const attributes = (study.attributes || []).filter(a => !hidden.has(a.id));
  const attrOrder = study.randomizeAttributeOrder ? shuffle(r, attributes) : attributes;

  // ---------- home location and built-up mask ----------
  const homeCfg = arm.home === false ? null : (study.home || null);
  let home = null, mask = null;
  if (meta.mask) {
    try {
      const img = new Image(); img.src = meta.mask.file; await img.decode();
      const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
      const g = c.getContext('2d'); g.drawImage(img, 0, 0);
      mask = { w: img.width, h: img.height, data: g.getImageData(0, 0, img.width, img.height).data };
    } catch (e) { mask = null; }
  }
  const onMap = p => p.x >= 0 && p.x < meta.width && p.y >= 0 && p.y < meta.height;
  function builtUp(lon, lat) {
    const p = project(lon, lat);
    if (!onMap(p)) return false;
    if (!mask) return true;
    const mx = Math.floor(p.x / meta.mask.cellX), my = Math.floor(p.y / meta.mask.cellY);
    return mask.data[(my * mask.w + mx) * 4] > 127;
  }
  function metres(a, b) {
    const k = Math.cos((a.lat + b.lat) / 2 * Math.PI / 180);
    return Math.hypot((a.lon - b.lon) * 111320 * k, (a.lat - b.lat) * 110574);
  }
  function resolvePlace(level) {
    if (level.pool) {
      const far = study.locations.filter(l => metres(l, home) >= (level.minDistance || 0));
      return Object.assign({}, pick(r, far.length ? far : study.locations));
    }
    const [d0, d1] = [].concat(level.distance ?? 0);
    if (!d0 && !d1) return { lon: home.lon, lat: home.lat, name: level.id, fromHome: true };
    let cand = null;
    for (let tries = 0; tries < 60; tries++) {
      const d = d0 + r() * ((d1 ?? d0) - d0), b = r() * 2 * Math.PI;
      const [lon, lat] = shift(home.lon, home.lat, d * Math.sin(b), d * Math.cos(b));
      cand = { lon, lat, name: level.id, fromHome: true };
      if (builtUp(lon, lat)) return cand;
    }
    return cand;
  }

  // ---------- build the task list ----------
  const optionById = Object.fromEntries((study.options || []).map(o => [o.id, o]));
  let tasks = [], setId = '';
  function buildTasks() {
  if (study.design === 'sets') {
    // Explicit choice sets: each set is a list of tasks, each task a list of option ids.
    const sets = study.choiceSets || [];
    let set = sets.find(s => s.id === (params.get('set') || arm.choiceSet));
    if (!set) set = pick(r, sets, sets.map(s => s.weight ?? 1));
    setId = set.id;
    let list = set.tasks.map(ids => ids.map(id => optionById[id]));
    if (study.randomizeTaskOrder) list = shuffle(r, list);
    tasks = list.map(opts => (study.randomizeOptionOrder === false ? opts : shuffle(r, opts)).map(o => ({
      location: o, levels: o.attributes || {}, optionId: o.id })));
  } else {
    // Conjoint: profiles drawn independently for each option in each task.
    const n = study.optionsPerTask || 2;
    const placeAttr = attributes.find(a => a.type === 'place');
    const banned = study.restrictions || [];
    const allowed = lv => !banned.some(rule => Object.entries(rule).every(([k, v]) => lv[k] === v));
    const draw = () => { for (let tries = 0; tries < 200; tries++) {
      const lv = {}; attributes.forEach(a => { lv[a.id] = pick(r, a.levels.map(l => l.id ?? l), a.weights); });
      if (allowed(lv)) return lv; } throw new Error('restrictions leave no valid profile'); };
    for (let t = 0; t < (study.tasks || 5); t++) {
      const pool = shuffle(r, study.locations);
      const fixed = study.sameLocationWithinTask ? pool[0] : null;
      const opts = [];
      for (let o = 0; o < n; o++) {
        let lv, guard = 0;
        do { lv = draw(); } while (opts.some(p => JSON.stringify(p.levels) === JSON.stringify(lv)) && guard++ < 50);
        let loc;
        if (placeAttr && home) loc = resolvePlace(levelOf(placeAttr, lv[placeAttr.id]));
        else { if (placeAttr) delete lv[placeAttr.id]; loc = fixed || pool[o % pool.length]; }
        opts.push({ location: loc, levels: lv, optionId: '' });
      }
      tasks.push(opts);
    }
  }
  }
  const levelOf = (attr, id) => { const l = attr.levels.find(x => (x.id ?? x) === id); return typeof l === 'object' ? l : { id: l, label: l }; };
  const showMarkers = cfg('showMarkers') !== false;

  // ---------- data ----------
  const rows = [];
  const homeDp = homeCfg ? (homeCfg.recordDecimals ?? 2) : -1;
  const started = new Date().toISOString();
  const send = (type, extra = {}) => {
    const msg = Object.assign({ source: 'isometric-melbourne', type, study: studyId, pid, arm: arm.id, choiceSet: setId, seed }, extra);
    if (window.parent !== window) window.parent.postMessage(msg, '*');
    return msg;
  };
  function saveLab() {
    try {
      const key = 'isomelb:' + studyId;
      const all = JSON.parse(localStorage.getItem(key) || '[]').filter(x => !(x.pid === pid && x.started === started));
      all.push(...rows);
      localStorage.setItem(key, JSON.stringify(all));
    } catch (e) { /* storage unavailable: data still shown on the end screen */ }
  }

  // ---------- screens ----------
  let viewers = [];
  function marker(text, colour) {
    return el('div', { class: 'marker' }, el('div', { class: 'tag' }, text), el('div', { class: 'stem' }),
      el('div', { class: 'dot', style: `background:${colour || '#c86a48'}` }));
  }
  function addMarker(v, m, lon, lat) {
    const [mlon, mlat] = m.lon !== undefined ? [m.lon, m.lat] : shift(lon, lat, m.east || 0, m.north || 0);
    const p = project(mlon, mlat);
    v.addOverlay({ element: marker(m.label, m.colour), location: v.viewport.imageToViewportCoordinates(p.x, p.y),
      placement: OpenSeadragon.Placement.BOTTOM });
  }

  function intro() {
    const body = [].concat(cfg('intro') || []).map(t => el('p', {}, t));
    const begin = () => { buildTasks(); task(0); };
    const go = el('button', { type: 'button', onclick: () => (homeCfg ? homeStep(begin) : begin()) }, 'Start');
    app.replaceChildren(el('h1', {}, study.title || 'Study'), ...body, el('div', { class: 'next' }, go));
    go.focus();
  }

  // Ask for the participant's address, geocode it, and keep only the coordinates.
  function homeStep(done) {
    const input = el('input', { type: 'text', id: 'addr', autocomplete: 'street-address', style: 'width:min(100%,420px)' });
    const status = el('p', { role: 'status' });
    const list = el('div', {});
    const cont = el('button', { type: 'button', disabled: '', onclick: done }, 'Continue');
    const form = el('form', {}, el('p', {}, el('label', { for: 'addr' }, homeCfg.prompt || 'Please enter your home address in Melbourne.')),
      el('p', {}, input, ' ', el('button', { type: 'submit' }, 'Find')));
    form.onsubmit = async ev => {
      ev.preventDefault();
      const q = input.value.trim(); list.replaceChildren(); if (!q) return;
      status.textContent = 'Searching…';
      const [w, s, e, n] = meta.bbox;
      const url = 'https://nominatim.openstreetmap.org/search?' + new URLSearchParams({
        format: 'jsonv2', q, countrycodes: 'au', viewbox: `${w},${n},${e},${s}`, bounded: 1, limit: 6 });
      try {
        const hits = (await fetch(url).then(x => { if (!x.ok) throw new Error(); return x.json(); }))
          .map(h => ({ name: h.display_name.replace(/, Victoria.*$/, ''), lon: +h.lon, lat: +h.lat }))
          .filter(h => onMap(project(h.lon, h.lat)));
        if (!hits.length) { status.textContent = 'No match found. Try adding your suburb.'; return; }
        status.textContent = 'Choose your address:';
        hits.forEach(h => list.append(el('p', {}, el('button', { type: 'button', class: 'choose', style: 'margin:0', onclick: () => {
          home = { lon: h.lon, lat: h.lat };
          status.textContent = 'Selected: ' + h.name; list.replaceChildren(); cont.disabled = false; cont.focus();
        } }, h.name))));
      } catch (err) { status.textContent = 'Address search is unavailable right now. Please try again.'; }
    };
    const kids = [el('h1', {}, study.title || 'Study'), form, status, list];
    if (homeCfg.note) kids.push(el('p', { style: 'font-size:12px;opacity:.75' }, homeCfg.note));
    const row = el('div', { class: 'next' });
    if (homeCfg.required === false) row.append(el('button', { type: 'button', class: 'choose', style: 'margin:0 12px 0 0', onclick: done }, 'Skip'));
    row.append(cont); kids.push(row);
    app.replaceChildren(...kids); input.focus();
  }

  function task(t) {
    viewers.forEach(v => v.destroy()); viewers = [];
    if (t >= tasks.length) return finish();
    const opts = tasks[t];
    const t0 = performance.now();
    const state = { chosen: null, ratings: {}, firstChoiceMs: null, changes: 0 };
    const track = opts.map(() => ({ drags: 0, zooms: 0 }));
    const rating = study.outcomes && study.outcomes.rating;
    const wantChoice = !study.outcomes || study.outcomes.choice !== false;
    const next = el('button', { type: 'button', disabled: '' }, t + 1 === tasks.length ? 'Finish' : 'Next');
    const ready = () => (!wantChoice || state.chosen !== null) && (!rating || opts.every((_, i) => state.ratings[i] !== undefined));
    const refresh = () => { next.disabled = !ready(); cards.forEach((c, i) => c.classList.toggle('chosen', state.chosen === i)); };

    const cards = opts.map((o, i) => {
      const viewEl = el('div', { class: 'view', 'aria-label': `Map for option ${LETTERS[i]}` });
      const table = el('table', {}, attrOrder.filter(a => a.id in o.levels && !a.mapOnly).map(a =>
        el('tr', {}, el('th', { scope: 'row' }, a.label), el('td', {}, levelOf(a, o.levels[a.id]).label))));
      const card = el('section', { class: 'option' }, el('h2', {}, `Option ${LETTERS[i]}` + (study.showLocationNames && o.location.name ? ` · ${o.location.name}` : '')), viewEl, table);
      if (rating) {
        const scale = el('div', { class: 'scale', role: 'radiogroup', 'aria-label': `${rating.label}, option ${LETTERS[i]}` });
        for (let k = rating.min; k <= rating.max; k++) {
          const input = el('input', { type: 'radio', name: `rate${i}`, value: k });
          input.onchange = () => { state.ratings[i] = k; refresh(); };
          scale.append(el('label', {}, input, el('span', {}, String(k))));
        }
        card.append(el('div', { class: 'rating' }, rating.label, scale,
          el('div', { class: 'ends' }, el('span', {}, rating.minLabel || ''), el('span', {}, rating.maxLabel || ''))));
      }
      if (wantChoice) card.append(el('button', { type: 'button', class: 'choose', onclick: () => {
        if (state.chosen !== null && state.chosen !== i) state.changes++;
        if (state.firstChoiceMs === null) state.firstChoiceMs = Math.round(performance.now() - t0);
        state.chosen = i; refresh(); } }, `Choose ${LETTERS[i]}`));
      return card;
    });

    next.onclick = () => {
      const rt = Math.round(performance.now() - t0);
      opts.forEach((o, i) => {
        const row = { pid, study: studyId, arm: arm.id, arm_forced: armForced ? 1 : 0, choice_set: setId, seed, started, mode,
          task: t + 1, option: LETTERS[i], option_id: o.optionId, location: o.location.name || '',
          // sites derived from the home address are saved no more precisely than the home itself
          lon: o.location.fromHome ? (homeDp >= 0 ? +o.location.lon.toFixed(homeDp) : '') : +o.location.lon.toFixed(5),
          lat: o.location.fromHome ? (homeDp >= 0 ? +o.location.lat.toFixed(homeDp) : '') : +o.location.lat.toFixed(5),
          home_lon: home && homeDp >= 0 ? +home.lon.toFixed(homeDp) : '', home_lat: home && homeDp >= 0 ? +home.lat.toFixed(homeDp) : '',
          dist_home_m: home ? Math.round(metres(o.location, home) / 10) * 10 : '' };
        (study.attributes || []).forEach(a => { row['attr_' + a.id] = a.id in o.levels && !hidden.has(a.id) ? o.levels[a.id] : ''; });
        Object.assign(row, { chosen: wantChoice ? (state.chosen === i ? 1 : 0) : '', rating: rating ? state.ratings[i] : '',
          rt_ms: rt, first_choice_ms: state.firstChoiceMs ?? '', choice_changes: state.changes,
          map_drags: track[i].drags, map_zooms: track[i].zooms });
        rows.push(row);
      });
      send('task', { task: t + 1, rows: rows.slice(-opts.length) });
      if (mode === 'lab') saveLab();
      task(t + 1);
    };

    app.replaceChildren(
      el('div', { class: 'bar' }, el('span', {}, `Question ${t + 1} of ${tasks.length}`), el('span', {}, view.lock ? '' : 'Drag to move each map, scroll to zoom')),
      el('p', {}, cfg('prompt') || 'Which option do you prefer?'),
      el('div', { class: 'options', style: `--n:${opts.length}` }, cards),
      el('div', { class: 'next' }, next));

    opts.forEach((o, i) => {
      const v = OpenSeadragon({
        element: cards[i].querySelector('.view'), showNavigationControl: false, showNavigator: false,
        tileSources: { width: meta.width, height: meta.height, tileSize: meta.tile, minLevel: 0, maxLevel: meta.maxLevel,
          getTileUrl: (l, x, y) => `tiles/${l}/${x}_${y}.webp` },
        maxZoomPixelRatio: 4, visibilityRatio: 1, constrainDuringPan: true, animationTime: 0.4,
        mouseNavEnabled: !view.lock, gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: false }
      });
      viewers.push(v);
      v.addHandler('open', () => {
        const c = project(o.location.lon, o.location.lat);
        v.viewport.zoomTo(v.viewport.imageToViewportZoom(view.zoom), null, true);
        v.viewport.panTo(v.viewport.imageToViewportCoordinates(c.x, c.y), true);
        v.drawer.setImageSmoothingEnabled(view.zoom < 1);
        if (home) addMarker(v, { label: homeCfg.markerLabel || 'Your home', colour: '#23252e', lon: home.lon, lat: home.lat });
        if (o.location.label) addMarker(v, { label: o.location.label, colour: '#23252e' }, o.location.lon, o.location.lat);
        if (showMarkers) attributes.forEach(a => { const lv = levelOf(a, o.levels[a.id]); if (lv && lv.marker) addMarker(v, lv.marker, o.location.lon, o.location.lat); });
        (arm.markers || []).forEach(m => addMarker(v, m, o.location.lon, o.location.lat));
        (o.location.markers || []).forEach(m => addMarker(v, m, o.location.lon, o.location.lat));
      });
      v.addHandler('canvas-drag-end', () => track[i].drags++);
      v.addHandler('canvas-scroll', () => track[i].zooms++);
    });
    window.scrollTo(0, 0);
  }

  function finish() {
    const code = 'IM-' + hash(studyId + pid + seed).toString(36).toUpperCase();
    send('complete', { rows, code });
    if (mode === 'lab') {
      saveLab();
      app.replaceChildren(el('h1', {}, 'Thank you'), el('p', {}, 'Your answers are saved. Please let the experimenter know you have finished.'),
        el('div', { class: 'next' }, el('button', { type: 'button', onclick: () => { location.href = 'lab.html'; } }, 'Experimenter: next participant')));
    } else {
      const done = [].concat(study.outro || 'Thank you. Your answers have been recorded.').map(t => el('p', {}, t));
      app.replaceChildren(el('h1', {}, 'Thank you'), ...done,
        window.parent === window ? el('p', {}, 'Completion code: ', el('code', {}, code)) : '');
    }
  }

  send('ready');
  intro();
})();
