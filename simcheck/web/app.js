'use strict';
// Spectre 运行监视. Every log-derived string is inserted with textContent; nothing is
// parsed as HTML. The page only reads the local read-only API.
(() => {
  const SCHEMA = 3;
  const POLL_MS = 2000;
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const $ = (id) => document.getElementById(id);

  const STATUS = {
    complete: '已结束', failed: '失败', unknown: '状态未知', incomplete: '证据不完整',
    running: '运行中', indexing: '索引中', queued: '排队中', starting: '启动中',
    submitted: '已提交', waiting: '等待中',
  };
  const SEVERITY = {
    FATAL: { shape: '■', label: '致命', cls: 'critical' },
    ERROR: { shape: '■', label: '错误', cls: 'critical' },
    WARNING: { shape: '▲', label: '警告', cls: 'warning' },
    NOTICE: { shape: '●', label: '提示', cls: 'notice' },
    INFO: { shape: '◆', label: '测试台', cls: 'info' },
  };
  const ATTENTION = {
    failed: { text: '失败', cls: 'critical' },
    rule_hit: { text: '命中关注规则', cls: 'critical' },
    log_quiet: { text: '日志长时间未更新', cls: 'warning' },
    collector_error: { text: '采集出错', cls: 'warning' },
    source_error: { text: '日志读取失败', cls: 'warning' },
  };
  const LEVEL_RANK = { critical: 0, warning: 1, new: 2, none: 3 };
  const PREFIXES = [[1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n'], [1e-12, 'p'], [1e-15, 'f']];

  const ui = {
    data: null, error: null, selected: null, tab: 'problems', paused: false, busy: false,
    groups: new Map(), rows: new Map(), previous: new Map(), evidence: new Map(),
    expanded: new Map(), openFolds: new Set(), fresh: new Set(), details: new Map(),
    meas: null, problemSig: '', collectorAlive: null, notify: false,
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
  function shape(cls, glyph) {
    const s = el('span', 'shape sev-' + cls, glyph);
    s.setAttribute('aria-hidden', 'true');
    return s;
  }
  function chip(text, cls) { return el('span', 'chip' + (cls ? ' ' + cls : ''), text); }
  function fmtTime(s) {
    if (s === null || s === undefined) return '—';
    if (s === 0) return '0 s';
    for (const [scale, prefix] of PREFIXES) {
      // Six significant digits: as many as Spectre prints, never more.
      if (Math.abs(s) >= scale * 0.9999995 || scale === 1e-15) return `${+(s / scale).toPrecision(6)} ${prefix}s`;
    }
    return `${s} s`;
  }
  function fmtPct(f) {
    if (f === null || f === undefined) return '—';
    const p = f * 100;
    if (p >= 10) return `${p.toFixed(1)}%`;
    if (p >= 1) return `${p.toFixed(2)}%`;
    if (p >= 0.001) return `${p.toFixed(3)}%`;
    return '<0.001%';
  }
  function fmtAge(seconds) {
    if (seconds === null || seconds === undefined) return '—';
    const s = Math.max(0, seconds);
    if (s < 90) return `${Math.round(s)} 秒`;
    if (s < 5400) return `${Math.round(s / 60)} 分钟`;
    if (s < 172800) return `${(s / 3600).toFixed(1)} 小时`;
    return `${Math.round(s / 86400)} 天`;
  }
  function since(epoch) { return epoch ? fmtAge(Date.now() / 1000 - epoch) + '前' : '—'; }
  function stamp(epoch) {
    if (!epoch) return '—';
    return new Date(epoch * 1000).toLocaleString('zh-CN', {
      hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  }
  function bytes(n) {
    if (n === null || n === undefined) return '—';
    if (n < 1024) return `${n} B`;
    if (n < 1048576) return `${(n / 1024).toFixed(1)} KiB`;
    return `${(n / 1048576).toFixed(1)} MiB`;
  }
  function clamp(f) { return f === null || f === undefined ? null : Math.min(1, Math.max(0, f)); }
  function gkey(g) { return `${g.problem_key}|${g.severity}`; }
  function basename(path) { return String(path || '').split(/[\\/]/).pop(); }
  function severityOf(name) { return SEVERITY[name] || SEVERITY.INFO; }
  function announce(text) { $('live').textContent = text; }

  async function api(path, params) {
    const url = params ? `${path}?${new URLSearchParams(params)}` : path;
    const response = await fetch(url, { cache: 'no-store' });
    let body = null;
    try { body = await response.json(); } catch (_) { body = null; }
    if (!response.ok) throw new Error(body && body.error ? body.error.message : `HTTP ${response.status}`);
    return body;
  }

  // ---------------------------------------------------------------- acknowledgement
  // Keys the person has already seen, per run, kept in this browser only.
  function ackKeys(run) {
    try {
      const stored = JSON.parse(localStorage.getItem('simcheck.ack.' + run) || 'null');
      return stored ? new Set(stored.keys) : null;
    } catch (_) { return null; }
  }
  function saveAck(run, keys) { localStorage.setItem('simcheck.ack.' + run, JSON.stringify({ keys: [...keys] })); }
  function newGroups(run) {
    const cache = ui.groups.get(run.run_id);
    const seen = ackKeys(run.run_id);
    if (!cache || !seen) return [];
    return cache.list.filter((g) => g.severity !== 'NOTICE' && !seen.has(gkey(g)));
  }
  function acknowledge(run) {
    const cache = ui.groups.get(run.run_id);
    const seen = ackKeys(run.run_id) || new Set();
    if (cache) for (const g of cache.list) seen.add(gkey(g));
    saveAck(run.run_id, seen);
    ui.problemSig = '';
    render();
  }

  // ---------------------------------------------------------------- data flow
  async function syncGroups(runs) {
    const fresh = [];
    await Promise.all(runs.map(async (run) => {
      const sig = `${run.generation}:${run.problems.last_problem_id}:${run.problems.group_count}`;
      const cached = ui.groups.get(run.run_id);
      if (cached && cached.sig === sig) return;
      const data = await api('/api/problems', { run: run.run_id, limit: 500 });
      const before = cached ? new Set(cached.list.map(gkey)) : null;
      ui.groups.set(run.run_id, { sig, list: data.problems });
      if (!ackKeys(run.run_id)) saveAck(run.run_id, new Set(data.problems.map(gkey)));
      if (!before) return;
      for (const g of data.problems) {
        if (!before.has(gkey(g))) {
          ui.fresh.add(`${run.run_id}|${run.generation}|${gkey(g)}`);
          if (g.severity !== 'NOTICE') fresh.push({ run: run.run_id, g });
        }
      }
    }));
    return fresh;
  }

  function detectChanges(data, fresh) {
    const events = [];
    const ruleKeys = new Set();
    for (const run of data.runs) {
      const prev = ui.previous.get(run.run_id);
      if (prev) {
        if (prev.state.status !== run.state.status && ['failed', 'complete', 'incomplete'].includes(run.state.status)) {
          events.push({ run: run.run_id, text: `状态变为「${STATUS[run.state.status] || run.state.status}」` });
        }
        for (const h of run.rule_hits) {
          if (!prev.rule_hits.some((p) => p.rule === h.rule && p.problem_key === h.problem_key)) {
            ruleKeys.add(`${run.run_id}|${h.problem_key}`);
            events.push({ run: run.run_id, text: `命中规则「${h.rule}」：${h.problem_key}，首次 ${fmtTime(h.first_sim_time_s)}（${fmtPct(h.first_fraction)}）` });
          }
        }
        for (const flag of ['log_quiet', 'collector_error', 'source_error']) {
          if (run.attention.includes(flag) && !prev.attention.includes(flag)) {
            events.push({ run: run.run_id, text: flag === 'log_quiet' ? `日志 ${fmtAge(run.state.quiet_for_s)}未更新，运行尚未结束` : ATTENTION[flag].text });
          }
        }
      }
      ui.previous.set(run.run_id, run);
    }
    for (const { run, g } of fresh) {
      if (ruleKeys.has(`${run}|${g.problem_key}`)) continue;
      const when = g.first_sim_time_s === null || g.first_sim_time_s === undefined ? '' : `，首次 ${fmtTime(g.first_sim_time_s)}`;
      events.push({ run, text: `新问题 ${g.code || g.problem_key}（${g.severity}）${when}` });
    }
    if (ui.collectorAlive === true && !data.collector.alive) events.push({ run: null, text: '采集器停止心跳，页面数据不再更新' });
    ui.collectorAlive = data.collector.alive;
    // One notification per run per refresh: a failure usually arrives as several lines at once.
    const byRun = new Map();
    for (const e of events) {
      if (!byRun.has(e.run)) byRun.set(e.run, []);
      byRun.get(e.run).push(e.text);
    }
    for (const [run, texts] of byRun) notify(run ? `Spectre ${run}` : 'Spectre 运行监视', texts.join('；'));
    if (events.length) announce(events.map((e) => (e.run ? e.run + '：' : '') + e.text).join('；'));
  }

  function notify(title, body) {
    if (!ui.notify || !('Notification' in window) || Notification.permission !== 'granted') return;
    try { new Notification(title, { body }); } catch (_) { /* platform without page notifications */ }
  }

  async function refresh() {
    if (ui.busy) return;
    ui.busy = true;
    try {
      const data = await api('/api/runs');
      if (data.schema_version !== SCHEMA) {
        throw new Error(`查看器接口版本不匹配（schema ${data.schema_version}，页面需要 ${SCHEMA}）。请重启 simcheck 查看器。`);
      }
      ui.data = data;
      ui.error = null;
      const fresh = await syncGroups(data.runs);
      detectChanges(data, fresh);
      render();
      await refreshPanel();
    } catch (e) {
      ui.error = e instanceof TypeError
        ? '连接不到查看器进程，它可能已经退出。重新运行 python -m simcheck run 清单.json 后，本页会自动恢复。'
        : e.message;
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
    if (ui.error) {
      box.replaceChildren(shape('critical', '■'), document.createTextNode('无法读取监视数据'));
      banner.textContent = ui.error;
      banner.classList.add('critical');
      banner.hidden = false;
      return;
    }
    if (!ui.data) return;
    const c = ui.data.collector;
    if (c.alive) {
      box.replaceChildren(document.createTextNode(`采集中：心跳 ${fmtAge(c.heartbeat_age_s)}前，版本 ${c.version}，PID ${c.pid}`));
      if (c.version !== ui.data.version) {
        banner.textContent = `采集进程版本 ${c.version} 与查看器版本 ${ui.data.version} 不同：可能有旧进程仍在写同一个数据库。`;
        banner.hidden = false;
      }
    } else {
      box.replaceChildren(shape('warning', '▲'), document.createTextNode(
        c.heartbeat_age_s === null ? '没有采集进程' : `采集器离线，最后心跳 ${fmtAge(c.heartbeat_age_s)}前`));
      const last = Math.max(0, ...ui.data.runs.map((r) => r.state.observed_epoch || 0));
      banner.textContent = `采集器没有在运行，页面上的数据停在 ${last ? stamp(last) : '未知时间'}。`
        + '用 python -m simcheck run 清单.json（或 watch）启动采集后会自动恢复。';
      banner.hidden = false;
    }
  }

  // ---------------------------------------------------------------- run list
  function level(run) {
    const a = run.attention;
    if (a.includes('failed') || a.includes('rule_hit')) return 'critical';
    if (a.length) return 'warning';
    return newGroups(run).length ? 'new' : 'none';
  }
  function stateText(run) {
    const a = run.attention;
    if (a.includes('failed')) return STATUS.failed;
    if (a.includes('rule_hit')) return '命中规则';
    if (a.includes('log_quiet')) return `日志 ${fmtAge(run.state.quiet_for_s)}未更新`;
    if (a.includes('collector_error')) return '采集出错';
    return STATUS[run.state.status] || run.state.status;
  }
  function rowFor(id) {
    let row = ui.rows.get(id);
    if (row) return row;
    const li = el('li');
    const button = el('button', 'run-row');
    button.type = 'button';
    button.dataset.run = id;
    const name = el('span', 'run-name');
    const state = el('span', 'run-state');
    const counts = el('span', 'run-counts');
    const meta = el('span', 'run-meta');
    const mini = svg('svg', { 'aria-hidden': 'true', focusable: 'false' }, 'mini');
    button.append(name, state, counts, meta, mini);
    button.addEventListener('click', () => select(id));
    li.append(button);
    row = { li, button, name, state, counts, meta, mini };
    ui.rows.set(id, row);
    return row;
  }
  function countSpan(cls, glyph, label, n) {
    const span = el('span');
    span.append(shape(cls, glyph), el('span', 'sr-only', label), document.createTextNode(String(n)));
    return span;
  }
  function updateRow(row, run, lvl) {
    row.button.className = `run-row level-${lvl}`;
    row.button.setAttribute('aria-current', run.run_id === ui.selected ? 'true' : 'false');
    const fresh = newGroups(run).length;
    row.name.replaceChildren(document.createTextNode(run.run_id));
    if (fresh) row.name.append(el('span', 'badge-new', `新 ${fresh}`));
    row.state.textContent = stateText(run);
    const sev = run.problems.by_severity;
    row.counts.replaceChildren(
      countSpan('critical', '■', '错误', (sev.ERROR || 0) + (sev.FATAL || 0)),
      countSpan('warning', '▲', '警告', sev.WARNING || 0),
      countSpan('notice', '●', '提示', sev.NOTICE || 0));
    row.meta.textContent = run.state.source_mtime_epoch ? `日志 ${since(run.state.source_mtime_epoch)}` : '日志未读到';
  }
  function railOrder(runs) {
    // Running runs first: stopping those is what saves simulation time.
    return runs.map((r) => ({ r, lvl: level(r) })).sort((a, b) =>
      LEVEL_RANK[a.lvl] - LEVEL_RANK[b.lvl]
      || Number(a.r.state.ended) - Number(b.r.state.ended)
      || Number(!a.r.attention.includes('failed')) - Number(!b.r.attention.includes('failed'))
      || a.r.run_id.localeCompare(b.r.run_id));
  }
  function place(list, items) {
    items.forEach(({ r, lvl }, i) => {
      const row = rowFor(r.run_id);
      updateRow(row, r, lvl);
      if (list.children[i] !== row.li) list.insertBefore(row.li, list.children[i] || null);
    });
    while (list.children.length > items.length) list.lastElementChild.remove();
  }
  function renderRail(runs) {
    const active = document.activeElement;
    const ordered = railOrder(runs);
    const attention = ordered.filter((x) => x.lvl !== 'none');
    const others = ordered.filter((x) => x.lvl === 'none');
    $('rail-count').textContent = `${runs.length} 个运行，${attention.length} 个需要关注`;
    place($('attention-list'), attention);
    place($('other-list'), others);
    $('attention-group').hidden = !attention.length;
    $('other-group').hidden = !others.length;
    for (const id of [...ui.rows.keys()]) if (!runs.some((r) => r.run_id === id)) { ui.rows.get(id).li.remove(); ui.rows.delete(id); }
    for (const { r } of ordered) drawTimeline(ui.rows.get(r.run_id).mini, r, true);
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
    const cache = ui.groups.get(run.run_id);
    const groups = cache ? cache.list : [];
    const width = Math.max(target.clientWidth || 0, mini ? 120 : 320);
    const height = mini ? 12 : 74;
    // Redraw only when something drawn changed; rebuilding on every poll would drop keyboard focus.
    const sig = JSON.stringify([width, run.state.stop_time_s, run.state.progress_at_least, run.state.ended,
      run.state.analysis, cache ? cache.sig : null, run.rule_hits.map((h) => `${h.problem_key}|${h.severity}`).sort()]);
    if (target.dataset.sig === sig) return Number(target.dataset.count);
    target.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const pad = mini ? 4 : 10;
    const x0 = pad;
    const span = width - 2 * pad;
    const trackY = mini ? 5 : 38;
    const trackH = mini ? 3 : 6;
    const stop = run.state.stop_time_s;
    const ended = run.state.ended ? ' ended' : '';
    const parts = [];
    if (!mini) {
      for (let i = 0; i <= 10; i += 1) {
        const x = x0 + (span * i) / 10;
        parts.push(svg('line', { x1: x, x2: x, y1: trackY - 6, y2: trackY + trackH + 4 }, i % 5 === 0 ? 'tick' : 'grid'));
      }
    }
    parts.push(svg('rect', { x: x0, y: trackY, width: span, height: trackH, rx: trackH / 2 }, 'track' + ended));
    const f = clamp(run.state.progress_at_least);
    if (stop && f !== null) {
      parts.push(svg('rect', { x: x0, y: trackY, width: Math.max(trackH, span * f), height: trackH, rx: trackH / 2 }, 'fill' + ended));
    }
    if (!mini && stop) {
      const y = trackY + trackH + 20;
      [[x0, '0', 'start'], [x0 + span / 2, fmtTime(stop / 2), 'middle'], [x0 + span, fmtTime(stop), 'end']].forEach(([x, text, anchor]) => {
        const t = svg('text', { x, y, 'text-anchor': anchor }, 'axis-label');
        t.textContent = text;
        parts.push(t);
      });
    }
    const hits = new Set(run.rule_hits.map((h) => `${h.problem_key}|${h.severity}`));
    const marks = groups
      .filter((g) => g.first_fraction !== null && g.first_fraction !== undefined && g.phase === run.state.analysis
        && (g.severity !== 'NOTICE' || hits.has(gkey(g))))
      .map((g) => ({ g, x: x0 + span * clamp(g.first_fraction), hit: hits.has(gkey(g)), cls: severityOf(g.severity).cls }))
      .sort((a, b) => a.x - b.x || a.g.first_evidence_id - b.g.first_evidence_id);
    // Markers closer than the hit target merge into one cluster: early problems pile up
    // at the left edge, and "6 groups, earliest 60 ns" is the honest way to say so.
    const rank = { critical: 0, warning: 1, info: 2, notice: 3 };
    const clusters = [];
    for (const m of marks) {
      const last = clusters[clusters.length - 1];
      if (last && m.x - last.x <= (mini ? 4 : 14)) last.members.push(m);
      else clusters.push({ x: m.x, members: [m] });
    }
    const y = mini ? trackY + trackH / 2 : trackY - 14;
    let labelEnd = -Infinity;
    for (const c of clusters) {
      const lead = c.members.reduce((a, b) => (rank[b.cls] < rank[a.cls] ? b : a));
      const group = svg('g', {}, `marker sev-${lead.cls}`);
      if (!mini) {
        const names = c.members.map((m) => m.g.code || m.g.problem_key.replace(/^NOTICE:/, ''));
        const earliest = c.members.reduce((a, b) => (b.g.first_sim_time_s < a.g.first_sim_time_s ? b : a)).g;
        group.setAttribute('tabindex', '0');
        group.setAttribute('role', 'button');
        group.setAttribute('data-key', gkey(earliest));
        group.setAttribute('aria-label', `${names.join('、')}，最早首次出现于 ${fmtTime(earliest.first_sim_time_s)}`);
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
          const text = `${c.members.length} 组，最早 ${fmtTime(earliest.first_sim_time_s)}（${fmtPct(earliest.first_fraction)}）`;
          const label = svg('text', { x: Math.max(0, c.x - 4), y: y - 13 }, 'more-label');
          label.textContent = text;
          parts.push(label);
          labelEnd = c.x + [...text].reduce((w, ch) => w + (ch.charCodeAt(0) > 0x2e7f ? 12 : 6.5), 0);
        }
      }
      group.append(markerShape(lead.cls, c.x, y, mini ? 5 : 9));
      parts.push(group);
    }
    const focused = target.contains(document.activeElement) ? document.activeElement.getAttribute('data-key') : null;
    target.replaceChildren(...parts);
    target.dataset.sig = sig;
    target.dataset.count = String(marks.length);
    if (focused) {
      const again = [...target.querySelectorAll('.marker')].find((n) => n.getAttribute('data-key') === focused);
      if (again) again.focus({ preventScroll: true });
    }
    return marks.length;
  }
  function showTip(anchor, groups) {
    const tip = $('tooltip');
    const lines = [];
    for (const g of groups.slice(0, 6)) {
      const sev = severityOf(g.severity);
      lines.push(el('strong', null, g.code || g.problem_key.replace(/^NOTICE:/, '')),
        el('span', null, `${sev.label}（${g.severity}），已打印 ${g.printed_count} 次${g.suppressed_after ? '，之后被抑制' : ''}；首次 ${fmtTime(g.first_sim_time_s)}（${fmtPct(g.first_fraction)}）`));
    }
    if (groups.length > 6) lines.push(el('span', null, `另有 ${groups.length - 6} 组，见下方问题列表`));
    tip.replaceChildren(...lines);
    tip.hidden = false;
    const r = anchor.getBoundingClientRect();
    const left = Math.min(window.innerWidth - tip.offsetWidth - 8, Math.max(8, r.left + r.width / 2 - tip.offsetWidth / 2));
    const above = r.top - tip.offsetHeight - 8;
    tip.style.left = `${left}px`;
    tip.style.top = `${above > 8 ? above : r.bottom + 8}px`;
  }
  function hideTip() { $('tooltip').hidden = true; }

  // ---------------------------------------------------------------- run detail
  function fact(label, value, note) {
    const div = el('div');
    const dd = el('dd', null, value);
    if (note) dd.append(document.createTextNode(' '), el('small', null, note));
    div.append(el('dt', null, label), dd);
    return div;
  }
  function renderHead(run) {
    $('run-title').textContent = run.run_id;
    const status = STATUS[run.state.status] || run.state.status;
    $('run-status').textContent = run.generation > 1 ? `${status}（第 ${run.generation} 次启动）` : status;
    const chips = [];
    for (const flag of run.attention) {
      if (flag === 'failed') continue;
      const info = ATTENTION[flag];
      const text = flag === 'log_quiet' ? `日志 ${fmtAge(run.state.quiet_for_s)}未更新，运行尚未结束` : info.text;
      const c = chip('', info.cls);
      c.append(shape(info.cls, info.cls === 'critical' ? '■' : '▲'), document.createTextNode(text));
      chips.push(c);
    }
    const fresh = newGroups(run).length;
    if (fresh) chips.push(chip(`新出现 ${fresh} 组`, 'new'));
    $('run-attention').replaceChildren(...chips);
    $('ack').hidden = !fresh;
    const s = run.state;
    const facts = [fact('分析', s.analysis || '日志未报告')];
    if (s.stop_time_s) {
      facts.push(fact('仿真时间', `至少 ${fmtTime(s.last_logged_time_s)} / ${fmtTime(s.stop_time_s)}`,
        s.progress_at_least === null ? '' : `（${fmtPct(s.progress_at_least)}）`));
    } else {
      facts.push(fact('仿真时间', s.last_logged_time_s === null ? '日志未报告' : fmtTime(s.last_logged_time_s)));
    }
    const latest = run.measurements.latest;
    facts.push(fact('测量记录', `${run.measurements.records} 条`,
      latest && latest.frame !== undefined ? `最新帧 ${latest.frame}，码字 ${latest.code_value}` : ''));
    const sev = run.problems.by_severity;
    facts.push(fact('已打印问题', `${run.problems.printed_count} 条，${run.problems.group_count} 组`,
      `错误 ${(sev.ERROR || 0) + (sev.FATAL || 0)}，警告 ${sev.WARNING || 0}，提示 ${sev.NOTICE || 0}`));
    facts.push(fact('日志最后修改', since(s.source_mtime_epoch), stamp(s.source_mtime_epoch)));
    facts.push(fact('最近一次采集', since(s.observed_epoch), s.backlog ? '索引尚未追平' : ''));
    if (s.collector_error) facts.push(fact('采集错误', s.collector_error, stamp(s.collector_error_epoch)));
    if (s.error) facts.push(fact('日志读取错误', s.error));
    $('facts').replaceChildren(...facts);
  }
  function renderAxis(run) {
    const count = drawTimeline($('timeline-svg'), run, false);
    const s = run.state;
    const cap = $('timeline-caption');
    if (!s.stop_time_s) {
      cap.textContent = '日志尚未给出瞬态分析的结束时间，无法按仿真时间定位问题。';
      return;
    }
    const progress = s.progress_at_least === null ? '' : `日志已记录到 ${fmtTime(s.last_logged_time_s)}（至少 ${fmtPct(s.progress_at_least)}）`;
    const marks = count ? `标出 ${count} 组问题首次出现的位置` : '本次分析中还没有带时间的警告或错误';
    cap.textContent = `横轴是分析 ${s.analysis} 的仿真时间 0 → ${fmtTime(s.stop_time_s)}。${progress ? progress + '；' : ''}${marks}。`;
  }
  function renderWatch(run) {
    const box = $('watch');
    const blocks = [];
    if (run.rule_hits.length) {
      const block = el('div', 'watch-block');
      block.append(el('h3', null, '关注规则命中'));
      const list = el('ul');
      const byRule = new Map();
      for (const h of run.rule_hits) {
        if (!byRule.has(h.rule)) byRule.set(h.rule, []);
        byRule.get(h.rule).push(h);
      }
      const cache = ui.groups.get(run.run_id);
      const label = (h) => {
        if (!h.problem_key.includes(':') || h.problem_key.startsWith('TB:')) return h.problem_key;
        // Uncoded messages: show the first printed text, not the number-masked group key.
        const g = cache && cache.list.find((x) => x.problem_key === h.problem_key && x.severity === h.severity);
        return g ? g.summary : h.problem_key;
      };
      for (const [rule, hits] of byRule) {
        const first = hits.reduce((a, b) => (b.first_sim_time_s !== null && (a.first_sim_time_s === null || b.first_sim_time_s < a.first_sim_time_s) ? b : a));
        const li = el('li');
        li.append(document.createTextNode(`「${rule}」：`), el('span', 'keys', hits.map(label).join('、')));
        if (first.first_sim_time_s !== null) li.append(document.createTextNode(`，最早出现在 ${fmtTime(first.first_sim_time_s)}（${fmtPct(first.first_fraction)}）`));
        list.append(li);
      }
      block.append(list);
      blocks.push(block);
    }
    if (run.baseline) {
      const serious = run.baseline.keys_not_in_baseline.filter((k) => k.severity !== 'NOTICE');
      const block = el('div', 'watch-block');
      block.append(el('h3', null, `与参考运行 ${run.baseline.run_id} 对比`));
      block.append(el('p', null, serious.length
        ? `参考运行（${STATUS[run.baseline.status] || run.baseline.status}）里没有出现过的警告或错误：`
        : `没有参考运行里未出现过的警告或错误（参考运行状态：${STATUS[run.baseline.status] || run.baseline.status}）。`));
      if (serious.length) block.append(el('p', 'keys', serious.map((k) => k.problem_key).join('、')));
      blocks.push(block);
    }
    box.replaceChildren(...blocks);
  }

  // ---------------------------------------------------------------- problems
  function groupId(run, g) { return `${run.run_id}|${run.generation}|${gkey(g)}`; }
  function phaseTitle(phase) { return phase === 'setup' ? '读入与初始化' : `分析 ${phase}`; }
  function renderProblems(run, force) {
    const cache = ui.groups.get(run.run_id);
    const list = cache ? cache.list : [];
    const seen = ackKeys(run.run_id) || new Set();
    const rules = new Map();
    for (const h of run.rule_hits) {
      const k = `${h.problem_key}|${h.severity}`;
      if (!rules.has(k)) rules.set(k, []);
      rules.get(k).push(h.rule);
    }
    const missing = new Set((run.baseline ? run.baseline.keys_not_in_baseline : []).map((k) => `${k.problem_key}|${k.severity}`));
    const sig = JSON.stringify([run.run_id, run.generation, cache && cache.sig, [...seen].sort(), [...rules.keys()], [...missing]]);
    if (!force && sig === ui.problemSig) return;
    ui.problemSig = sig;
    const panel = $('panel-problems');
    const focused = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.group : null;
    const sections = new Map();
    for (const g of list) {
      const phase = g.category === 'testbench' ? 'testbench' : g.phase;
      if (!sections.has(phase)) sections.set(phase, []);
      sections.get(phase).push(g);
    }
    const order = [...sections.keys()].sort((a, b) => {
      const rank = (p) => (p === 'testbench' ? 1 : p === 'setup' ? 2 : 0);
      return rank(a) - rank(b) || sections.get(a)[0].first_evidence_id - sections.get(b)[0].first_evidence_id;
    });
    const nodes = [];
    if (!list.length) nodes.push(el('p', 'panel-note', '当前已索引的日志里没有警告、错误、提示或测试台问题记录。'));
    for (const phase of order) {
      const groups = sections.get(phase);
      const section = el('section', 'phase');
      const title = el('h3', 'phase-title', phase === 'testbench' ? '测试台报告' : phaseTitle(phase));
      title.append(el('small', null, `${groups.length} 组`));
      section.append(title);
      const main = el('ul', 'groups');
      const notices = el('ul', 'groups');
      for (const g of groups) (g.severity === 'NOTICE' ? notices : main).append(groupItem(run, g, seen, rules, missing));
      if (main.children.length) section.append(main);
      if (notices.children.length) {
        const fold = el('details', 'notice-fold');
        const foldId = `${run.run_id}|${phase}`;
        fold.open = ui.openFolds.has(foldId);
        fold.addEventListener('toggle', () => (fold.open ? ui.openFolds.add(foldId) : ui.openFolds.delete(foldId)));
        fold.append(el('summary', null, `提示（NOTICE）${notices.children.length} 组：Spectre 原生提示，不升级为告警`), notices);
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
  function groupItem(run, g, seen, rules, missing) {
    const id = groupId(run, g);
    const sev = severityOf(g.severity);
    const li = el('li', 'group' + (ui.fresh.has(id) ? ' fresh' : ''));
    const head = el('button', 'group-head');
    head.type = 'button';
    head.dataset.group = id;
    head.setAttribute('aria-expanded', ui.expanded.has(id) ? 'true' : 'false');
    const sevBox = el('span', 'sev');
    sevBox.append(shape(sev.cls, sev.shape), document.createTextNode(g.severity));
    const own = { premature_termination: '分析提前终止', line_size_limit: '超长行被截断' };
    const key = el('span', 'key', g.code || own[g.problem_key]
      || (g.category === 'testbench' ? g.problem_key : '无编号'));
    const summary = el('span', 'group-summary', g.summary);
    summary.title = g.message || g.summary;
    const when = el('span', 'group-when', g.first_sim_time_s === null || g.first_sim_time_s === undefined
      ? (g.phase === 'setup' ? '读入阶段' : '无仿真时间')
      : `首次 ${fmtTime(g.first_sim_time_s)}${g.first_fraction === null ? '' : `（${fmtPct(g.first_fraction)}）`}`);
    const tags = el('span', 'group-tags');
    tags.append(el('span', null, `已打印 ${g.printed_count} 次`));
    if (g.severity !== 'NOTICE' && !seen.has(gkey(g))) tags.append(chip('新出现', 'new'));
    if (g.suppressed_after) tags.append(chip('之后被抑制，实际次数未知'));
    for (const rule of rules.get(gkey(g)) || []) tags.append(chip(`规则：${rule}`, 'critical'));
    if (missing.has(gkey(g)) && g.severity !== 'NOTICE') tags.append(chip(`参考运行 ${run.baseline.run_id} 中没有`, 'warning'));
    head.append(sevBox, key, summary, when, tags);
    head.addEventListener('click', () => toggleGroup(run, g, li, head));
    li.append(head);
    if (ui.expanded.has(id)) li.append(evidenceBox(run, g, li));
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
    ui.expanded.set(id, g.first_evidence_id);
    head.setAttribute('aria-expanded', 'true');
    li.append(evidenceBox(run, g, li));
  }
  function openGroup(g) {
    const run = currentRun();
    if (!run) return;
    setTab('problems');
    const id = groupId(run, g);
    if (!ui.expanded.has(id)) ui.expanded.set(id, g.first_evidence_id);
    if (g.severity === 'NOTICE') ui.openFolds.add(`${run.run_id}|${g.category === 'testbench' ? 'testbench' : g.phase}`);
    renderProblems(run, true);
    const head = [...$('panel-problems').querySelectorAll('[data-group]')].find((n) => n.dataset.group === id);
    if (head) { head.focus({ preventScroll: true }); head.scrollIntoView({ block: 'center' }); }
  }
  async function getEvidence(id) {
    if (!ui.evidence.has(id)) ui.evidence.set(id, (await api('/api/evidence', { id })).evidence);
    return ui.evidence.get(id);
  }
  function evidenceBox(run, g, li) {
    const box = el('div', 'evidence');
    box.append(el('p', 'panel-note', '正在读取原文…'));
    const id = groupId(run, g);
    const which = ui.expanded.get(id) || g.first_evidence_id;
    getEvidence(which).then((e) => {
      const meta = el('div', 'evidence-meta');
      if (g.first_evidence_id !== g.last_evidence_id) {
        for (const [label, target] of [['首条', g.first_evidence_id], ['末条', g.last_evidence_id]]) {
          const b = el('button', 'quiet-button', label);
          b.type = 'button';
          b.setAttribute('aria-pressed', target === which ? 'true' : 'false');
          b.addEventListener('click', () => {
            ui.expanded.set(id, target);
            box.replaceWith(evidenceBox(run, g, li));
          });
          meta.append(b);
        }
      }
      meta.append(el('span', null, `${basename(e.source_path)} 第 ${e.line} 行，字节偏移 ${e.byte_offset}`),
        el('span', null, `首次采集 ${stamp(e.observed_epoch)}`));
      box.replaceChildren(meta, logView(e), observedList(e));
    }).catch((err) => box.replaceChildren(el('p', 'panel-note', `原文读取失败：${err.message}`)));
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
    for (const c of e.continuation) pre.append(logLine(c.line, c.raw));
    if (e.continuation_limited) pre.append(logLine('…', '续行较多，只显示前 20 行', 'dim'));
    if (e.suppression) pre.append(logLine(e.suppression.line, e.suppression.raw, 'dim'));
    return pre;
  }
  function observedList(e) {
    const o = e.observed;
    const dl = el('dl', 'observed');
    const add = (k, v) => { if (v !== undefined && v !== null && v !== '') dl.append(el('dt', null, k), el('dd', null, v)); };
    add('实例', o.instance);
    if (o.terminal) add('端对', o.terminal);
    if (o.measured) add('测得', o.measured.raw);
    if (o.limit) add('限值', o.limit.raw);
    add('仿真时间', o.sim_time_s === null || o.sim_time_s === undefined ? (e.header ? '头行未给出时间' : undefined) : fmtTime(o.sim_time_s));
    if (o.severity_source === 'header') add('级别来源', '无编号消息，级别取自头行');
    add('说明', o.limitation);
    return dl;
  }

  // ---------------------------------------------------------------- measurements
  async function loadMeasurements(run, mode) {
    if (!ui.meas || ui.meas.run !== run.run_id || ui.meas.generation !== run.generation) {
      ui.meas = { run: run.run_id, generation: run.generation, rows: [], exhausted: false, records: -1, open: new Set() };
      mode = 'initial';
    }
    const m = ui.meas;
    const params = { run: run.run_id, generation: run.generation };
    if (mode === 'initial') {
      m.rows = (await api('/api/measurements', { ...params, tail: 50 })).measurements;
      m.exhausted = m.rows.length < 50;
    } else if (mode === 'earlier' && m.rows.length) {
      const older = (await api('/api/measurements', { ...params, before: m.rows[0].evidence_id, limit: 50 })).measurements;
      m.rows = older.concat(m.rows).slice(0, 500);
      m.exhausted = older.length < 50;
    } else if (mode === 'newer') {
      const after = m.rows.length ? m.rows[m.rows.length - 1].evidence_id : 0;
      const newer = (await api('/api/measurements', { ...params, after, limit: 500 })).measurements;
      m.rows = m.rows.concat(newer).slice(-500);
    }
    m.records = run.measurements.records;
    renderMeasurements(run);
  }
  function renderMeasurements(run) {
    const m = ui.meas;
    const body = $('measure-body');
    const rows = [];
    for (const r of m.rows) {
      const tr = el('tr', r.reported_valid === 0 || r.parse_issue ? 'flag' : '');
      const valid = r.parse_issue ? `无法解析：${r.parse_issue}` : r.reported_valid === undefined ? '—' : String(r.reported_valid);
      tr.append(el('td', 'num', r.frame ?? '—'), el('td', 'num', r.code_value ?? '—'), el('td', 'num', valid), el('td', null, stamp(r.observed_epoch)));
      const cell = el('td');
      const b = el('button', 'quiet-button', m.open.has(r.evidence_id) ? '收起原文' : '原文');
      b.type = 'button';
      b.addEventListener('click', () => {
        if (m.open.has(r.evidence_id)) m.open.delete(r.evidence_id); else m.open.add(r.evidence_id);
        renderMeasurements(run);
      });
      cell.append(b);
      tr.append(cell);
      rows.push(tr);
      if (m.open.has(r.evidence_id)) {
        const er = el('tr', 'evidence-row');
        const td = el('td');
        td.colSpan = 5;
        td.append(el('p', 'panel-note', '正在读取原文…'));
        getEvidence(r.evidence_id).then((e) => td.replaceChildren(logView(e))).catch((err) => td.replaceChildren(el('p', 'panel-note', err.message)));
        er.append(td);
        rows.push(er);
      }
    }
    body.replaceChildren(...rows);
    const total = run.measurements.records;
    $('measure-note').textContent = total
      ? `显示最新的 ${m.rows.length} 条（共 ${total} 条）。测试台报告值，不作正确码判定。`
      : '当前已索引的日志里没有测试台记录。';
    const earlier = $('measure-earlier');
    earlier.hidden = m.exhausted || !m.rows.length;
  }

  // ---------------------------------------------------------------- settings and integrity
  async function loadDetails(run) {
    const cached = ui.details.get(run.run_id);
    const now = Date.now();
    if (cached && cached.token === run.token && now - cached.at < 10000) return cached.data;
    const data = (await api('/api/run-details', { run: run.run_id })).details;
    ui.details.set(run.run_id, { token: run.token, at: now, data });
    return data;
  }
  function renderSettings(d) {
    const panel = $('panel-settings');
    if (!d.settings.length) {
      panel.replaceChildren(el('p', 'panel-note', '日志里还没有识别到求解器设置。'));
      return;
    }
    const table = el('table', 'data-table');
    const head = el('tr');
    for (const h of ['参数', '用户请求值', '分析实际生效值', '默认值']) { const th = el('th', null, h); th.scope = 'col'; head.append(th); }
    table.append(el('thead'), el('tbody'));
    table.tHead.append(head);
    for (const s of d.settings) {
      const tr = el('tr');
      const name = el('td', 'num' + (s.differs ? ' differs' : ''), s.name);
      const effective = s.effective.map((e) => (e.analysis ? `${e.analysis}：${e.value}` : e.value)).join('；') || '—';
      const eff = el('td', 'wrap', effective);
      if (s.differs) eff.append(document.createTextNode(' '), chip('与请求值不同', 'warning'));
      const defaults = [s.requested_default, ...s.effective.map((e) => e.default)].filter(Boolean).join('；') || '—';
      tr.append(name, el('td', 'wrap', s.requested ?? '—'), eff, el('td', 'wrap', defaults));
      table.tBodies[0].append(tr);
    }
    panel.replaceChildren(table, el('p', 'panel-note', '请求值来自 Global user options，生效值来自分析开头的 Important parameter values；只并列原文，不判断设置好坏。'));
  }
  function check(stateCls, glyph, name, body, note) {
    const li = el('li', 'check');
    const icon = el('span', 'shape ' + stateCls, glyph);
    icon.setAttribute('aria-hidden', 'true');
    const content = el('div', 'check-body', body);
    if (note) content.append(el('small', null, note));
    li.append(icon, el('span', 'check-name', name), content);
    return li;
  }
  function renderIntegrity(d, run) {
    const items = [];
    const f = d.footer;
    items.push(f
      ? check(f.errors ? 'state-bad' : 'state-ok', f.errors ? '✗' : '✓', '原生日志结尾', `spectre completes with ${f.errors} errors, ${f.warnings} warnings, ${f.notices} notices`)
      : check('state-gap', '…', '原生日志结尾', '尚未出现结尾行', '仿真可能仍在运行，或异常中断；不会因此判为完成。'));
    const names = { state: '管理状态文件', log_status: 'logStatus', raw: '波形 raw 头尾' };
    for (const c of (d.integrity && d.integrity.checks) || []) {
      const name = names[c.check] || c.check;
      if (c.status === 'not_checked') { items.push(check('state-none', '—', name, '未配置，不检查')); continue; }
      if (c.status !== 'observed') { items.push(check('state-gap', '!', name, `不可用（${c.status}）`, c.detail || c.format || '')); continue; }
      if (c.check === 'state') {
        const bad = c.exit_code || ['failed', 'limit_exceeded', 'rejected', 'cancelled', 'killed'].includes(c.reported_status);
        items.push(check(bad ? 'state-bad' : 'state-ok', bad ? '✗' : '✓', name, `报告状态 ${c.reported_status}，退出码 ${c.exit_code ?? '—'}${c.reason ? `，原因 ${c.reason}` : ''}`));
      } else if (c.check === 'log_status') {
        const ok = c.last_status === 'PASS';
        items.push(check(ok ? 'state-ok' : ['FAIL', 'FAILED', 'ERROR'].includes(c.last_status) ? 'state-bad' : 'state-gap', ok ? '✓' : '!', name,
          `${c.analysis || '未指定分析'}：${c.last_status || '未出现'}`, Object.entries(c.all_analyses || {}).map(([k, v]) => `${k} ${v}`).join('，')));
      } else {
        const ok = c.end_marker && c.expected_stop_reached !== false;
        items.push(check(ok ? 'state-ok' : 'state-gap', ok ? '✓' : '!', name,
          `END 标记${c.end_marker ? '存在' : '缺失'}，最后保存时间 ${fmtTime(c.last_saved_time_s)}，${c.expected_stop_reached === null ? '未配置预期结束时间' : c.expected_stop_reached ? '已到预期结束时间' : '未到预期结束时间'}，文件 ${bytes(c.size_bytes)}`,
          '只读文件头 4 KiB 和尾部 64 KiB，不是全波形检查。'));
      }
    }
    items.push(check(run.state.backlog ? 'state-gap' : 'state-ok', run.state.backlog ? '…' : '✓', '索引进度',
      `${bytes(d.indexed_bytes)} / ${bytes(d.source_bytes)}`, run.state.backlog ? '索引尚未追平日志。' : ''));
    const totals = Object.entries(d.suppressed_totals || {}).map(([k, v]) => `${k === 'warning' ? '警告' : k === 'notice' ? '提示' : k} ${v.toLocaleString('zh-CN')} 条`);
    items.push(check('state-none', '·', '原生抑制汇总', totals.length ? totals.join('，') : '日志尚未报告抑制总数', 'Spectre 的全局汇总，不能分摊到各个编号。'));
    const analyses = Object.entries(d.analyses || {}).map(([k, v]) => `${k}（结束时间 ${fmtTime(v.stop_time_s)}）`);
    items.push(check('state-none', '·', 'Spectre 与分析', `${d.version || '版本未识别'}${analyses.length ? '；' + analyses.join('，') : ''}`));
    const rules = d.watch.map((r) => r.name);
    items.push(check('state-none', '·', '关注设置', rules.length ? `规则 ${rules.join('、')}` : '没有关注规则',
      `参考运行 ${d.baseline || '未指定'}；运行未结束而日志超过 ${fmtAge(d.quiet_after_s)}没有更新时提醒。`));
    const limits = run.coverage.limitations;
    items.push(check('state-none', '·', '检查范围', '只核对已配置的证据来源是否正常结束，不判断电路或码字是否合格。',
      limits.length ? `未覆盖：${limits.join('，')}` : ''));
    const list = el('ul', 'checks');
    list.append(...items);
    $('panel-integrity').replaceChildren(list);
  }

  // ---------------------------------------------------------------- panels and tabs
  function currentRun() { return ui.data ? ui.data.runs.find((r) => r.run_id === ui.selected) : null; }
  async function refreshPanel() {
    const run = currentRun();
    if (!run) return;
    try {
      if (ui.tab === 'measurements') {
        if (!ui.meas || ui.meas.run !== run.run_id || ui.meas.generation !== run.generation) await loadMeasurements(run, 'initial');
        else if (ui.meas.records !== run.measurements.records) await loadMeasurements(run, 'newer');
      } else if (ui.tab === 'settings') {
        renderSettings(await loadDetails(run));
      } else if (ui.tab === 'integrity') {
        renderIntegrity(await loadDetails(run), run);
      }
    } catch (e) {
      $('panel-' + ui.tab).replaceChildren(el('p', 'panel-note', `读取失败：${e.message}`));
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
    const counts = { problems: run.problems.group_count, measurements: run.measurements.records };
    for (const tab of document.querySelectorAll('.tab')) {
      const label = { problems: '问题', measurements: '测量', settings: '设置', integrity: '完整性' }[tab.dataset.tab];
      tab.replaceChildren(document.createTextNode(label));
      if (counts[tab.dataset.tab] !== undefined) tab.append(el('span', 'count', counts[tab.dataset.tab]));
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
    document.title = n ? `(${n}) Spectre 运行监视` : 'Spectre 运行监视';
  }
  function render() {
    renderTopline();
    if (!ui.data) return;
    const runs = ui.data.runs;
    $('empty').hidden = runs.length > 0;
    $('run-view').hidden = runs.length === 0;
    if (!runs.length) { renderRail(runs); updateTitle(runs); return; }
    if (!runs.some((r) => r.run_id === ui.selected)) {
      ui.selected = railOrder(runs)[0].r.run_id;
      writeHash();
    }
    renderRail(runs);
    const run = currentRun();
    renderHead(run);
    renderAxis(run);
    renderWatch(run);
    renderTabs(run);
    renderProblems(run, false);
    updateTitle(runs);
  }

  function setupControls() {
    const pause = $('pause');
    pause.addEventListener('click', () => {
      ui.paused = !ui.paused;
      pause.setAttribute('aria-pressed', ui.paused ? 'true' : 'false');
      pause.textContent = ui.paused ? '继续刷新' : '暂停刷新';
    });
    const bell = $('notify');
    const sync = () => {
      bell.setAttribute('aria-pressed', ui.notify ? 'true' : 'false');
      bell.textContent = ui.notify ? '提醒已开启' : '开启提醒';
    };
    if (!('Notification' in window)) {
      bell.disabled = true;
      bell.textContent = '浏览器不支持提醒';
    } else {
      ui.notify = localStorage.getItem('simcheck.notify') === 'on' && Notification.permission === 'granted';
      sync();
      bell.addEventListener('click', async () => {
        if (ui.notify) {
          ui.notify = false;
        } else {
          const permission = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
          ui.notify = permission === 'granted';
          if (!ui.notify) announce('浏览器没有允许本页发送提醒：请在地址栏的站点设置里允许通知。');
        }
        localStorage.setItem('simcheck.notify', ui.notify ? 'on' : 'off');
        sync();
      });
    }
    $('ack').addEventListener('click', () => { const run = currentRun(); if (run) acknowledge(run); });
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
      resize = setTimeout(() => { if (ui.data && currentRun()) { renderAxis(currentRun()); renderRail(ui.data.runs); } }, 150);
    });
  }

  const initial = readHash();
  ui.selected = initial.run;
  setupControls();
  setTab(['problems', 'measurements', 'settings', 'integrity'].includes(initial.tab) ? initial.tab : 'problems');
  tick();
})();
