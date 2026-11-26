// HelloWorld web app: one page for Open Shot Designer -> Kitsu + AYON -> cut -> Blender.

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const enc = encodeURIComponent;

const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z"/>',
  film: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  pencil: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  board: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/>',
  layers: '<path d="M12 3 2 8l10 5 10-5z"/><path d="m2 13 10 5 10-5"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
  ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>',
  folder: '<path d="M3 6h7l2 2h9v11H3z"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M4 16V4h12"/>',
  play: '<path d="M7 4l13 8-13 8z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
  blender: '<circle cx="14" cy="13" r="6"/><circle cx="14" cy="13" r="2"/><path d="M3 9h7M6 5l6 4"/>',
};
const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;

const state = {
  status: null,
  settings: null,
  projects: [],
  jobs: [],
  route: { view: 'home' },
  project: null, // detail of the open project
  tracking: null, // its Kitsu/AYON view
  trackingFor: null,
  taskTypes: [],
  pull: { task_type: 'Layout', stage: 'previs' },
  activityOpen: false,
  selectedJob: null,
  log: { id: null, lines: [], offset: 0 },
  pending: new Set(), // buttons waiting for a response
  uploadTarget: null, // project name when "Update plan" was clicked
};

// -- server --------------------------------------------------------------------------------------

async function api(path, { method = 'GET', body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = data && (data.error || data.detail);
    throw new Error(typeof detail === 'string' ? detail : res.statusText || 'Request failed');
  }
  return data;
}

function toast(message, kind = 'ok') {
  const el = document.createElement('div');
  el.className = `toast ${kind === 'bad' ? 'bad' : ''}`;
  el.innerHTML = `<span class="dot ${kind}"></span><div>${esc(message)}</div>`;
  $('#toasts').append(el);
  setTimeout(() => el.remove(), kind === 'bad' ? 9000 : 4500);
}

async function run(key, fn) {
  if (state.pending.has(key)) return;
  state.pending.add(key);
  renderBusy();
  try {
    const result = await fn();
    if (result && result.job) {
      state.selectedJob = result.job.id;
      upsertJob(result.job);
      renderActivity();
      pollJobs(true);
    }
    return result;
  } catch (err) {
    toast(err.message, 'bad');
  } finally {
    state.pending.delete(key);
    renderBusy();
  }
}

// Replace an element's contents only when they actually change. The page redraws on every poll,
// and swapping identical buttons out from under the pointer swallows clicks.
const drawn = new WeakMap();
function setHTML(el, html) {
  if (drawn.get(el) === html) return false;
  drawn.set(el, html);
  el.innerHTML = html;
  tickTimes();
  renderBusy();
  return true;
}

function renderBusy() {
  document.querySelectorAll('[data-key]').forEach((el) => {
    const busy = state.pending.has(el.dataset.key) || runningJob(el.dataset.key);
    el.classList.toggle('busy', Boolean(busy));
    if (busy) el.disabled = true;
    else if (el.dataset.disabled !== 'true') el.disabled = false;
  });
}

// -- helpers -------------------------------------------------------------------------------------

// Relative times are drawn as <time> elements and ticked in place (tickTimes), so the page's HTML
// doesn't change every minute and setHTML can leave it alone.
function ago(seconds) {
  if (!seconds) return '';
  return `<time data-ts="${seconds}"></time>`;
}

function tickTimes() {
  document.querySelectorAll('time[data-ts]').forEach((el) => {
    const text = agoText(Number(el.dataset.ts));
    if (el.textContent !== text) el.textContent = text;
  });
}

function agoText(seconds) {
  const d = Date.now() / 1000 - seconds;
  if (d < 45) return 'just now';
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  return new Date(seconds * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}

function runningJob(key) {
  if (!key) return null;
  const [kind, project] = key.split('|');
  return state.jobs.find((j) => j.status === 'running' && j.kind === kind && (j.project || '') === (project || ''));
}

function btn(label, { action, key, kind = '', icon: ic, disabled = false, data = {}, title = '' } = {}) {
  const attrs = Object.entries(data).map(([k, v]) => ` data-${k}="${esc(v)}"`).join('');
  const busy = key && (state.pending.has(key) || runningJob(key));
  return `<button class="btn ${kind} ${busy ? 'busy' : ''}" data-action="${esc(action)}"${key ? ` data-key="${esc(key)}"` : ''}${attrs}
    data-disabled="${disabled}" ${disabled || busy ? 'disabled' : ''} ${title ? `title="${esc(title)}"` : ''}>${ic ? icon(ic) : ''}${esc(label)}</button>`;
}

function setupTodo(s = state.status) {
  if (!s) return [];
  const todo = [];
  if (!s.docker.running) todo.push('docker');
  else if (!s.images.ayon?.built || !s.images.processor?.built) todo.push('images');
  if (!s.osd.built) todo.push('osd');
  if (!s.blender.found) todo.push('blender');
  else if (s.blender.addon !== 'installed' || !s.blender.otio) todo.push('addon');
  return todo;
}

function stackDot(s = state.status) {
  const st = s?.stack.state;
  return st === 'running' ? 'ok' : st === 'starting' ? 'warn' : '';
}

// -- routing -------------------------------------------------------------------------------------

function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, '').split('/');
  if (parts[0] === 'p' && parts[1]) return { view: 'project', name: decodeURIComponent(parts.slice(1).join('/')) };
  if (['plan', 'kitsu', 'ayon', 'setup'].includes(parts[0])) return { view: parts[0] };
  return { view: 'home' };
}

async function onRoute() {
  state.route = parseRoute();
  document.body.classList.remove('nav-open');
  renderSidebar();
  if (state.route.view === 'project') {
    if (state.project?.name !== state.route.name) {
      state.project = null;
      state.tracking = null;
      state.trackingFor = null;
    }
    renderView();
    await loadProject();
  } else {
    renderView();
  }
  $('#view').focus({ preventScroll: true });
}

async function loadProject({ quiet = false } = {}) {
  const name = state.route.name;
  try {
    const detail = await api(`/api/projects/${enc(name)}`);
    if (state.route.view !== 'project' || state.route.name !== name) return;
    state.project = detail;
    renderView();
    loadTracking(name);
  } catch (err) {
    if (!quiet) {
      state.project = { error: err.message, name };
      renderView();
    }
  }
}

async function loadTracking(name) {
  try {
    const tracking = await api(`/api/projects/${enc(name)}/tracking`);
    if (state.route.name !== name) return;
    state.tracking = tracking;
    state.trackingFor = name;
    const types = tracking?.kitsu?.task_types;
    if (types?.length) state.taskTypes = types;
    renderView();
  } catch {
    /* the page works without it */
  }
}

// -- sidebar -------------------------------------------------------------------------------------

function renderSidebar() {
  const r = state.route;
  const s = state.status;
  const todo = setupTodo();
  const nav = (href, label, ic, active, extra = '') =>
    `<a class="nav-item ${active ? 'active' : ''}" href="${href}">${icon(ic)}<span class="label">${esc(label)}</span>${extra}</a>`;
  const stack = s?.stack;
  const stState = stack?.state || 'stopped';
  const svc = (name, up, url) => `<div class="svc"><span class="dot ${up ? 'ok' : stState === 'starting' ? 'warn' : ''}"></span>
      <span class="grow">${name}</span>${up ? `<a href="${esc(url)}" target="_blank" rel="noopener">open ↗</a>` : ''}</div>`;
  let control = '';
  if (s && s.docker.running && s.images.ayon?.built) {
    control = stState === 'stopped'
      ? btn('Start services', { action: 'stack', data: { do: 'start' }, key: 'stack|', kind: 'primary block', icon: 'play' })
      : btn(stState === 'starting' ? 'Starting…' : 'Stop services', { action: 'stack', data: { do: 'stop' }, key: 'stack|', kind: 'block', icon: 'stop' });
  } else if (s && !s.docker.running) {
    control = '<div class="faint" style="font-size:12.5px">Docker Desktop isn\'t running.</div>';
  } else if (s) {
    control = `<a class="btn block" href="#/setup">Finish setup</a>`;
  }
  setHTML($('#sidebar'), `
    <div class="brand"><span class="logo">${icon('film')}</span>HelloWorld</div>
    <nav class="nav">
      ${nav('#/', 'Home', 'home', r.view === 'home')}
      <div class="nav-label">Projects</div>
      ${state.projects.map((p) => nav(`#/p/${enc(p.name)}`, p.name, 'board', r.view === 'project' && r.name === p.name,
        `<span class="count">${p.shots ?? ''}</span>`)).join('')}
      <button class="nav-item add" data-action="upload">${icon('plus')}<span class="label">Add a plan (.osd)</span></button>
      <div class="nav-label">Tools</div>
      ${nav('#/plan', 'Open Shot Designer', 'pencil', r.view === 'plan')}
      ${nav('#/kitsu', 'Kitsu', 'layers', r.view === 'kitsu')}
      ${nav('#/ayon', 'AYON', 'layers', r.view === 'ayon')}
      ${nav('#/setup', 'Setup', 'gear', r.view === 'setup', todo.length ? `<span class="badge">${todo.length}</span>` : '')}
    </nav>
    <div class="services">
      ${svc('Kitsu', stack?.kitsu.up, stack?.kitsu.url)}
      ${svc('AYON', stack?.ayon.up, stack?.ayon.url)}
      ${control}
    </div>`);
}

// -- views ---------------------------------------------------------------------------------------

function renderView() {
  const view = $('#view');
  const v = state.route.view;
  const framed = ['plan', 'kitsu', 'ayon'].includes(v);
  view.classList.toggle('flush', framed);
  if (framed) {
    const ready = frameReady(v);
    view.hidden = ready;
    $('#frames').hidden = !ready;
    if (ready) showFrame(v);
    else setHTML(view, frameOffline(v));
    return;
  }
  view.hidden = false;
  $('#frames').hidden = true;
  // Don't yank a dropdown out from under the user; the next refresh catches up.
  if (document.activeElement?.tagName === 'SELECT' && view.contains(document.activeElement)) return;
  const scroll = view.scrollTop;
  const html = v === 'home' ? homeView() : v === 'project' ? projectView() : v === 'setup' ? setupView() : '';
  if (setHTML(view, html)) view.scrollTop = scroll;
}

function homeView() {
  const s = state.status;
  const todo = setupTodo();
  const stack = s?.stack;
  const banner = todo.length ? `
    <div class="card setup-banner">
      <span class="dot warn"></span>
      <div class="grow"><b>Finish setting up.</b> <span class="muted">${plural(todo.length, 'item')} left before everything works.</span></div>
      <a class="btn" href="#/setup">Open setup</a>
    </div>` : '';
  const svcLine = (name, info, extra) => `<div class="svc"><span class="dot ${info?.up ? 'ok' : stack?.state === 'starting' ? 'warn' : ''}"></span>
    <span class="grow">${name}</span><span class="faint">${info?.up ? extra : stack?.state === 'starting' ? 'starting…' : 'stopped'}</span></div>`;
  const projects = state.projects.map((p) => `
    <a class="card project-card" href="#/p/${enc(p.name)}">
      <div class="thumb">${p.thumb ? `<img src="${esc(p.thumb)}" alt="" loading="lazy">` : icon('board')}</div>
      <div class="body">
        <div class="name">${esc(p.name)}</div>
        <div class="meta">${p.error ? esc(p.error) : `${plural(p.scenes, 'scene')} · ${plural(p.shots, 'shot')} · ${ago(p.updated)}`}</div>
      </div>
    </a>`).join('');
  return `<div class="page">
    ${banner}
    <div class="hero">
      <div class="card pad intro">
        <h1>Your films</h1>
        <p>Plan shots and boards in Open Shot Designer, track them in Kitsu and AYON, and cut them in Blender, all from here.</p>
        <div class="flow"><span class="step">Plan</span><span class="arrow">→</span><span class="step">Kitsu</span><span class="arrow">→</span>
          <span class="step">AYON</span><span class="arrow">→</span><span class="step">Cut</span><span class="arrow">→</span><span class="step">Blender</span></div>
      </div>
      <div class="card pad svc-card">
        <h3>Services</h3>
        ${svcLine('Kitsu · tracking and review', stack?.kitsu, 'running')}
        ${svcLine('AYON · pipeline', stack?.ayon, 'running')}
        <div class="svc"><span class="dot ${s?.osd.built ? 'ok' : ''}"></span><span class="grow">Open Shot Designer</span>
          <span class="faint">${s?.osd.built ? 'ready' : 'not set up'}</span></div>
        <div class="svc"><span class="dot ${s?.blender.addon === 'installed' ? 'ok' : ''}"></span><span class="grow">Blender ${esc(s?.blender.version || '')}</span>
          <span class="faint">${!s?.blender.found ? 'not found' : s.blender.addon === 'installed' ? 'add-on ready' : 'add-on missing'}</span></div>
        <div class="footer">
          ${s?.images?.ayon?.built ? (stack?.state === 'stopped'
            ? btn('Start services', { action: 'stack', data: { do: 'start' }, key: 'stack|', kind: 'primary', icon: 'play' })
            : btn('Stop services', { action: 'stack', data: { do: 'stop' }, key: 'stack|', icon: 'stop' })) : ''}
        </div>
      </div>
    </div>
    <div class="section-title">Projects <span class="faint" style="text-transform:none;letter-spacing:0">in ${esc(s?.projects_dir || '')}</span></div>
    <div class="grid">
      ${projects}
      <div class="card dropzone">
        <div class="big">Add a plan</div>
        <div>Drop an Open Shot Designer <b>.osd</b> anywhere on this page, or</div>
        <div class="actions">${btn('Choose file…', { action: 'upload', icon: 'upload' })}<a class="btn ghost" href="#/plan">${icon('pencil')}Plan a new film</a></div>
      </div>
    </div>
  </div>`;
}

function stageCard(n, title, done, body) {
  return `<div class="card stage ${done ? 'done' : ''}"><div class="top"><span class="num">${done ? '✓' : n}</span><h3>${title}</h3></div>${body}</div>`;
}

function projectView() {
  const p = state.project;
  if (!p) return `<div class="page"><div class="empty"><span class="spinner"></span></div></div>`;
  if (p.error) return `<div class="page"><div class="empty">${esc(p.error)}<br><br><a class="btn" href="#/">Back</a></div></div>`;
  const s = state.status;
  const t = state.trackingFor === p.name ? state.tracking : null;
  const key = (kind) => `${kind}|${p.name}`;
  const online = s?.stack.kitsu.up;
  const kitsu = t?.kitsu;
  const ayon = t?.ayon;

  // 1. Kitsu
  let kBody;
  if (!online) kBody = `<div class="state">Start Kitsu and AYON to send the plan.</div>
      <div class="row">${btn('Start services', { action: 'stack', data: { do: 'start' }, key: 'stack|', kind: 'primary', icon: 'play', disabled: !s?.images?.ayon?.built })}</div>`;
  else if (!t) kBody = `<div class="state"><span class="spinner"></span></div>`;
  else if (kitsu?.error) kBody = `<div class="state">Couldn't reach Kitsu: ${esc(kitsu.error)}</div>`;
  else if (!kitsu?.exists) kBody = `<div class="state">Not in Kitsu yet. Sends scenes, shots, camera notes and boards.</div>
      <div class="row">${btn('Push plan to Kitsu', { action: 'project', data: { do: 'push' }, key: key('push'), kind: 'primary' })}</div>`;
  else kBody = `<div class="state"><b>${plural(kitsu.shots, 'shot')}</b> in Kitsu. Push again after changing the plan.</div>
      <div class="row">${btn('Push changes', { action: 'project', data: { do: 'push' }, key: key('push') })}
      <a class="ext" href="${esc(kitsu.url)}" target="_blank" rel="noopener">Open in Kitsu ↗</a></div>`;

  // 2. AYON
  let aBody;
  if (!online || !t) aBody = `<div class="state">${online ? '<span class="spinner"></span>' : 'Waiting for Kitsu.'}</div>`;
  else if (!kitsu?.exists) aBody = `<div class="state">Push to Kitsu first; AYON mirrors Kitsu.</div>`;
  else if (ayon?.error) aBody = `<div class="state">${esc(ayon.error)}</div>`;
  else if (!ayon?.paired) aBody = `<div class="state">Not in AYON yet. Creates the pipeline project and keeps it in sync with Kitsu.</div>
      <div class="row">${btn('Sync to AYON', { action: 'project', data: { do: 'sync-ayon' }, key: key('sync-ayon'), kind: 'primary', disabled: !s?.stack.ayon.up })}</div>`;
  else aBody = `<div class="state"><b>${plural(ayon.folders, 'folder')}</b> · ${plural(ayon.tasks, 'task')} in <b>${esc(ayon.project)}</b>, kept in sync from Kitsu.</div>
      <div class="row">${btn('Sync again', { action: 'project', data: { do: 'sync-ayon' }, key: key('sync-ayon') })}
      <a class="ext" href="${esc(ayon.url)}" target="_blank" rel="noopener">Open in AYON ↗</a></div>`;

  // 3. Cut
  const counts = p.cut?.stages || {};
  const types = state.taskTypes.length ? state.taskTypes : ['Layout', 'Animation', 'Compositing'];
  if (!types.includes(state.pull.task_type)) state.pull.task_type = types.includes('Layout') ? 'Layout' : types[0];
  const pull = `<div class="pull">
      <select class="input" data-bind="task_type" aria-label="Kitsu task">${types.map((x) => `<option ${x === state.pull.task_type ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select>
      <select class="input" data-bind="stage" aria-label="Use as">${['previs', 'final'].map((x) => `<option value="${x}" ${x === state.pull.stage ? 'selected' : ''}>as ${x}</option>`).join('')}</select>
      ${btn('Pull from Kitsu', { action: 'project', data: { do: 'pull' }, key: key('pull'), disabled: !online, title: online ? '' : 'Start the services first' })}
    </div>`;
  const cBody = p.cut
    ? `<div class="state"><b>${counts.board || 0}</b> boards · <b>${counts.previs || 0}</b> previs · <b>${counts.final || 0}</b> final <span class="faint">· built ${ago(p.cut.updated)}</span></div>
       ${pull}
       <div class="row">${btn('Rebuild', { action: 'project', data: { do: 'build-cut' }, key: key('build-cut'), kind: 'small' })}
         ${btn('Attach renders', { action: 'project', data: { do: 'attach-renders' }, key: key('attach-renders'), kind: 'small', title: 'Adds the files in renders/ (named like SC001_SH002_v001.mov) to the cut as final' })}
         ${btn('Renders folder', { action: 'reveal', data: { target: 'renders' }, kind: 'small ghost', icon: 'folder' })}</div>`
    : `<div class="state">No cut yet. Builds a board-o-matic: each shot's boards for its planned length.</div>
       <div class="row">${btn('Build the cut', { action: 'project', data: { do: 'build-cut' }, key: key('build-cut'), kind: 'primary' })}</div>`;

  // 4. Blender
  const b = s?.blender;
  let bBody;
  if (!b?.found) bBody = `<div class="state">Blender isn't installed. <a class="ext" href="https://www.blender.org/download/" target="_blank" rel="noopener">Get Blender ↗</a></div>`;
  else if (b.addon === 'missing' || !b.otio) bBody = `<div class="state">Install the HelloWorld add-on in Blender ${esc(b.version)} first.</div>
      <div class="row">${btn('Install add-on', { action: 'blender-install', key: 'blender|', kind: 'primary' })}</div>`;
  else bBody = `<div class="state">${p.edit.exists ? `<b>edit.blend</b> saved ${ago(p.edit.updated)}.` : 'Opens the cut in Blender’s sequencer as edit.blend.'}
        ${b.addon === 'outdated' ? '<br><span class="faint">Add-on update available in Setup.</span>' : ''}</div>
      <div class="row">${btn('Open in Blender', { action: 'project', data: { do: 'open-blender' }, key: key('open-blender'), kind: 'primary', icon: 'blender' })}
        ${p.edit.exists ? btn('Rebuild from cut', { action: 'project', data: { do: 'rebuild-edit' }, key: key('rebuild-edit'), kind: 'small ghost', title: 'Re-import the latest cut; the current edit is kept in history/' }) : ''}</div>`;

  const scenes = p.scenes_detail.map((scene) => `
    <div class="scene">
      <div class="scene-head"><span class="seq">${esc(scene.sequence)}</span><h3>${esc(scene.heading)}</h3><span class="count">${plural(scene.shots.length, 'shot')}</span></div>
      <div class="card shots">${scene.shots.map((shot) => shotRow(shot, kitsu?.tasks?.[shot.clip])).join('')}</div>
    </div>`).join('');

  return `<div class="page">
    <div class="page-head">
      <div class="titles">
        <h1>${esc(p.title || p.name)}</h1>
        <div class="sub">${plural(p.scenes, 'scene')} · ${plural(p.shots, 'shot')} · ${p.fps} fps · ${esc(p.aspect)} · plan saved ${ago(p.updated)}</div>
      </div>
      <div class="actions">
        <a class="btn" href="#/plan">${icon('pencil')}Edit plan</a>
        ${btn('Update plan…', { action: 'upload', data: { project: p.name }, icon: 'upload' })}
        <a class="btn ghost" href="/api/projects/${enc(p.name)}/plan.osd" download>Download .osd</a>
        ${btn('Show in Finder', { action: 'reveal', data: { target: 'folder' }, kind: 'ghost', icon: 'folder' })}
      </div>
    </div>
    <div class="pipeline">
      ${stageCard(1, 'Kitsu', kitsu?.exists, kBody)}
      ${stageCard(2, 'AYON', ayon?.paired, aBody)}
      ${stageCard(3, 'Cut', Boolean(p.cut), cBody)}
      ${stageCard(4, 'Blender', p.edit.exists, bBody)}
    </div>
    <div class="section-title">Shots</div>
    ${scenes || '<div class="empty">This plan has no shots yet.</div>'}
  </div>`;
}

function shotRow(shot, tasks) {
  const boards = shot.boards.length
    ? shot.boards.slice(0, 3).map((b) => `<button data-action="zoom" data-src="${esc(b.url)}" data-cap="${esc(`${shot.clip} · ${b.label}`)}" title="${esc(b.label)}"><img src="${esc(b.url)}" alt="${esc(b.label)}" loading="lazy"></button>`).join('')
    : '<div class="none">no board</div>';
  const specs = [shot.size, shot.lens, shot.movement, shot.angle, shot.camera].filter(Boolean).map((x) => `<span class="chip">${esc(x)}</span>`).join('');
  const pills = ['board', 'previs', 'final'].map((st) =>
    `<span class="stage-pill ${shot.stages.includes(st) ? 'has' : ''} ${shot.active === st ? 'active' : ''}">${st}</span>`).join('');
  const taskList = (tasks || []).map((t) => `<span class="task" title="${esc(t.status_name)}"><span class="swatch" style="background:${esc(t.color)}"></span>${esc(t.type)} <b>${esc(t.status)}</b></span>`).join('');
  return `<div class="shot">
    <div class="boards">${boards}</div>
    <div>
      <div class="ids"><span class="clip">${esc(shot.clip)}</span><span class="slate">slate ${esc(shot.slate)}</span>
        ${shot.status ? `<span class="chip ${shot.status === 'ready' ? 'ok' : ''}">${esc(shot.status)}</span>` : ''}</div>
      ${shot.description ? `<div class="desc">${esc(shot.description)}</div>` : ''}
      ${specs ? `<div class="specs">${specs}</div>` : ''}
    </div>
    <div class="timing"><b>${shot.seconds.toFixed(1)} s</b>${shot.estimated ? '' : ' <span class="faint">default</span>'}
      <div class="stages">${pills}</div></div>
    <div class="tasks">${taskList || '<span class="faint" style="font-size:12px">—</span>'}</div>
  </div>`;
}

function setupView() {
  const s = state.status;
  if (!s) return `<div class="page"><div class="empty"><span class="spinner"></span></div></div>`;
  const st = state.settings;
  const row = (ok, what, detail, action = '') => `<div class="check ${ok ? 'ok' : 'todo'}">
      <span class="mark">${ok ? '✓' : '!'}</span>
      <div><div class="what">${what}</div><div class="detail">${detail}</div></div>
      <div class="actions">${ok ? '' : action}</div></div>`;
  const imagesBuilt = s.images.ayon?.built && s.images.processor?.built;
  const b = s.blender;
  const addonOk = b.found && b.addon === 'installed' && b.otio;
  const cred = (k, v, secret) => `<span class="k">${k}</span><span class="v mono">${secret ? '••••••••••' : esc(v)}</span>
      ${btn('', { action: 'copy', data: { value: v }, kind: 'small ghost', icon: 'copy', title: `Copy ${k.toLowerCase()}` })}`;
  return `<div class="page">
    <div class="page-head"><div class="titles"><h1>Setup</h1><div class="sub">Everything HelloWorld needs on this Mac. Each step only needs doing once.</div></div></div>
    <div class="card checklist">
      ${row(s.docker.running, 'Docker Desktop', s.docker.running ? `Running (Docker ${esc(s.docker.version)})` : s.docker.installed ? 'Installed but not running: open Docker Desktop.' : 'Not installed: get Docker Desktop from docker.com.',
        s.docker.installed ? '' : '<a class="btn" href="https://www.docker.com/products/docker-desktop/" target="_blank" rel="noopener">Get Docker ↗</a>')}
      ${row(imagesBuilt, 'AYON server images', imagesBuilt ? 'Built for this Mac (arm64).' : 'Builds AYON and its Kitsu sync from Ynput’s release sources. Takes several minutes.',
        btn('Build images', { action: 'stack', data: { do: 'build' }, key: 'stack|', kind: 'primary', disabled: !s.docker.running }))}
      ${row(s.stack.state === 'running', 'Kitsu and AYON', s.stack.state === 'running' ? `Running at ${esc(s.stack.kitsu.url)} and ${esc(s.stack.ayon.url)}.` : s.stack.state === 'starting' ? 'Starting…' : 'Stopped. Start them when you work; they keep running until you stop them.',
        btn('Start services', { action: 'stack', data: { do: 'start' }, key: 'stack|', disabled: !imagesBuilt }))}
      ${row(s.osd.built, 'Open Shot Designer', s.osd.built ? 'Ready, served by HelloWorld so plans save straight into your projects.' : s.osd.npm ? 'Downloads and builds Open Shot Designer (needs Node.js, about a minute).' : 'Needs Node.js from nodejs.org to build.',
        btn('Set up', { action: 'osd-setup', key: 'osd|', kind: 'primary', disabled: !s.osd.npm }))}
      ${row(b.found, 'Blender', b.found ? `Blender ${esc(b.version)} at ${esc(b.path)}` : 'Not found in /Applications.',
        '<a class="btn" href="https://www.blender.org/download/" target="_blank" rel="noopener">Get Blender ↗</a>')}
      ${row(addonOk, 'HelloWorld add-on for Blender', addonOk ? 'Installed, with OpenTimelineIO.' : !b.found ? 'Needs Blender.' : b.addon === 'outdated' ? 'An update is available.' : 'Imports cuts into the sequencer and swaps boards, previs and finals.',
        btn(b.addon === 'outdated' ? 'Update add-on' : 'Install add-on', { action: 'blender-install', key: 'blender|', kind: 'primary', disabled: !b.found || !b.supported }))}
    </div>
    <div class="section-title">Logins</div>
    <div class="logins">
      <div class="card pad login"><h3>Kitsu</h3><div class="kv">${st ? cred('Email', st.kitsu.email) + cred('Password', st.kitsu.password, true) : ''}</div></div>
      <div class="card pad login"><h3>AYON</h3><div class="kv">${st ? cred('User', st.ayon.user) + cred('Password', st.ayon.password, true) : ''}</div></div>
      <div class="card pad login"><h3>Open Shot Designer storage</h3><div class="kv">${st ? cred('Server', st.dav.url) + cred('User', st.dav.user) + cred('Password', st.dav.password, true) : ''}</div></div>
    </div>
    <div class="section-title">Projects folder</div>
    <div class="card pad mono">${esc(s.projects_dir)}</div>
  </div>`;
}

// -- embedded tools ------------------------------------------------------------------------------

const frames = {};

function frameReady(name) {
  const s = state.status;
  if (!s || !state.settings) return false;
  if (name === 'plan') return s.osd.built;
  return Boolean(s.stack[name]?.up);
}

function frameOffline(name) {
  const s = state.status;
  if (name === 'plan') {
    return `<div class="offline"><div><h2>Open Shot Designer isn't set up yet</h2><p>HelloWorld builds and serves it for you.</p>
      <div class="actions" style="justify-content:center">${btn('Set up Open Shot Designer', { action: 'osd-setup', key: 'osd|', kind: 'primary', disabled: !s?.osd.npm })}</div></div></div>`;
  }
  const label = name === 'kitsu' ? 'Kitsu' : 'AYON';
  const starting = s?.stack.state === 'starting';
  return `<div class="offline"><div><h2>${label} ${starting ? 'is starting…' : "isn't running"}</h2>
    <p>${starting ? 'This page opens it as soon as it answers.' : 'Start Kitsu and AYON together.'}</p>
    <div class="actions" style="justify-content:center">${starting ? '<span class="spinner"></span>'
      : btn('Start services', { action: 'stack', data: { do: 'start' }, key: 'stack|', kind: 'primary', icon: 'play', disabled: !s?.images?.ayon?.built })}</div></div></div>`;
}

function toolbar(name) {
  const st = state.settings;
  const s = state.status;
  const cred = (label, value, secret) => `<span class="cred">${label} <code>${secret ? '••••••' : esc(value)}</code>
      ${btn('', { action: 'copy', data: { value }, kind: 'small ghost', icon: 'copy', title: `Copy ${label.toLowerCase()}` })}</span>`;
  if (name === 'plan') {
    return `<div class="toolbar"><span class="title">Open Shot Designer</span>
      <span class="hint">To open a HelloWorld plan: <b>Cloud</b> → <b>Nextcloud</b> → <b>Connect</b> (already filled in) → <b>Open</b>. To save it back, use the Nextcloud save button on its card. HelloWorld picks it up right away.</span>
      <a class="btn small ghost" href="${esc(s.osd.url)}" target="_blank" rel="noopener">${icon('ext')}New tab</a></div>`;
  }
  const info = name === 'kitsu' ? { label: 'Kitsu', url: s.stack.kitsu.url, user: st.kitsu.email, pw: st.kitsu.password }
    : { label: 'AYON', url: s.stack.ayon.url, user: st.ayon.user, pw: st.ayon.password };
  return `<div class="toolbar"><span class="title">${info.label}</span>
    <span class="hint">${cred('Login', info.user)} ${cred('Password', info.pw, true)}</span>
    <a class="btn small ghost" href="${esc(info.url)}" target="_blank" rel="noopener">${icon('ext')}New tab</a></div>`;
}

function showFrame(name) {
  const host = $('#frames');
  for (const [key, el] of Object.entries(frames)) el.hidden = key !== name;
  if (!frames[name]) {
    const s = state.status;
    const src = name === 'plan' ? s.osd.url : s.stack[name].url;
    const el = document.createElement('div');
    el.className = 'frames';
    el.innerHTML = `${toolbar(name)}<div class="frame-wrap"><iframe src="${esc(src)}" title="${esc(name)}"
      allow="clipboard-read; clipboard-write; fullscreen"></iframe></div>`;
    host.append(el);
    frames[name] = el;
  }
}

function seedOpenShotDesigner(settings) {
  // Open Shot Designer runs on this same origin, so its Nextcloud (WebDAV) panel can come
  // pre-filled with HelloWorld's storage. It reads these keys when its dashboard opens.
  try {
    const set = (k, v) => localStorage.setItem(`openshotdesigner_ui_cloud.webdav.${k}`, v);
    set('url', JSON.stringify(settings.dav.url));
    set('username', JSON.stringify(settings.dav.user));
    set('remember', 'true');
    set('password', settings.dav.password);
  } catch {
    /* private mode: the user can type the details from Setup */
  }
}

// -- activity ------------------------------------------------------------------------------------

function upsertJob(job) {
  const i = state.jobs.findIndex((j) => j.id === job.id);
  if (i >= 0) state.jobs[i] = { ...state.jobs[i], ...job };
  else state.jobs.unshift(job);
}

function renderActivity() {
  const latest = state.jobs[0];
  const running = state.jobs.filter((j) => j.status === 'running');
  const dot = (j) => (j.status === 'running' ? 'warn' : j.status === 'ok' ? 'ok' : 'bad');
  const bar = latest
    ? `<span class="dot ${dot(latest)}"></span><span class="grow"><span class="title">${esc(latest.title)}</span>
       <span> · ${latest.status === 'running' ? esc(latest.last || 'working…') : latest.status === 'ok' ? 'done' : 'failed'}</span></span>`
    : '<span class="grow">No activity yet. Actions you run show their progress here.</span>';
  const count = running.length ? `<span class="chip warn">${running.length} running</span>` : '';
  let panel = '';
  if (state.activityOpen) {
    const selected = state.jobs.find((j) => j.id === state.selectedJob) || latest;
    const jobs = state.jobs.map((j) => `<button class="job ${selected && j.id === selected.id ? 'selected' : ''}" data-action="select-job" data-id="${j.id}">
        <span class="dot ${dot(j)}"></span><div><div class="t">${esc(j.title)}</div><div class="when">${ago(j.started)}</div></div></button>`).join('');
    const lines = state.log.id === selected?.id ? state.log.lines : [];
    const html = lines.map((l) => {
      const cls = l.startsWith('▸') ? 'step' : l.startsWith('✗') || /error|failed|traceback/i.test(l) ? 'err' : '';
      return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
    }).join('\n');
    panel = `<div class="panel"><div class="jobs">${jobs || '<div class="empty">Nothing yet.</div>'}</div><pre class="log" id="log">${html}</pre></div>`;
  }
  const el = $('#activity');
  const log = $('#log');
  const stick = !log || log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
  setHTML(el, `<div class="bar" data-action="toggle-activity">${bar}${count}<span class="faint">${state.activityOpen ? 'Hide ▾' : 'Activity ▴'}</span></div>${panel}`);
  const newLog = $('#log');
  if (newLog && stick) newLog.scrollTop = newLog.scrollHeight;
  document.documentElement.style.setProperty('--activity', state.activityOpen ? '344px' : '44px');
}

let jobTimer = null;
async function pollJobs(soon = false) {
  clearTimeout(jobTimer);
  if (soon) await new Promise((r) => setTimeout(r, 300));
  try {
    const before = new Map(state.jobs.map((j) => [j.id, j.status]));
    state.jobs = await api('/api/jobs');
    for (const job of state.jobs) {
      const was = before.get(job.id);
      if (was === 'running' && job.status !== 'running') onJobFinished(job);
    }
    const selected = state.jobs.find((j) => j.id === state.selectedJob) || state.jobs[0];
    if (state.activityOpen && selected) {
      if (state.log.id !== selected.id) state.log = { id: selected.id, lines: [], offset: 0 };
      const data = await api(`/api/jobs/${selected.id}?offset=${state.log.offset}`);
      state.log.lines.push(...data.lines);
      state.log.offset += data.lines.length;
    }
    renderActivity();
    renderBusy();
  } catch {
    /* server restarting */
  }
  const busy = state.jobs.some((j) => j.status === 'running');
  jobTimer = setTimeout(pollJobs, busy || state.activityOpen ? 1000 : 4000);
}

function onJobFinished(job) {
  toast(`${job.title}: ${job.status === 'ok' ? 'done' : 'failed — see Activity'}`, job.status === 'ok' ? 'ok' : 'bad');
  if (job.status !== 'ok' && !state.activityOpen) {
    state.activityOpen = true;
    state.selectedJob = job.id;
  }
  refreshStatus();
  refreshProjects();
  if (state.route.view === 'project' && job.project === state.route.name) loadProject({ quiet: true });
}

// -- polling ------------------------------------------------------------------------------------

// Only what the page shows: container health flickers while starting, and redrawing on every
// flicker would swallow clicks on buttons that are replaced mid-click.
function statusKey(s) {
  if (!s) return '';
  const st = s.stack;
  return JSON.stringify([s.docker.running, s.images?.ayon?.built, s.images?.processor?.built, st.state, st.kitsu.up,
    st.ayon.up, s.osd.built, s.osd.npm, s.blender.found, s.blender.addon, s.blender.otio, s.projects_dir]);
}

async function refreshStatus() {
  try {
    const before = state.status;
    state.status = await api('/api/status');
    if (statusKey(state.status) === statusKey(before)) return;
    renderSidebar();
    if (state.route.view === 'project' && before && state.project
        && (before.stack.kitsu.up !== state.status.stack.kitsu.up || before.stack.ayon.up !== state.status.stack.ayon.up)) {
      loadTracking(state.route.name);
    }
    renderView();
  } catch {
    /* server restarting */
  }
}

async function refreshProjects() {
  try {
    const before = state.projects;
    state.projects = await api('/api/projects');
    if (JSON.stringify(before) !== JSON.stringify(state.projects)) {
      renderSidebar();
      if (state.route.view === 'home') renderView();
      if (state.route.view === 'project') {
        const now = state.projects.find((p) => p.name === state.route.name);
        const was = before.find((p) => p.name === state.route.name);
        if (now && (!was || now.updated !== was.updated || now.has_cut !== was.has_cut)) loadProject({ quiet: true });
      }
    }
  } catch {
    /* ignore */
  }
}

// -- actions -------------------------------------------------------------------------------------

async function uploadFile(file, project) {
  if (!file.name.toLowerCase().endsWith('.osd')) {
    toast('That isn’t an Open Shot Designer .osd file.', 'bad');
    return;
  }
  const form = new FormData();
  form.append('file', file);
  await run('upload|', async () => {
    const res = project
      ? await api(`/api/projects/${enc(project)}/plan`, { method: 'POST', form })
      : await api('/api/projects', { method: 'POST', form });
    toast(project ? 'Plan updated.' : res.created ? `Added ${res.name}.` : `Updated ${res.name}.`);
    await refreshProjects();
    if (location.hash === `#/p/${enc(res.name)}`) loadProject({ quiet: true });
    else location.hash = `#/p/${enc(res.name)}`;
  });
}

document.addEventListener('click', async (event) => {
  const el = event.target.closest('[data-action]');
  if (!el || el.disabled) return;
  const a = el.dataset.action;
  const p = state.project?.name;
  if (a === 'stack') {
    run('stack|', () => api(`/api/stack/${el.dataset.do}`, { method: 'POST' })).then(() => setTimeout(refreshStatus, 800));
  } else if (a === 'osd-setup') {
    run('osd|', () => api('/api/osd/setup', { method: 'POST' }));
  } else if (a === 'blender-install') {
    run('blender|', () => api('/api/blender/install', { method: 'POST' }));
  } else if (a === 'project' && p) {
    const action = el.dataset.do;
    const body = action === 'pull' ? state.pull : {};
    run(`${action}|${p}`, () => api(`/api/projects/${enc(p)}/actions/${action}`, { method: 'POST', body }));
  } else if (a === 'reveal' && p) {
    api(`/api/projects/${enc(p)}/reveal`, { method: 'POST', body: { target: el.dataset.target } }).catch((e) => toast(e.message, 'bad'));
  } else if (a === 'upload') {
    state.uploadTarget = el.dataset.project || null;
    $('#file').value = '';
    $('#file').click();
  } else if (a === 'copy') {
    try {
      await navigator.clipboard.writeText(el.dataset.value);
      toast('Copied.');
    } catch {
      toast('Copy failed; select the text instead.', 'bad');
    }
  } else if (a === 'toggle-activity') {
    state.activityOpen = !state.activityOpen;
    renderActivity();
    pollJobs();
  } else if (a === 'select-job') {
    event.stopPropagation();
    state.selectedJob = Number(el.dataset.id);
    state.log = { id: null, lines: [], offset: 0 };
    pollJobs();
  } else if (a === 'menu') {
    document.body.classList.toggle('nav-open');
  } else if (a === 'zoom') {
    const box = $('#lightbox');
    box.innerHTML = `<img src="${esc(el.dataset.src)}" alt=""><div class="cap">${esc(el.dataset.cap)}</div>`;
    box.hidden = false;
  }
});

document.addEventListener('change', (event) => {
  const el = event.target;
  if (el.id === 'file' && el.files[0]) uploadFile(el.files[0], state.uploadTarget);
  if (el.dataset.bind) state.pull[el.dataset.bind] = el.value;
});

$('#lightbox').addEventListener('click', () => { $('#lightbox').hidden = true; });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#lightbox').hidden = true; });

// Drop an .osd anywhere to add it (or update the open project's plan when it's the same film).
let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
window.addEventListener('dragenter', (e) => { if (hasFiles(e)) { dragDepth += 1; $('#drop').hidden = false; } });
window.addEventListener('dragleave', (e) => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; $('#drop').hidden = true; } });
window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener('drop', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $('#drop').hidden = true;
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file, null);
});

// -- start ---------------------------------------------------------------------------------------

async function start() {
  window.addEventListener('hashchange', onRoute);
  renderActivity();
  [state.status, state.settings, state.projects] = await Promise.all([
    api('/api/status').catch(() => null), api('/api/settings').catch(() => null), api('/api/projects').catch(() => []),
  ]);
  if (state.settings) seedOpenShotDesigner(state.settings);
  await onRoute();
  pollJobs();
  setInterval(refreshStatus, 3000);
  setInterval(refreshProjects, 5000);
  setInterval(tickTimes, 15000);
  setInterval(() => {
    if (state.route.view === 'project' && state.status?.stack.kitsu.up) loadTracking(state.route.name);
  }, 15000);
}

start();
