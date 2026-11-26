'use strict';
// Machine Chess Arena web UI. All dynamic text goes through textContent (LLM replies are untrusted).

const GLYPH = {K:'♚', Q:'♛', R:'♜', B:'♝', N:'♞', P:'♟'};
const VALUE = {P:1, N:3, B:3, R:5, Q:9, K:0};
const START_COUNT = {P:8, N:2, B:2, R:2, Q:1};
const STD_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
let INFO = null;   // /api/info: the configured players (live tab)
const $ = id => document.getElementById(id);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
const svgNS = 'http://www.w3.org/2000/svg';
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}

// ---------------------------------------------------------------- game model
// G.moves[i] is ply i+1. G.view is the ply being displayed (0 = start position).
const blankGame = () => ({
  startFen: STD_FEN, white: 'White', black: 'Black', moves: [], view: 0, flipped: false,
  clocks: {white: null, black: null}, evals: null, comments: [], over: null,
  handicap: '', chess960: false, gameId: null,
});
// LIVE is fed by the WebSocket; REPLAY holds whichever saved game is open. G is the one on screen.
const LIVE = blankGame(), REPLAY = blankGame();
let G = LIVE;

function resetGame(target, over = {}) {
  const keepFlip = target.flipped;
  Object.assign(target, blankGame(), {flipped: keepFlip}, over);
}
const fenAt = ply => ply === 0 ? G.startFen : G.moves[ply - 1].fen_after;

function parseBoard(fen) {
  const grid = [];
  for (const row of fen.split(' ')[0].split('/')) {
    const r = [];
    for (const ch of row) { if (/\d/.test(ch)) for (let i = 0; i < +ch; i++) r.push(null); else r.push(ch); }
    grid.push(r);
  }
  return grid;
}
function counts(fen) {
  const c = {w: {}, b: {}};
  for (const row of parseBoard(fen)) for (const p of row) if (p) {
    const side = p === p.toUpperCase() ? 'w' : 'b', k = p.toUpperCase();
    c[side][k] = (c[side][k] || 0) + 1;
  }
  return c;
}
const material = c => Object.entries(c).reduce((a, [k, n]) => a + VALUE[k] * n, 0);

// ---------------------------------------------------------------- who is playing
const prettyModel = m => {
  const x = /^claude-([a-z]+)-(\d+)-(\d+)$/.exec(m || '');
  return x ? `Claude ${x[1][0].toUpperCase() + x[1].slice(1)} ${x[2]}.${x[3]}` : (m || 'LLM');
};
// Works from a saved-game name alone (replays) or, on the live tab, from the full player config.
function describe(raw, cfg) {
  const name = raw || '';
  const type = cfg ? cfg.type : /^stockfish/.test(name) ? 'stockfish' : name === 'random' ? 'random' : name === 'greedy' ? 'greedy' : 'llm';
  const coach = cfg ? cfg.coach : /\+coach$/.test(name);
  if (type === 'stockfish') {
    const lvl = cfg ? cfg.skill_level : (/lvl(\d+)/.exec(name) || [])[1], elo = cfg ? cfg.elo : (/elo(\d+)/.exec(name) || [])[1];
    return {kind: 'Engine', title: 'Stockfish', detail: elo ? `Elo ${elo}` : lvl != null ? `Skill level ${lvl} / 20` : 'Full strength'};
  }
  if (type === 'random') return {kind: 'Baseline', title: 'Random', detail: 'Any legal move'};
  if (type === 'greedy') return {kind: 'Baseline', title: 'Greedy', detail: 'Takes the best capture'};
  const model = cfg ? cfg.model : name.replace(/\+coach$/, '');
  const bits = [cfg && cfg.personality, coach ? 'Stockfish coach' : null].filter(Boolean);
  return {kind: 'LLM', title: (cfg && cfg.name) || prettyModel(model), detail: bits.length ? bits.join(' · ') : 'Language model'};
}
const sideInfo = side => {
  const raw = G[side], cfg = G === LIVE && INFO ? INFO[side] : null;
  return describe(raw === 'White' || raw === 'Black' ? '' : raw, cfg);
};

function drawMatchup() {
  const el = $('matchup'), res = G.over && G.over.result;
  const turn = G.view < G.moves.length || !G.over ? fenAt(G.view).split(' ')[1] : null;
  const half = side => {
    const i = sideInfo(side), mine = side === 'white' ? 'w' : 'b';
    const won = res === (side === 'white' ? '1-0' : '0-1'), lost = res === (side === 'white' ? '0-1' : '1-0');
    const live = !res && turn === mine && (G !== LIVE || G.moves.length > 0 || G.started);
    return h('div', {class: `mside ${side}${won ? ' won' : ''}${lost ? ' lost' : ''}${live ? ' turn' : ''}`},
      h('span', {class: `dot ${mine}`}),
      h('div', {class: 'minfo'},
        h('div', {class: 'mtitle'}, i.title),
        h('div', {class: 'mdetail'}, h('span', {class: 'kind'}, i.kind), i.detail)),
      won ? h('span', {class: 'winmark', title: 'Winner'}, '✓') : null);
  };
  const centre = res ? ({'1-0': '1 – 0', '0-1': '0 – 1', '1/2-1/2': '½ – ½'}[res] || res) : 'vs';
  const sub = res ? G.over.reason.replaceAll('_', ' ') : (G.moves.length ? `Move ${Math.ceil(G.view / 2) || 1}` : (G === LIVE ? 'Ready' : ''));
  el.replaceChildren(half('white'),
    h('div', {class: 'mcentre'}, h('div', {class: 'mscore' + (res ? ' final' : '')}, centre), h('div', {class: 'msub'}, sub)),
    half('black'));
}

// ---------------------------------------------------------------- rendering
function evalAt(ply) {
  if (G.evals && G.evals[ply] !== undefined) return G.evals[ply];
  for (let i = ply; i >= 1; i--) {
    const e = G.moves[i - 1] && G.moves[i - 1].info && G.moves[i - 1].info.eval_cp;
    if (e !== undefined && e !== null) return e;
  }
  return null;
}
function fmtClock(sec) {
  if (sec == null) return '';
  sec = Math.max(0, Math.round(sec));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}
function clockAt(side, ply) {
  for (let i = ply; i >= 1; i--) {
    const m = G.moves[i - 1];
    if (m.side === side && m.info && m.info.clock_left !== undefined) return m.info.clock_left;
  }
  return G.clocks[side];
}

function drawBoard() {
  const board = $('board'); board.replaceChildren();
  const grid = parseBoard(fenAt(G.view));
  const last = G.view > 0 ? G.moves[G.view - 1].uci : null;
  const hl = new Set(last ? [last.slice(0, 2), last.slice(2, 4)] : []);
  const rows = [...Array(8).keys()], files = [...Array(8).keys()];
  if (G.flipped) { rows.reverse(); files.reverse(); }
  rows.forEach((r, ri) => files.forEach((f, fi) => {
    const sq = 'abcdefgh'[f] + (8 - r), p = grid[r][f];
    const el = h('div', {class: `sq ${(f + r) % 2 ? 'd' : 'l'}${hl.has(sq) ? ' hl' : ''}`});
    if (fi === 7) el.append(h('span', {class: 'coord r'}, String(8 - r)));
    if (ri === 7) el.append(h('span', {class: 'coord f'}, 'abcdefgh'[f]));
    if (p) el.append(h('span', {class: `piece ${p === p.toUpperCase() ? 'w' : 'b'}`}, GLYPH[p.toUpperCase()] + '︎'));
    board.append(el);
  }));
}

function playerBar(el, side) {
  const fen = fenAt(G.view), now = counts(fen), start = counts(G.startFen);
  const enemy = side === 'white' ? 'b' : 'w', mine = side === 'white' ? 'w' : 'b';
  // pieces this side has captured = enemy pieces missing compared with the start position
  let caps = '';
  for (const k of ['Q', 'R', 'B', 'N', 'P']) {
    const lost = Math.max(0, (start[enemy][k] || 0) - (now[enemy][k] || 0));
    caps += (GLYPH[k] + '︎').repeat(lost);
  }
  const diff = material(now[mine]) - material(now[enemy]);
  const clock = clockAt(side, G.view);
  const toMove = fen.split(' ')[1] === (side === 'white' ? 'w' : 'b') && !G.over;
  el.replaceChildren(...[
    h('span', {class: `dot ${mine}`}),
    h('span', {class: 'pname'}, sideInfo(side).title),
    h('span', {class: 'caps'}, caps, diff > 0 ? h('span', {class: 'adv'}, `+${diff}`) : null),
    clock != null ? h('span', {class: 'clock' + (clock < 30 ? ' low' : ''), title: toMove ? 'to move' : ''},
      (toMove ? '▸ ' : '') + fmtClock(clock)) : null].filter(Boolean));
}

function drawEval() {
  const cp = evalAt(G.view);
  $('evalfill').style.height = cp == null ? '50%' : (100 / (1 + Math.exp(-cp / 400))) + '%';
  $('evaltext').textContent = cp == null ? '' : (Math.abs(cp) >= 9000 ? 'M' : (cp / 100).toFixed(1));
}

function drawGraph() {
  const g = $('graph'); g.replaceChildren();
  const n = G.moves.length, pts = [];
  for (let i = 0; i <= n; i++) { const e = evalAt(i); if (e !== null) pts.push([i, e]); }
  $('graphnote').textContent = pts.length < 2 ? 'No evaluations yet (Stockfish players report them live; use “Analyse” on saved games).' : '';
  g.append(s('line', {x1: 0, x2: 300, y1: 35, y2: 35, stroke: 'currentColor', 'stroke-opacity': .25, 'stroke-width': .5}));
  if (pts.length >= 2) {
    const X = i => (i / Math.max(1, n)) * 300, Y = e => 35 - Math.max(-1, Math.min(1, Math.tanh(e / 500))) * 33;
    const line = pts.map(([i, e]) => `${X(i).toFixed(1)},${Y(e).toFixed(1)}`).join(' ');
    g.append(s('polygon', {points: `${X(pts[0][0])},35 ${line} ${X(pts[pts.length - 1][0])},35`, fill: 'currentColor', 'fill-opacity': .12}));
    g.append(s('polyline', {points: line, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.4, 'vector-effect': 'non-scaling-stroke'}));
  }
  g.append(s('line', {x1: (G.view / Math.max(1, n)) * 300, x2: (G.view / Math.max(1, n)) * 300, y1: 0, y2: 70,
    stroke: '#a63d32', 'stroke-width': 1.2, 'vector-effect': 'non-scaling-stroke'}));
}

function drawMoves() {
  const el = $('moves'); el.replaceChildren();
  G.moves.forEach((m, i) => {
    if (i % 2 === 0) el.append(h('span', {class: 'n'}, `${i / 2 + 1}.`));
    const cls = ['mv'];
    if (G.view === i + 1) cls.push('cur');
    if (m.retries) cls.push('warn');
    if (m.fallback) cls.push('fb');
    el.append(h('span', {class: cls.join(' '), title: m.retries ? `${m.retries} rejected attempt(s)` : '', onclick: () => goto(i + 1)}, m.san));
  });
  const cur = el.querySelector('.cur');
  if (cur) cur.scrollIntoView({block: 'nearest'}); else el.scrollTop = 0;
}

function drawDetail() {
  const el = $('detail'); el.replaceChildren();
  const m = G.view > 0 ? G.moves[G.view - 1] : null;
  if (!m) { el.append('Select a move.'); return; }
  const i = m.info || {}, kv = [];
  const add = (k, v) => v != null && v !== '' && kv.push(h('span', {}, `${k} `, h('b', {}, String(v))));
  add('Player', m.player || G[m.side]);
  add('Time', m.seconds != null ? m.seconds.toFixed(1) + 's' : null);
  add('Retries', m.retries || null);
  add('Tokens', i.input_tokens != null ? `${i.input_tokens}→${i.output_tokens}` : null);
  add('Cost', i.cost_usd != null ? '$' + i.cost_usd.toFixed(4) : null);
  add('Engine calls', i.tool_calls);
  add('Eval', i.eval_cp != null ? (i.eval_cp / 100).toFixed(2) : null);
  if (m.fallback) add('Fallback', 'random move');
  el.append(h('div', {class: 'kv'}, kv), h('pre', {}, i.raw_reply || '(this player gives no reasoning)'));
}

function drawCommentary() {
  const el = $('commentary'); el.replaceChildren();
  const shown = G.comments.filter(c => c.ply <= G.view || c.kind === 'summary' && G.over && G.view >= G.moves.length);
  if (!shown.length) { el.append('—'); return; }
  for (const c of shown) el.append(h('div', {class: 'cm'}, h('span', {class: 'ply'}, c.kind === 'summary' ? 'final' : `ply ${c.ply}`), c.text));
  el.scrollTop = el.scrollHeight;
}

function render() {
  drawBoard();
  const top = G.flipped ? 'white' : 'black';
  playerBar($('top-player'), top);
  playerBar($('bottom-player'), top === 'black' ? 'white' : 'black');
  drawMatchup(); drawEval(); drawGraph(); drawMoves(); drawDetail(); drawCommentary();
  $('b-first').disabled = $('b-prev').disabled = G.view === 0;
  $('b-next').disabled = $('b-last').disabled = G.view >= G.moves.length;
}

function setStatus(text, err) {
  const el = $('status'); el.textContent = text; el.className = err ? 'err' : '';
  $('pulse').className = 'pulse' + (err ? ' err' : G === LIVE && G.started && !G.over ? ' on' : '');
}
function gameOverText(g = G) { return g.over ? `Game over: ${g.over.result} (${g.over.reason.replaceAll('_', ' ')})` : ''; }

let autoTimer = null;
function stopAuto() { clearInterval(autoTimer); autoTimer = null; const b = $('b-auto'); if (b) b.textContent = 'Auto'; }
function toggleAuto() {
  if (autoTimer) return stopAuto();
  if (G.view >= G.moves.length) goto(0);
  $('b-auto').textContent = 'Pause';
  autoTimer = setInterval(() => { if (G.view >= G.moves.length) stopAuto(); else goto(G.view + 1); }, 800);
}
function goto(ply) {
  G.view = Math.max(0, Math.min(G.moves.length, ply));
  render();
}

// ---------------------------------------------------------------- live game (WebSocket)
let ws = null, tab = 'live';

function handleEvent(ev) {
  const L = LIVE;
  let msg = null, err = false;
  if (ev.type === 'GameStart') {
    // opening / resumed moves are already on the board: the viewer starts from the position after them
    resetGame(L, {started: true, startFen: ev.fen_now || ev.fen, white: ev.white, black: ev.black, handicap: ev.handicap || '',
      chess960: !!ev.chess960, clocks: ev.clock_seconds || {white: null, black: null}});
    const n = (ev.prior_moves || []).length;
    msg = n ? `Ready (${n} opening plies already played) — press Play` : 'Ready — press Play';
  } else if (ev.type === 'MoveEvent') {
    const following = L.view === L.moves.length;
    L.moves.push(ev);
    if (following) L.view = L.moves.length;
    msg = `Move ${Math.ceil(ev.ply / 2)} · ${ev.player} played ${ev.san}` + (ev.retries ? ` (retries: ${ev.retries})` : '');
  } else if (ev.type === 'Commentary') {
    L.comments.push(ev);
  } else if (ev.type === 'GameOver') {
    L.over = ev; msg = gameOverText(L); stopAuto();
  } else if (ev.type === 'Error') {
    msg = 'Error: ' + ev.message; err = true;
  }
  if (msg) { L.status = msg; L.statusErr = err; }
  if (G === L) { if (msg) setStatus(msg, err); badges(); render(); }
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = e => handleEvent(JSON.parse(e.data));
  ws.onclose = () => { LIVE.status = 'Disconnected from server'; LIVE.statusErr = true; if (G === LIVE && !LIVE.over) setStatus(LIVE.status, true); };
}
const send = (cmd, value) => ws && ws.readyState === 1 && ws.send(JSON.stringify({cmd, value}));

function badges() {
  const el = $('badges'); el.replaceChildren();
  if (G.chess960) el.append(h('span', {class: 'badge'}, 'Chess960'));
  if (G.handicap) el.append(h('span', {class: 'badge', title: G.handicap}, 'Handicap: ' + G.handicap));
}

// ---------------------------------------------------------------- saved games (replay)
let gameList = [];
async function loadGameList() {
  gameList = await (await fetch('/api/games')).json();
  drawGameList();
}
function drawGameList() {
  const q = $('filter').value.toLowerCase(), el = $('gamelist'); el.replaceChildren();
  const shown = gameList.filter(g => `${g.white} ${g.black} ${g.date} ${g.id}`.toLowerCase().includes(q));
  if (!shown.length) el.append(h('div', {class: 'muted'}, gameList.length ? 'No matches.' : 'No saved games yet.'));
  for (const g of shown) {
    el.append(h('div', {class: 'gitem' + (G.gameId === g.id ? ' sel' : ''), onclick: () => openGame(g.id)},
      h('div', {class: 'vs'}, `${g.white} – ${g.black}`),
      h('div', {class: 'meta'}, `${g.result} · ${g.termination.replaceAll('_', ' ')} · ${g.date}${g.variant ? ' · ' + g.variant : ''}`)));
  }
}
async function openGame(id) {
  const r = await fetch('/api/games/' + id.split('/').map(encodeURIComponent).join('/'));
  if (!r.ok) { setStatus('Could not load game', true); return; }
  const d = await r.json();
  resetGame(REPLAY, {startFen: d.start_fen, white: d.headers.White || 'White', black: d.headers.Black || 'Black',
    moves: d.moves, gameId: id, comments: d.commentary, chess960: d.chess960, handicap: d.headers.Handicap || '',
    evals: d.analysis ? d.analysis.evals : null,
    over: {result: d.headers.Result || '*', reason: d.headers.Termination || 'finished'}});
  showTab('games', true);
  history.replaceState(null, '', '#game=' + encodeURIComponent(id));
  badges();
  setStatus(`${G.white} vs ${G.black} — ${gameOverText().replace('Game over: ', '')}`);
  $('analysenote').textContent = d.analysis ? summarise(d.analysis) : '';
  drawGameList(); render();
}
const summarise = a => `Accuracy W ${a.white.accuracy.toFixed(0)} / B ${a.black.accuracy.toFixed(0)} · blunders ${a.white.blunders}/${a.black.blunders}`;

async function analyse() {
  if (!G.gameId) return;
  $('analysenote').textContent = 'Analysing…'; $('analyse').disabled = true;
  try {
    const r = await fetch('/api/games/' + G.gameId.split('/').map(encodeURIComponent).join('/') + '/analysis');
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const a = await r.json();
    G.evals = a.evals; $('analysenote').textContent = summarise(a); render();
  } catch (e) { $('analysenote').textContent = 'Analysis failed: ' + e.message; }
  $('analyse').disabled = false;
}

// ---------------------------------------------------------------- tournaments
async function loadTournaments() {
  const list = await (await fetch('/api/tournaments')).json(), el = $('tlist'); el.replaceChildren();
  if (!list.length) el.append(h('div', {class: 'muted'}, 'No tournaments found. Run `aichess tournament …` first.'));
  for (const t of list) {
    el.append(h('div', {class: 'titem', onclick: () => openTournament(t.id, el)},
      h('div', {}, t.id.split('/').pop()),
      h('div', {class: 'muted'}, `${t.format.replace('_', ' ')} · ${t.players} players · ${t.games} games · 🏆 ${t.winner}`)));
  }
  if (list.length) openTournament(list[0].id);
}

function eloPlot(standings) {
  const vals = standings.flatMap(x => [x.elo, x.elo_lo ?? x.elo, x.elo_hi ?? x.elo]);
  const lo = Math.min(...vals) - 30, hi = Math.max(...vals) + 30, W = 600, rowH = 26, H = rowH * standings.length + 24;
  const X = v => 150 + ((v - lo) / Math.max(1, hi - lo)) * (W - 170);
  const svg = s('svg', {viewBox: `0 0 ${W} ${H}`, class: 'eloplot'});
  standings.forEach((x, i) => {
    const y = 14 + i * rowH;
    svg.append(s('text', {x: 0, y: y + 4, fill: 'currentColor', 'font-size': 12}, x.name.slice(0, 22)));
    if (x.elo_lo != null) svg.append(s('line', {x1: X(x.elo_lo), x2: X(x.elo_hi), y1: y, y2: y, stroke: 'currentColor', 'stroke-opacity': .4, 'stroke-width': 2}));
    svg.append(s('circle', {cx: X(x.elo), cy: y, r: 5, fill: 'currentColor'}));
    svg.append(s('text', {x: X(x.elo) + 9, y: y - 7, fill: 'currentColor', 'font-size': 10}, Math.round(x.elo)));
  });
  return svg;
}

function crossTable(t) {
  const names = t.standings.map(x => x.name), cell = {};
  for (const g of t.games) {
    const sc = {'1-0': 1, '0-1': 0, '1/2-1/2': .5}[g.result]; if (sc === undefined) continue;
    for (const [a, b, p] of [[g.white, g.black, sc], [g.black, g.white, 1 - sc]]) {
      const c = (cell[a + '\u0000' + b] ||= {pts: 0, n: 0}); c.pts += p; c.n++;
    }
  }
  return h('table', {}, h('tr', {}, h('th', {}, ''), h('th', {}, ''), names.map((_, i) => h('th', {}, String(i + 1)))),
    names.map((a, i) => h('tr', {}, h('td', {}, String(i + 1)), h('td', {}, a), names.map(b => {
      const c = cell[a + '\u0000' + b];
      if (a === b || !c) return h('td', {}, a === b ? '·' : '');
      const f = c.pts / c.n;
      return h('td', {class: f > .5 ? 'win' : f < .5 ? 'loss' : 'draw', title: `${c.pts}/${c.n}`}, `${c.pts}/${c.n}`);
    }))));
}

async function openTournament(id) {
  const t = await (await fetch('/api/tournament/' + id.split('/').map(encodeURIComponent).join('/'))).json();
  document.querySelectorAll('.titem').forEach(e => e.classList.toggle('sel', e.firstChild.textContent === id.split('/').pop()));
  const rows = t.standings.map((x, i) => h('tr', {},
    h('td', {}, String(i + 1)), h('td', {}, x.name + (t.anchors && x.name in t.anchors ? ' *' : '')),
    h('td', {}, Math.round(x.elo) + (x.elo_lo != null ? ` (${Math.round(x.elo_lo)}–${Math.round(x.elo_hi)})` : '')),
    h('td', {}, String(x.points)), h('td', {}, String(x.games)), h('td', {}, String(x.wins)), h('td', {}, String(x.draws)), h('td', {}, String(x.losses))));
  const games = t.games.map((g, i) => h('tr', {},
    h('td', {}, String(g.round || 1)), h('td', {}, g.white), h('td', {}, g.black), h('td', {}, g.result),
    h('td', {}, g.reason.replaceAll('_', ' ')), h('td', {}, g.game_id ? h('span', {class: 'glink', onclick: () => openGame(g.game_id)}, 'replay') : '')));
  $('tdetail').replaceChildren(
    h('div', {class: 'card'}, h('div', {class: 'cardtitle'}, `Leaderboard · ${t.format.replace('_', ' ')}`),
      h('table', {}, h('tr', {}, ['#', 'Player', 'Elo (95% CI)', 'Pts', 'G', 'W', 'D', 'L'].map(x => h('th', {}, x))), rows),
      t.anchors && Object.keys(t.anchors).length ? h('div', {class: 'muted'}, '* anchored rating (known strength)') : null),
    h('div', {class: 'card'}, h('div', {class: 'cardtitle'}, 'Rating estimates'), eloPlot(t.standings)),
    h('div', {class: 'card'}, h('div', {class: 'cardtitle'}, 'Head to head (row’s points / games)'), crossTable(t)),
    h('div', {class: 'card'}, h('div', {class: 'cardtitle'}, 'Games'),
      h('table', {class: 'txt'}, h('tr', {}, ['Rd', 'White', 'Black', 'Result', 'Reason', ''].map(x => h('th', {}, x))), games)));
}

// ---------------------------------------------------------------- tabs, controls, keyboard
function showTab(name, keepGame) {
  tab = name; stopAuto();
  $('b-auto').classList.toggle('hidden', name !== 'games');
  $('matchup').classList.toggle('hidden', name === 'tournaments');
  if (!keepGame) history.replaceState(null, '', name === 'live' ? location.pathname : '#' + name);
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $('view-game').classList.toggle('hidden', name === 'tournaments');
  $('view-tournaments').classList.toggle('hidden', name !== 'tournaments');
  $('picker').classList.toggle('hidden', name !== 'games');
  $('view-game').classList.toggle('withpicker', name === 'games');
  $('livecontrols').classList.toggle('hidden', name !== 'live');
  $('replaycontrols').classList.toggle('hidden', name !== 'games');
  if (name === 'tournaments') { loadTournaments(); return; }
  G = name === 'live' ? LIVE : REPLAY;
  if (name === 'live') setStatus(LIVE.status || 'Connecting…', LIVE.statusErr);
  else { loadGameList(); if (!keepGame) setStatus(G.gameId ? `${G.white} vs ${G.black}` : 'Pick a saved game from the list'); }
  badges(); render();
}

document.querySelectorAll('.tab').forEach(b => b.onclick = () => showTab(b.dataset.tab));
$('b-first').onclick = () => goto(0);
$('b-prev').onclick = () => goto(G.view - 1);
$('b-next').onclick = () => goto(G.view + 1);
$('b-last').onclick = () => goto(G.moves.length);
$('b-auto').onclick = toggleAuto;
$('b-flip').onclick = () => { G.flipped = !G.flipped; render(); };
$('play').onclick = () => send('play');
$('pause').onclick = () => send('pause');
$('step').onclick = () => send('step');
$('analyse').onclick = analyse;
$('filter').oninput = drawGameList;
$('speed').oninput = e => { $('dv').textContent = (+e.target.value).toFixed(1); send('speed', +e.target.value); };
$('graph').onclick = e => {
  const r = e.currentTarget.getBoundingClientRect();
  goto(Math.round(((e.clientX - r.left) / r.width) * G.moves.length));
};
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || tab === 'tournaments') return;
  const k = {ArrowLeft: () => goto(G.view - 1), ArrowRight: () => goto(G.view + 1), Home: () => goto(0),
    End: () => goto(G.moves.length), ' ': () => tab === 'games' && toggleAuto(), f: () => { G.flipped = !G.flipped; render(); }}[e.key];
  if (k) { e.preventDefault(); k(); }
});

// live tab keeps its own game state; replays use the shared viewer, so snapshot/restore around tab switches
fetch('/api/info').then(r => r.json()).then(i => {
  INFO = i; render();
  if (!LIVE.moves.length) {
    LIVE.chess960 = i.chess960; if (i.material_odds) LIVE.handicap = 'material odds ' + i.material_odds;
    if (G === LIVE) badges();
  }
}).catch(() => {});
connect();
render();
(function route() {   // shareable links: #games, #tournaments, #game=<id>
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash.startsWith('game=')) openGame(hash.slice(5));
  else if (hash === 'games' || hash === 'tournaments') showTab(hash);
})();
