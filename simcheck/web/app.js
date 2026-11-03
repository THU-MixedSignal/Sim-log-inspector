'use strict';
// Spectre Log Inspector: only what is needed to decide whether a run needs attention.
// Log-derived text is always inserted with textContent, never parsed as HTML.
(() => {
  const API = 4;
  const POLL_MS = 2000;
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);

  const STATUS = {
    complete: 'Complete', failed: 'Failed', unknown: 'Unknown', incomplete: 'Incomplete evidence',
    running: 'Running', indexing: 'Indexing', queued: 'Queued', starting: 'Starting',
    submitted: 'Submitted', waiting: 'Waiting',
  };
  const SEV = {
    FATAL: { glyph: '■', name: 'Fatal', cls: 'critical' },
    ERROR: { glyph: '■', name: 'Error', cls: 'critical' },
    WARNING: { glyph: '▲', name: 'Warning', cls: 'warning' },
    NOTICE: { glyph: '●', name: 'Notice', cls: 'notice' },
    INFO: { glyph: '◆', name: 'Testbench', cls: 'info' },
  };
  const COUNTS = [['E', 'ERROR'], ['W', 'WARNING'], ['T', 'INFO'], ['N', 'NOTICE']];
  const LEVEL_RANK = { critical: 0, warning: 1, new: 2, none: 3 };
  const UNITS = [[1, 's'], [1e-3, 'ms'], [1e-6, 'µs'], [1e-9, 'ns'], [1e-12, 'ps'], [1e-15, 'fs']];

  const ui = {
    data: null, error: null, selected: null, tab: 'problems', paused: false, busy: false,
    shows: new Map(), rows: new Map(), previous: new Map(), evidence: new Map(),
    expanded: new Map(), openFolds: new Set(), fresh: new Set(), details: new Map(),
    meas: null, problemSig: '', collectorLive: null, notify: false,
  };

  // ---------------------------------------------------------------- helpers
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function svg(tag, attrs, cls) {
    const n = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
    if (cls) n.setAttribute('class', cls);
    return n;
  }
  function has(value) { return value !== undefined && value !== null; }
  function sevOf(name) { return SEV[name] || SEV.INFO; }
  function glyph(sev) {
    const s = sevOf(sev);
    const n = el('span', 'glyph sev-' + s.cls, s.glyph);
    n.setAttribute('aria-hidden', 'true');
    return n;
  }
  function chip(text, cls, title) {
    const c = el('span', 'chip' + (cls ? ' ' + cls : ''), text);
    if (title) c.title = title;
    return c;
  }
  function fmtTime(s) {
    if (!has(s)) return '—';
    if (s === 0) return '0 s';
    for (const [scale, unit] of UNITS) {
      if (Math.abs(s) >= scale * 0.9999995 || unit === 'fs') return `${+(s / scale).toPrecision(6)} ${unit}`;
    }
    return `${s} s`;
  }
  function fmtPct(p) {
    if (!has(p)) return '';
    if (p >= 10) return `${p.toFixed(1)}%`;
    if (p >= 1) return `${p.toFixed(2)}%`;
    if (p >= 0.001) return `${p.toFixed(3)}%`;
    return '<0.001%';
  }
  function fmtAge(seconds) {
    if (!has(seconds)) return '—';
    const s = Math.max(0, seconds);
    if (s < 90) return `${Math.round(s)} s`;
    if (s < 5400) return `${Math.round(s / 60)} min`;
    if (s < 172800) return `${(s / 3600).toFixed(1)} h`;
    return `${Math.round(s / 86400)} d`;
  }
  function bytes(n) {
    if (!has(n)) return '—';
    if (n < 1024) return `${n} B`;
    if (n < 1048576) return `${(n / 1024).toFixed(1)} KiB`;
    return `${(n / 1048576).toFixed(1)} MiB`;
  }
  function clockTime(epoch) { return new Date(epoch * 1000).toLocaleTimeString('en-US', { hour12: false }); }
  function clamp(f) { return has(f) ? Math.min(1, Math.max(0, f)) : null; }
  function clip(text, n) { return text.length > n ? `${text.slice(0, n - 1)}…` : text; }
  function gkey(g) { return `${g.key}|${g.sev}`; }
  function uncoded(g) { return g.key.startsWith(`${g.sev}:`); }
  function label(g) { return uncoded(g) ? g.msg : g.key; }
  function announce(text) { $('live').textContent = text; }

  async function api(path, params) {
    const url = params ? `${path}?${new URLSearchParams(params)}` : path;
    const response = await fetch(url, { cache: 'no-store' });
    let body = null;
    try { body = await response.json(); } catch (_) { body = null; }
    if (!response.ok) throw new Error(body && body.error ? body.error.message : `HTTP ${response.status}`);
    return body;
  }

  // ---------------------------------------------------------------- what this browser has already seen
  function ackKeys(run) {
    try {
      const stored = JSON.parse(localStorage.getItem('simcheck.ack.' + run) || 'null');
      return stored ? new Set(stored.keys) : null;
    } catch (_) { return null; }
  }
  function saveAck(run, keys) { localStorage.setItem('simcheck.ack.' + run, JSON.stringify({ keys: [...keys] })); }
  function groupsOf(id) { const s = ui.shows.get(id); return s ? s.data.groups : []; }
  function newGroups(run) {
    const seen = ackKeys(run.run);
    if (!seen) return [];
    return groupsOf(run.run).filter((g) => (g.sev !== 'NOTICE' || g.rules) && !seen.has(gkey(g)));
  }
  function acknowledge(run) {
    const seen = ackKeys(run.run) || new Set();
    for (const g of groupsOf(run.run)) seen.add(gkey(g));
    saveAck(run.run, seen);
    ui.problemSig = '';
    render();
  }

  // ---------------------------------------------------------------- data flow
  function newText(g) {
    const rules = g.rules ? `, rule hit: ${g.rules.join(', ')}` : '';
    const when = has(g.t) ? `, first at ${fmtTime(g.t)}` : '';
    return `New problem ${clip(label(g), 60)} (${g.sev})${rules}${when}`;
  }
  async function syncShows(runs) {
    const events = [];
    await Promise.all(runs.map(async (run) => {
      const sig = `${run.gen || 1}:${run.last_problem || 0}`;
      const cached = ui.shows.get(run.run);
      if (cached && cached.sig === sig) return;
      const data = await api('/api/show', { run: run.run, full: 1 });
      const before = cached ? new Map(cached.data.groups.map((g) => [gkey(g), g])) : null;
      ui.shows.set(run.run, { sig, data });
      if (!ackKeys(run.run)) saveAck(run.run, new Set(data.groups.map(gkey)));
      if (!before) return;
      for (const g of data.groups) {
        const old = before.get(gkey(g));
        if (!old) {
          ui.fresh.add(`${run.run}|${gkey(g)}`);
          if (g.sev !== 'NOTICE' || g.rules) events.push({ run: run.run, text: newText(g) });
        } else {
          for (const rule of (g.rules || []).filter((r) => !(old.rules || []).includes(r))) {
            events.push({ run: run.run, text: `Rule hit "${rule}": ${clip(label(g), 60)}` });
          }
        }
      }
    }));
    return events;
  }
  function detectChanges(data, events) {
    for (const run of data.runs) {
      const prev = ui.previous.get(run.run);
      if (prev) {
        if (prev.state !== run.state && ['failed', 'complete', 'incomplete'].includes(run.state)) {
          events.unshift({ run: run.run, text: `Status changed to ${STATUS[run.state] || run.state}` });
        }
        const before = prev.flags || [];
        for (const flag of run.flags || []) {
          if (before.includes(flag)) continue;
          if (flag === 'quiet') events.push({ run: run.run, text: `Log unchanged for ${fmtAge(run.log_age)}` });
          if (flag === 'collector_error') events.push({ run: run.run, text: 'Collector error' });
          if (flag === 'source_error') events.push({ run: run.run, text: 'Log read failed' });
        }
      }
      ui.previous.set(run.run, run);
    }
    if (ui.collectorLive === true && !data.collector.live) events.push({ run: null, text: 'Collector heartbeat stopped' });
    ui.collectorLive = data.collector.live;
    // One notification per run per refresh: a failure usually arrives as several lines at once.
    const byRun = new Map();
    for (const e of events) {
      if (!byRun.has(e.run)) byRun.set(e.run, []);
      byRun.get(e.run).push(e.text);
    }
    for (const [run, texts] of byRun) notify(run ? `Spectre ${run}` : 'Spectre Log Inspector', texts.join('; '));
    if (events.length) announce(events.map((e) => (e.run ? `${e.run}: ` : '') + e.text).join('; '));
  }
  function notify(title, body) {
    if (!ui.notify || !('Notification' in window) || Notification.permission !== 'granted') return;
    try { new Notification(title, { body }); } catch (_) { /* platform without page notifications */ }
  }
  async function refresh() {
    if (ui.busy) return;
    ui.busy = true;
    try {
      const data = await api('/api/status');
      if (data.v !== API) throw new Error(`Viewer API version ${data.v} differs from page version ${API}. Restart simcheck.`);
      ui.data = data;
      ui.error = null;
      detectChanges(data, await syncShows(data.runs));
      render();
      await refreshPanel();
    } catch (e) {
      ui.error = e instanceof TypeError ? 'Cannot connect to the viewer.' : e.message;
      renderTopline();
    } finally {
      ui.busy = false;
    }
  }
  function tick() {
    const run = ui.paused ? Promise.resolve() : refresh();
    run.finally(() => setTimeout(tick, POLL_MS));
  }

  // ---------------------------------------------------------------- top line
  function renderTopline() {
    const box = $('collector');
    const banner = $('banner');
    banner.hidden = true;
    banner.className = 'banner';
    box.classList.remove('offline');
    box.removeAttribute('title');
    if (ui.error) {
      box.replaceChildren(glyph('ERROR'), document.createTextNode(' Unable to read data'));
      banner.textContent = ui.error;
      banner.classList.add('critical');
      banner.hidden = false;
      return;
    }
    if (!ui.data) return;
    const c = ui.data.collector;
    if (c.live) {
      box.replaceChildren(el('span', 'dot', '●'), document.createTextNode('Collecting'));
      box.title = `Heartbeat ${fmtAge(c.hb)} ago, version ${c.version}, PID ${c.pid}`;
      if (c.version && c.version !== ui.data.version) {
        banner.textContent = `Collector version ${c.version} differs from viewer version ${ui.data.version}`;
        banner.hidden = false;
      }
    } else {
      box.classList.add('offline');
      box.replaceChildren(glyph('WARNING'), document.createTextNode(has(c.hb)
        ? ' Collector offline · data not updating' : ' No collector · data not updating'));
      if (has(c.hb)) box.title = `Last heartbeat ${clockTime(Date.now() / 1000 - c.hb)}`;
    }
  }

  // ---------------------------------------------------------------- run list
  function level(run) {
    const f = run.flags || [];
    if (f.includes('failed') || f.includes('rule')) return 'critical';
    if (f.length) return 'warning';
    return newGroups(run).length ? 'new' : 'none';
  }
  function stateText(run) {
    return STATUS[run.state] || run.state;
  }
  function countItems(run) {
    const n = run.n || {};
    return COUNTS.filter(([letter]) => n[letter]).map(([letter, sev]) => {
      const span = el('span', 'count');
      span.append(glyph(sev), el('span', 'sr-only', sevOf(sev).name), document.createTextNode(String(n[letter])));
      return span;
    });
  }
  function rowFor(id) {
    let row = ui.rows.get(id);
    if (row) return row;
    const li = el('li');
    const button = el('button', 'run-row');
    button.type = 'button';
    const name = el('span', 'run-name');
    const side = el('span', 'run-side');
    const counts = el('span', 'run-counts');
    const mini = svg('svg', { 'aria-hidden': 'true', focusable: 'false' }, 'mini');
    button.append(name, side, counts, mini);
    button.addEventListener('click', () => select(id));
    li.append(button);
    row = { li, button, name, side, counts, mini };
    ui.rows.set(id, row);
    return row;
  }
  function updateRow(row, run, lvl) {
    row.button.className = `run-row level-${lvl}`;
    row.button.dataset.state = run.state;
    row.button.setAttribute('aria-current', run.run === ui.selected ? 'true' : 'false');
    const reasons = { failed: 'Failed', rule: 'Rule hit', quiet: 'Log unchanged',
      collector_error: 'Collector error', source_error: 'Log read failed' };
    row.button.title = (run.flags || []).map((f) => reasons[f] || f).join(', ');
    const fresh = newGroups(run).length;
    row.name.replaceChildren(document.createTextNode(run.run));
    if (fresh) row.name.append(el('span', 'badge-new', `${fresh} new`));
    row.side.textContent = stateText(run);
    row.counts.replaceChildren(...countItems(run));
  }
  function railOrder(runs) {
    // Running runs first within a level: stopping those is what saves simulation time.
    return runs.map((r) => ({ r, lvl: level(r) })).sort((a, b) => LEVEL_RANK[a.lvl] - LEVEL_RANK[b.lvl]
      || Number(Boolean(a.r.ended)) - Number(Boolean(b.r.ended))
      || Number(!(a.r.flags || []).includes('failed')) - Number(!(b.r.flags || []).includes('failed'))
      || a.r.run.localeCompare(b.r.run));
  }
  function renderRail(runs) {
    const active = document.activeElement;
    const list = $('runs');
    const ordered = railOrder(runs);
    const picker = $('run-select');
    const options = new Map([...picker.options].map((o) => [o.value, o]));
    ordered.forEach(({ r, lvl }, i) => {
      const row = rowFor(r.run);
      updateRow(row, r, lvl);
      if (list.children[i] !== row.li) list.insertBefore(row.li, list.children[i] || null);
      const option = options.get(r.run) || el('option');
      option.value = r.run;
      const text = `${r.run} — ${stateText(r)}`;
      if (option.textContent !== text) option.textContent = text;
      if (picker.children[i] !== option) picker.insertBefore(option, picker.children[i] || null);
    });
    for (const id of [...ui.rows.keys()]) {
      if (!runs.some((r) => r.run === id)) { ui.rows.get(id).li.remove(); ui.rows.delete(id); }
    }
    for (const option of [...picker.options]) {
      if (!runs.some((r) => r.run === option.value)) option.remove();
    }
    if (picker.value !== ui.selected) picker.value = ui.selected || '';
    picker.disabled = !runs.length;
    for (const { r } of ordered) drawTimeline(ui.rows.get(r.run).mini, r, true);
    if (active && document.contains(active) && document.activeElement !== active) active.focus({ preventScroll: true });
  }

  // ---------------------------------------------------------------- simulation-time axis
  function markerShape(cls, x, y, size) {
    const r = size / 2;
    if (cls === 'critical') return svg('rect', { x: x - r, y: y - r, width: size, height: size, rx: 1 }, 'mark');
    if (cls === 'warning') return svg('path', { d: `M${x} ${y - r - 1}L${x + r + 1} ${y + r}L${x - r - 1} ${y + r}Z` }, 'mark');
    if (cls === 'info') return svg('path', { d: `M${x} ${y - r - 1}L${x + r + 1} ${y}L${x} ${y + r + 1}L${x - r - 1} ${y}Z` }, 'mark');
    return svg('circle', { cx: x, cy: y, r }, 'mark');
  }
  function drawTimeline(target, run, mini) {
    const cache = ui.shows.get(run.run);
    const groups = cache ? cache.data.groups : [];
    const width = Math.max(target.clientWidth || 0, mini ? 120 : 320);
    const height = mini ? 8 : 52;
    // Redraw only when something drawn changed; rebuilding on every poll would drop keyboard focus.
    const sig = JSON.stringify([width, run.state, run.stop, run.pct, run.ended, run.analysis, cache ? cache.sig : null]);
    if (target.dataset.sig === sig) return;
    target.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const focused = target.contains(document.activeElement) ? document.activeElement.getAttribute('data-key') : null;
    const parts = [];
    const stop = run.stop;
    if (stop) {
      const pad = mini ? 4 : 10;
      const x0 = pad;
      const span = width - 2 * pad;
      const trackY = mini ? 2 : 24;
      const trackH = mini ? 3 : 6;
      const ended = run.ended ? ' ended' : '';
      if (!mini) {
        for (let i = 0; i <= 10; i += 1) {
          const x = x0 + (span * i) / 10;
          parts.push(svg('line', { x1: x, x2: x, y1: trackY - 5, y2: trackY + trackH + 4 }, i % 5 === 0 ? 'tick' : 'grid'));
        }
      }
      parts.push(svg('rect', { x: x0, y: trackY, width: span, height: trackH, rx: trackH / 2 }, 'track' + ended));
      const f = run.state === 'complete' ? 1 : has(run.pct) ? clamp(run.pct / 100) : null;
      if (f !== null) {
        parts.push(svg('rect', { x: x0, y: trackY, width: Math.max(trackH, span * f), height: trackH, rx: trackH / 2 }, 'fill' + ended));
      }
      if (!mini) {
        const y = trackY + trackH + 18;
        [[x0, '0', 'start'], [x0 + span / 2, fmtTime(stop / 2), 'middle'], [x0 + span, fmtTime(stop), 'end']].forEach(([x, text, anchor]) => {
          const t = svg('text', { x, y, 'text-anchor': anchor }, 'axis-label');
          t.textContent = text;
          parts.push(t);
        });
      }
      const marks = groups
        .filter((g) => has(g.pct) && g.phase === run.analysis && (g.sev !== 'NOTICE' || g.rules))
        .map((g) => ({ g, x: x0 + span * clamp(g.pct / 100), cls: sevOf(g.sev).cls, hit: Boolean(g.rules) }))
        .sort((a, b) => a.x - b.x || a.g.e - b.g.e);
      // Markers closer than their hit area merge: early problems pile up at the left edge.
      const rank = { critical: 0, warning: 1, info: 2, notice: 3 };
      const clusters = [];
      for (const m of marks) {
        const last = clusters[clusters.length - 1];
        if (last && m.x - last.x <= (mini ? 4 : 14)) last.members.push(m);
        else clusters.push({ x: m.x, members: [m] });
      }
      const y = mini ? trackY + trackH / 2 : trackY - 11;
      let labelEnd = -Infinity;
      for (const c of clusters) {
        const lead = c.members.reduce((a, b) => (rank[b.cls] < rank[a.cls] ? b : a));
        const group = svg('g', {}, `marker sev-${lead.cls}`);
        if (!mini) {
          const earliest = c.members.reduce((a, b) => (b.g.t < a.g.t ? b : a)).g;
          group.setAttribute('tabindex', '0');
          group.setAttribute('role', 'button');
          group.setAttribute('data-key', gkey(earliest));
          group.setAttribute('aria-label', `${c.members.map((m) => clip(label(m.g), 40)).join(', ')}, first at ${fmtTime(earliest.t)}`);
          group.append(svg('circle', { cx: c.x, cy: y, r: 12 }, 'hit'));
          if (c.members.some((m) => m.hit)) group.append(svg('circle', { cx: c.x, cy: y, r: 8.5 }, 'halo'));
          const show = (e) => showTip(e.currentTarget, c.members.map((m) => m.g));
          group.addEventListener('pointerenter', show);
          group.addEventListener('focus', show);
          group.addEventListener('pointerleave', hideTip);
          group.addEventListener('blur', hideTip);
          group.addEventListener('click', () => openGroup(earliest));
          group.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openGroup(earliest); } });
          if (c.members.length > 1 && c.x - 4 > labelEnd) {
            const text = `${c.members.length} groups, first at ${fmtTime(earliest.t)} (${fmtPct(earliest.pct)})`;
            const t = svg('text', { x: Math.max(0, c.x - 4), y: y - 13 }, 'cluster-label');
            t.textContent = text;
            parts.push(t);
            labelEnd = c.x + [...text].reduce((w, ch) => w + (ch.charCodeAt(0) > 0x2e7f ? 12 : 6.5), 0);
          }
        }
        group.append(markerShape(lead.cls, c.x, y, mini ? 5 : 9));
        parts.push(group);
      }
    }
    target.replaceChildren(...parts);
    target.dataset.sig = sig;
    if (focused) {
      const again = [...target.querySelectorAll('.marker')].find((n) => n.getAttribute('data-key') === focused);
      if (again) again.focus({ preventScroll: true });
    }
  }
  function showTip(anchor, groups) {
    const tip = $('tooltip');
    const lines = [];
    for (const g of groups.slice(0, 6)) {
      lines.push(el('strong', null, clip(label(g), 60)),
        el('span', null, `${sevOf(g.sev).name} ×${g.n}${g.sup ? '+' : ''}, first at ${fmtTime(g.t)} (${fmtPct(g.pct)})`));
    }
    if (groups.length > 6) lines.push(el('span', null, `${groups.length - 6} more groups`));
    tip.replaceChildren(...lines);
    tip.hidden = false;
    const r = anchor.getBoundingClientRect();
    const left = Math.min(window.innerWidth - tip.offsetWidth - 8, Math.max(8, r.left + r.width / 2 - tip.offsetWidth / 2));
    const above = r.top - tip.offsetHeight - 8;
    tip.style.left = `${left}px`;
    tip.style.top = `${above > 8 ? above : r.bottom + 8}px`;
  }
  function hideTip() { $('tooltip').hidden = true; }

  // ---------------------------------------------------------------- run header
  function renderHead(run) {
    $('run-title').textContent = run.run;
    const state = $('run-state');
    state.textContent = stateText(run);
    state.className = 'run-state' + (run.state === 'failed' ? ' is-failed'
      : ['unknown', 'incomplete'].includes(run.state) ? ' is-uncertain' : '');
    const chips = [];
    const f = run.flags || [];
    if (f.includes('quiet')) chips.push(chip(`Log unchanged for ${fmtAge(run.log_age)}`, 'warning'));
    if (f.includes('collector_error')) chips.push(chip('Collector error', 'warning', run.error));
    if (f.includes('source_error')) chips.push(chip('Log read failed', 'warning', run.error));
    $('run-chips').replaceChildren(...chips);
    const fresh = newGroups(run).length;
    $('ack').hidden = !fresh;
    $('ack').textContent = `Mark read (${fresh} new)`;
    const meta = [];
    if (run.gen) meta.push(`Generation ${run.gen}`);
    if (!run.ended && has(run.log_age)) meta.push(`Log updated ${fmtAge(run.log_age)} ago`);
    $('facts').textContent = meta.join(' · ');
    $('run-error').hidden = !run.error;
    $('run-error').textContent = run.error || '';
    const progress = $('progress');
    progress.hidden = !has(run.t);
    progress.replaceChildren();
    if (has(run.t)) {
      progress.append(document.createTextNode(run.stop ? `${fmtTime(run.t)} / ${fmtTime(run.stop)}` : fmtTime(run.t)));
      if (has(run.pct)) progress.append(el('small', null, fmtPct(run.pct)));
    }
    $('timeline-box').hidden = !run.stop && !has(run.t);
    $('timeline').hidden = !run.stop;
  }

  // ---------------------------------------------------------------- problems
  function groupId(run, g) { return `${run.run}|${gkey(g)}`; }
  function phaseTitle(phase) {
    if (phase === 'setup') return 'Setup';
    if (phase === 'testbench') return 'Testbench';
    return phase;
  }
  function renderProblems(run, force) {
    const cache = ui.shows.get(run.run);
    const show = cache ? cache.data : { groups: [] };
    const seen = ackKeys(run.run) || new Set();
    const sig = JSON.stringify([run.run, cache && cache.sig, [...seen].sort()]);
    if (!force && sig === ui.problemSig) return;
    ui.problemSig = sig;
    const panel = $('panel-problems');
    const focused = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.group : null;
    const sections = new Map();
    for (const g of show.groups) {
      const phase = g.sev === 'INFO' ? 'testbench' : g.phase;
      if (!sections.has(phase)) sections.set(phase, []);
      sections.get(phase).push(g);
    }
    const rank = (p) => (p === 'testbench' ? 1 : p === 'setup' ? 2 : 0);
    const first = (p) => Math.min(...sections.get(p).map((g) => g.e));
    const order = [...sections.keys()].sort((a, b) => rank(a) - rank(b) || first(a) - first(b));
    const nodes = [];
    if (!show.groups.length) nodes.push(el('p', 'panel-note', 'No problem records.'));
    for (const phase of order) {
      const section = el('section', 'phase');
      section.append(el('h3', 'phase-title', phaseTitle(phase)));
      const main = el('ul', 'groups');
      const notices = el('ul', 'groups');
      for (const g of sections.get(phase)) ((g.sev === 'NOTICE' && !g.rules) ? notices : main).append(groupItem(run, show, g, seen));
      if (main.children.length) section.append(main);
      if (notices.children.length) {
        const fold = el('details', 'notice-fold');
        const foldId = `${run.run}|${phase}`;
        fold.open = ui.openFolds.has(foldId);
        fold.addEventListener('toggle', () => (fold.open ? ui.openFolds.add(foldId) : ui.openFolds.delete(foldId)));
        fold.append(el('summary', null, `Notices ${notices.children.length}`), notices);
        section.append(fold);
      }
      nodes.push(section);
    }
    panel.replaceChildren(...nodes);
    if (focused) {
      const again = [...panel.querySelectorAll('[data-group]')].find((n) => n.dataset.group === focused);
      if (again) again.focus({ preventScroll: true });
    }
    setTimeout(() => ui.fresh.clear(), 2000);
  }
  function groupItem(run, show, g, seen) {
    const id = groupId(run, g);
    const li = el('li', 'group' + (ui.fresh.has(id) ? ' fresh' : ''));
    const head = el('button', 'group-head');
    head.type = 'button';
    head.dataset.group = id;
    head.setAttribute('aria-expanded', ui.expanded.has(id) ? 'true' : 'false');
    const sev = el('span', 'g-sev');
    sev.append(glyph(g.sev));
    if (!uncoded(g)) sev.append(el('span', 'sr-only', sevOf(g.sev).name));
    const body = el('span', 'g-body');
    const main = el('span', 'g-main');
    const meta = el('span', 'g-meta');
    if (g.n > 1 || g.sup) {
      const count = el('span', 'g-count', `×${g.n}${g.sup ? '+' : ''}`);
      if (g.sup) count.title = 'Further occurrences suppressed; actual total unknown';
      meta.append(count);
    }
    if (has(g.t)) meta.append(el('span', 'g-when', `First ${fmtTime(g.t)}`));
    const flags = el('span', 'g-flags');
    if ((g.sev !== 'NOTICE' || g.rules) && !seen.has(gkey(g))) flags.append(chip('New', 'new'));
    if (g.rules) flags.append(chip('Rule', 'critical', g.rules.join(', ')));
    if (g.base_new) flags.append(chip('Not in baseline', 'warning', `Absent from baseline run ${show.baseline}`));
    const msg = el('span', 'g-msg', g.msg);
    msg.title = g.msg;
    main.append(el('span', 'g-key', uncoded(g) ? sevOf(g.sev).name : g.key), msg);
    if (flags.children.length) meta.append(flags);
    body.append(main, meta);
    head.append(sev, body);
    head.addEventListener('click', () => toggleGroup(run, g, li, head));
    li.append(head);
    if (ui.expanded.has(id)) li.append(evidenceBox(run, g));
    return li;
  }
  function toggleGroup(run, g, li, head) {
    const id = groupId(run, g);
    if (ui.expanded.has(id)) {
      ui.expanded.delete(id);
      head.setAttribute('aria-expanded', 'false');
      const box = li.querySelector('.evidence');
      if (box) box.remove();
      return;
    }
    ui.expanded.set(id, g.e);
    head.setAttribute('aria-expanded', 'true');
    li.append(evidenceBox(run, g));
  }
  function openGroup(g) {
    const run = currentRun();
    if (!run) return;
    setTab('problems');
    const id = groupId(run, g);
    if (!ui.expanded.has(id)) ui.expanded.set(id, g.e);
    if (g.sev === 'NOTICE' && !g.rules) ui.openFolds.add(`${run.run}|${g.phase}`);
    renderProblems(run, true);
    const head = [...$('panel-problems').querySelectorAll('[data-group]')].find((n) => n.dataset.group === id);
    if (head) { head.focus({ preventScroll: true }); head.scrollIntoView({ block: 'center' }); }
  }
  async function getEvidence(id) {
    if (!ui.evidence.has(id)) ui.evidence.set(id, await api('/api/evidence', { id }));
    return ui.evidence.get(id);
  }
  function evidenceBox(run, g, focusWhich = null) {
    const box = el('div', 'evidence');
    box.append(el('p', 'panel-note', 'Loading evidence…'));
    const id = groupId(run, g);
    const which = ui.expanded.get(id) || g.e;
    getEvidence(which).then((e) => {
      const context = el('div', 'evidence-context');
      context.append(el('span', null, g.sev), el('span', null,
        `${g.n} printed${g.sup ? '; further occurrences suppressed, total unknown' : ''}`));
      context.append(el('span', null, has(g.t)
        ? `First ${fmtTime(g.t)}${has(g.pct) ? ` (${fmtPct(g.pct)})` : ''}` : 'Time not reported'));
      if (g.rules) context.append(el('span', null, `Rules: ${g.rules.join(', ')}`));
      if (g.base_new) {
        const show = ui.shows.get(run.run);
        if (show) context.append(el('span', null, `Absent from baseline ${show.data.baseline}`));
      }
      const meta = el('div', 'evidence-meta');
      let focusButton = null;
      if (g.last) {
        for (const [text, target] of [['First', g.e], ['Last', g.last]]) {
          const b = el('button', 'text-button', text);
          b.type = 'button';
          b.setAttribute('aria-pressed', target === which ? 'true' : 'false');
          b.addEventListener('click', () => { ui.expanded.set(id, target); box.replaceWith(evidenceBox(run, g, target)); });
          if (target === focusWhich) focusButton = b;
          meta.append(b);
        }
      }
      meta.append(el('code', 'loc', `${e.path}:${e.line}`));
      box.replaceChildren(context, meta, logView(e));
      if (focusButton && box.isConnected) focusButton.focus({ preventScroll: true });
    }).catch((err) => box.replaceChildren(el('p', 'panel-note', `Unable to load evidence: ${err.message}`)));
    return box;
  }
  function logLine(number, text, cls) {
    const row = el('span', 'log-line' + (cls ? ' ' + cls : ''));
    row.append(el('span', 'ln', number), el('span', 'tx', text));
    return row;
  }
  function logView(e) {
    const pre = el('pre', 'log');
    if (e.header) pre.append(logLine(e.header.line, e.header.raw, 'dim'));
    pre.append(logLine(e.line, e.raw, 'focus'));
    for (const c of e.cont || []) pre.append(logLine(c.line, c.raw));
    if (e.cont_more) pre.append(logLine('…', '', 'dim'));
    if (e.suppression) pre.append(logLine(e.suppression.line, e.suppression.raw, 'dim'));
    return pre;
  }

  // ---------------------------------------------------------------- measurements
  async function loadMeasurements(run, mode) {
    const gen = run.gen || 1;
    if (!ui.meas || ui.meas.run !== run.run || ui.meas.gen !== gen) {
      ui.meas = { run: run.run, gen, rows: [], older: false, total: 0, open: new Set() };
      mode = 'initial';
    }
    const m = ui.meas;
    if (mode === 'newer' && !m.rows.length) mode = 'initial';
    if (mode === 'initial') {
      const d = await api('/api/measurements', { run: run.run, tail: 50 });
      Object.assign(m, { rows: d.rows, older: Boolean(d.older), total: d.total });
    } else if (mode === 'earlier' && m.rows.length) {
      const d = await api('/api/measurements', { run: run.run, before: m.rows[0].e, limit: 50 });
      Object.assign(m, { rows: d.rows.concat(m.rows).slice(0, 500), older: Boolean(d.older), total: d.total });
    } else if (mode === 'newer') {
      const d = await api('/api/measurements', { run: run.run, after: m.rows[m.rows.length - 1].e, limit: 500 });
      if (m.rows.length + d.rows.length > 500) m.older = true;
      Object.assign(m, { rows: m.rows.concat(d.rows).slice(-500), total: d.total });
    }
    renderMeasurements(run);
  }
  function renderMeasurements(run) {
    const m = ui.meas;
    const active = document.activeElement;
    const focused = $('measure-body').contains(active) ? active.dataset.evidence : null;
    const rows = [];
    for (const r of m.rows) {
      const tr = el('tr', r.valid === 0 || r.issue ? 'flag' : '');
      if (has(r.frame)) {
        tr.append(el('td', null, r.frame), el('td', null, has(r.code) ? r.code : '—'), el('td', null, has(r.valid) ? r.valid : '—'));
      } else {
        const td = el('td', null, [r.issue, r.raw].filter(Boolean).join(': '));
        td.colSpan = 3;
        tr.append(td);
      }
      const cell = el('td');
      const open = m.open.has(r.e);
      const b = el('button', 'text-button', open ? 'Hide' : 'View');
      b.type = 'button';
      b.dataset.evidence = String(r.e);
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
      b.setAttribute('aria-label', `${open ? 'Hide' : 'Show'} evidence for ${has(r.frame) ? `frame ${r.frame}` : `record e${r.e}`}`);
      b.addEventListener('click', () => {
        if (m.open.has(r.e)) m.open.delete(r.e); else m.open.add(r.e);
        renderMeasurements(run);
      });
      cell.append(b);
      tr.append(cell);
      rows.push(tr);
      if (m.open.has(r.e)) {
        const er = el('tr', 'evidence-row');
        const td = el('td');
        td.colSpan = 4;
        getEvidence(r.e).then((e) => td.replaceChildren(logView(e))).catch((err) => td.replaceChildren(el('p', 'panel-note', err.message)));
        er.append(td);
        rows.push(er);
      }
    }
    $('measure-body').replaceChildren(...rows);
    if (focused) {
      const again = [...$('measure-body').querySelectorAll('[data-evidence]')].find((b) => b.dataset.evidence === focused);
      if (again) again.focus({ preventScroll: true });
    }
    $('measure-note').textContent = m.total ? `Latest ${m.rows.length} / ${m.total}` : 'No testbench records';
    $('measure-earlier').hidden = !m.older;
  }

  // ---------------------------------------------------------------- details
  async function loadDetails(run) {
    const key = `${run.state}|${run.gen || 1}|${run.last_problem || 0}`;
    const cached = ui.details.get(run.run);
    const now = Date.now();
    if (cached && cached.key === key && now - cached.at < 10000) return cached.data;
    const data = await api('/api/details', { run: run.run });
    ui.details.set(run.run, { key, at: now, data });
    return data;
  }
  function checkRow(state, mark, name, value) {
    const li = el('li', 'check');
    const icon = el('span', state, mark);
    icon.setAttribute('aria-hidden', 'true');
    li.append(icon, el('span', 'check-name', name), el('span', 'check-value', value));
    return li;
  }
  function renderDetails(d) {
    const items = [];
    const f = d.footer;
    items.push(f
      ? checkRow(f.errors ? 'state-bad' : 'state-ok', f.errors ? '✗' : '✓', 'Native footer', `${f.errors} errors, ${f.warnings} warnings, ${f.notices} notices`)
      : checkRow('state-gap', '…', 'Native footer', 'Not yet observed'));
    const names = { state: 'State file', log_status: 'logStatus', raw: 'Raw (head/tail)' };
    for (const c of d.checks || []) {
      const name = names[c.check] || c.check;
      if (c.status === 'not_checked') { items.push(checkRow('state-none', '—', name, 'Not configured')); continue; }
      if (c.status !== 'observed') { items.push(checkRow('state-gap', '!', name, c.detail || c.format || c.status)); continue; }
      if (c.check === 'state') {
        const bad = c.exit_code || ['failed', 'limit_exceeded', 'rejected', 'cancelled', 'killed'].includes(c.reported_status);
        items.push(checkRow(bad ? 'state-bad' : 'state-ok', bad ? '✗' : '✓', name,
          `${c.reported_status}, exit ${has(c.exit_code) ? c.exit_code : '—'}${c.reason ? `, ${c.reason}` : ''}`));
      } else if (c.check === 'log_status') {
        const ok = c.last_status === 'PASS';
        const bad = ['FAIL', 'FAILED', 'ERROR'].includes(c.last_status);
        items.push(checkRow(ok ? 'state-ok' : bad ? 'state-bad' : 'state-gap', ok ? '✓' : bad ? '✗' : '!', name,
          `${c.analysis || '—'} ${c.last_status || 'Not observed'}`));
      } else {
        const ok = c.end_marker && c.expected_stop_reached !== false;
        items.push(checkRow(ok ? 'state-ok' : 'state-gap', ok ? '✓' : '!', name,
          `END ${c.end_marker ? 'present' : 'missing'}, last ${fmtTime(c.last_saved_time_s)}${c.expected_stop_reached === false ? ', stop time not reached' : ''}, ${bytes(c.size_bytes)}`));
      }
    }
    if (has(d.size)) {
      const behind = (d.indexed || 0) < d.size;
      items.push(checkRow(behind ? 'state-gap' : 'state-ok', behind ? '…' : '✓', 'Indexed', `${bytes(d.indexed || 0)} / ${bytes(d.size)}`));
    }
    const totals = Object.entries(d.suppressed || {});
    if (totals.length) {
      items.push(checkRow('state-none', '·', 'Native suppression',
        totals.map(([k, v]) => `${k} ${v.toLocaleString('en-US')}`).join(', ')));
    }
    if (d.spectre) items.push(checkRow('state-none', '·', 'Spectre', d.spectre));
    const list = el('ul', 'checks');
    list.append(...items);
    const nodes = [list];
    if ((d.settings || []).length) {
      const table = el('table', 'data-table');
      const head = el('tr');
      for (const h of ['Parameter', 'Requested', 'Effective']) { const th = el('th', null, h); th.scope = 'col'; head.append(th); }
      table.createTHead().append(head);
      const body = table.createTBody();
      for (const s of d.settings) {
        const tr = el('tr', s.diff ? 'differs' : '');
        const eff = el('td', null, s.eff || '—');
        if (s.diff) eff.append(document.createTextNode(' '), chip('Differs', 'warning'));
        tr.append(el('td', null, s.name), el('td', null, s.req || '—'), eff);
        body.append(tr);
      }
      nodes.push(table);
    }
    $('panel-details').replaceChildren(...nodes);
  }

  // ---------------------------------------------------------------- panels and tabs
  function currentRun() { return ui.data ? ui.data.runs.find((r) => r.run === ui.selected) : null; }
  async function refreshPanel() {
    const run = currentRun();
    if (!run) return;
    try {
      if (ui.tab === 'measurements') {
        const gen = run.gen || 1;
        if (!ui.meas || ui.meas.run !== run.run || ui.meas.gen !== gen) await loadMeasurements(run, 'initial');
        else if ((run.frames ? run.frames.n : 0) !== ui.meas.total) await loadMeasurements(run, 'newer');
      } else if (ui.tab === 'details') {
        renderDetails(await loadDetails(run));
      }
    } catch (e) {
      if (ui.tab === 'measurements') $('measure-note').textContent = `Unable to load data: ${e.message}`;
      else $('panel-' + ui.tab).replaceChildren(el('p', 'panel-note', `Unable to load data: ${e.message}`));
    }
  }
  function setTab(name) {
    ui.tab = name;
    for (const tab of document.querySelectorAll('.tab')) {
      const on = tab.dataset.tab === name;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      $('panel-' + tab.dataset.tab).hidden = !on;
    }
    writeHash();
    refreshPanel();
  }
  function renderTabs(run) {
    const names = { problems: 'Problems', measurements: 'Measurements', details: 'Details' };
    const counts = { problems: groupsOf(run.run).length, measurements: run.frames ? run.frames.n : 0 };
    for (const tab of document.querySelectorAll('.tab')) {
      tab.replaceChildren(document.createTextNode(names[tab.dataset.tab]));
      if (has(counts[tab.dataset.tab])) tab.append(el('span', 'count-label', counts[tab.dataset.tab]));
    }
  }

  // ---------------------------------------------------------------- page
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    return { run: p.get('run'), tab: p.get('tab') };
  }
  function writeHash() {
    if (ui.selected) history.replaceState(null, '', `#${new URLSearchParams({ run: ui.selected, tab: ui.tab })}`);
  }
  function select(id) {
    if (ui.selected === id) return;
    ui.selected = id;
    ui.problemSig = '';
    ui.meas = null;
    writeHash();
    render();
    refreshPanel();
  }
  function updateTitle(runs) {
    const n = runs.filter((r) => level(r) !== 'none').length;
    document.title = n ? `(${n}) Spectre Log Inspector` : 'Spectre Log Inspector';
  }
  function render() {
    renderTopline();
    if (!ui.data) return;
    const runs = ui.data.runs;
    $('empty').hidden = runs.length > 0;
    $('run-view').hidden = runs.length === 0;
    if (!runs.length) { renderRail(runs); updateTitle(runs); return; }
    if (!runs.some((r) => r.run === ui.selected)) {
      ui.selected = railOrder(runs)[0].r.run;
      writeHash();
    }
    renderRail(runs);
    const run = currentRun();
    renderHead(run);
    drawTimeline($('timeline'), run, false);
    renderTabs(run);
    renderProblems(run, false);
    updateTitle(runs);
  }

  function setupControls() {
    const pause = $('pause');
    pause.addEventListener('click', () => {
      ui.paused = !ui.paused;
      pause.setAttribute('aria-pressed', ui.paused ? 'true' : 'false');
      pause.textContent = ui.paused ? 'Resume updates' : 'Pause updates';
    });
    const bell = $('notify');
    const sync = () => {
      bell.setAttribute('aria-pressed', ui.notify ? 'true' : 'false');
      bell.textContent = ui.notify ? 'Notifications on' : 'Notifications';
    };
    if (!('Notification' in window)) {
      bell.disabled = true;
      bell.title = 'This browser does not support notifications';
    } else {
      ui.notify = localStorage.getItem('simcheck.notify') === 'on' && Notification.permission === 'granted';
      sync();
      bell.addEventListener('click', async () => {
        if (ui.notify) {
          ui.notify = false;
        } else {
          const permission = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
          ui.notify = permission === 'granted';
          bell.title = ui.notify ? '' : 'Notifications are not allowed for this page';
        }
        localStorage.setItem('simcheck.notify', ui.notify ? 'on' : 'off');
        sync();
      });
    }
    $('ack').addEventListener('click', () => { const run = currentRun(); if (run) acknowledge(run); });
    $('run-select').addEventListener('change', (e) => select(e.target.value));
    $('measure-earlier').addEventListener('click', () => { const run = currentRun(); if (run) loadMeasurements(run, 'earlier'); });
    const tabs = [...document.querySelectorAll('.tab')];
    for (const tab of tabs) {
      tab.addEventListener('click', () => setTab(tab.dataset.tab));
      tab.addEventListener('keydown', (e) => {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        const i = tabs.indexOf(tab) + (e.key === 'ArrowRight' ? 1 : -1);
        const next = tabs[(i + tabs.length) % tabs.length];
        next.focus();
        setTab(next.dataset.tab);
      });
    }
    let resize = null;
    window.addEventListener('resize', () => {
      clearTimeout(resize);
      resize = setTimeout(() => { if (ui.data && currentRun()) render(); }, 150);
    });
  }

  const initial = readHash();
  ui.selected = initial.run;
  setupControls();
  setTab(['problems', 'measurements', 'details'].includes(initial.tab) ? initial.tab : 'problems');
  tick();
})();
