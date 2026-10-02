// 画面遷移(状態機械)とメインロジック。
import { config, applyConfig } from './config.js';
import { api, log } from './api.js';
import { unlockAudio, playHangupTone } from './audio.js';
import { Recorder } from './recorder.js';
import { Ringtone } from './ringtone.js';
import { CallPlayer, startWave } from './player.js';
import { speak, fallbackScript } from './fallback.js';
import { detectReply } from './reply.js';
import { Ambient } from './ambient.js';

const $ = (id) => document.getElementById(id);
const vibrate = (p) => { try { if (navigator.vibrate && (!navigator.userActivation || navigator.userActivation.hasBeenActive)) navigator.vibrate(p); } catch (e) {} };
const fmt = (s) => { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };

// ---------- 状態 ----------
const S = {
  run: 0, screen: 'idle', ready: false,
  sessionId: null, sessionPromise: null,
  status: null, fallback: false,
  recorder: null, ringtone: null, player: null, speech: null, stopWave: null, reply: null, ambient: null,
  timers: new Set(), intervals: new Set(), pollTimer: null,
  connectStart: 0, callStart: 0, ringLogged: false, level: 0, t0: performance.now(),
};

const after = (fn, ms) => { const id = setTimeout(() => { S.timers.delete(id); fn(); }, ms); S.timers.add(id); return id; };
const every = (fn, ms) => { const id = setInterval(fn, ms); S.intervals.add(id); return id; };
const clearAllTimers = () => {
  S.timers.forEach(clearTimeout); S.timers.clear();
  S.intervals.forEach(clearInterval); S.intervals.clear();
  clearTimeout(S.pollTimer); S.pollTimer = null;
};

function show(name) {
  S.screen = name;
  const key = name === 'missed' ? 'ringing' : name;
  document.querySelectorAll('.screen').forEach((el) => el.classList.toggle('active', el.id === 'screen-' + key));
  document.body.dataset.screen = name;
}

// ---------- 後始末 ----------
function cleanupAll() {
  S.run++;
  clearAllTimers();
  if (S.recorder) { S.recorder.cancel(); S.recorder = null; }
  if (S.ringtone) { S.ringtone.stop(); S.ringtone = null; }
  if (S.player) { S.player.stop(); S.player = null; }
  if (S.speech) { S.speech.cancel(); S.speech = null; }
  if (S.stopWave) { S.stopWave(); S.stopWave = null; }
  stopReplyWait();
  if (S.ambient) { S.ambient.stop(true); S.ambient = null; }
  vibrate(0);
  try { window.speechSynthesis && speechSynthesis.cancel(); } catch (e) {}
  $('ring-phone').classList.remove('shake');
  const sid = S.sessionId;
  S.pollInFlight = false; S.sessionId = null; S.sessionPromise = null; S.status = null; S.fallback = false; S.ringLogged = false;
  if (sid) api.deleteSession(sid).catch(() => {});
}

function goIdle() {
  cleanupAll();
  show('idle');
  updateStartButton();
}

// ---------- 待機 ----------
function updateStartButton() {
  const b = $('btn-start');
  b.disabled = !S.ready;
  b.textContent = S.ready ? 'はじめる' : '準備中…';
}

async function healthLoop() {
  let ok = false;
  try { const h = await api.health(); ok = !!h.ready; } catch (e) { ok = false; }
  S.ready = ok;
  if (S.screen === 'idle') updateStartButton();
  setTimeout(healthLoop, ok ? 5000 : 1500);
}

$('btn-start').addEventListener('click', async () => {
  if (!S.ready) return;
  await unlockAudio();
  goConsent();
});

// ---------- 同意 ----------
function goConsent() {
  cleanupAll();
  show('consent');
  const run = S.run;
  const arm = () => {
    clearTimeout(S.consentTimer);
    S.consentTimer = after(() => { if (S.run === run) goIdle(); }, config.consent_idle_sec * 1000);
  };
  arm();
  $('screen-consent').onpointerdown = arm;
}
$('btn-consent-no').addEventListener('click', goIdle);
$('btn-consent-yes').addEventListener('click', () => {
  $('screen-consent').onpointerdown = null;
  clearAllTimers();
  S.sessionPromise = api.createSession().then((r) => (S.sessionId = r.session_id)).catch(() => null);
  goRecord();
});

// ---------- 録音 ----------
const METER_N = 24;
(function buildMeter() {
  const m = $('rec-meter');
  for (let i = 0; i < METER_N; i++) { const b = document.createElement('i'); b.style.setProperty('--n', i); m.appendChild(b); }
})();

function setRecState(st) { $('screen-record').dataset.state = st; }

function goRecord() {
  const run = S.run;
  show('record');
  setRecState('ready');
  $('rec-error').textContent = '';
  $('rec-msg').textContent = '';
  $('rec-max').textContent = fmt(config.record_max_sec);
  $('rec-minmark').style.left = (config.record_min_sec / config.record_max_sec * 100) + '%';
  // 録音画面で長時間放置された場合も待機へ
  after(() => { if (S.run === run && S.screen === 'record' && !S.recorder) goIdle(); }, Math.max(90, config.consent_idle_sec) * 1000);
}

$('btn-rec-start').addEventListener('click', async () => {
  if (S.recorder) return;
  const run = S.run;
  const rec = new Recorder();
  S.recorder = rec;
  S.level = 0;
  try {
    await rec.start((rms) => { S.level = rms; });
  } catch (e) {
    rec.cancel();
    if (S.run === run) S.recorder = null;
    log('client_error');
    $('rec-error').textContent = 'マイクが つかえないみたい。スタッフの ひとに つたえてね。';
    return;
  }
  if (S.run !== run) { rec.cancel(); return; }
  clearAllTimers();
  log('record_start');
  setRecState('rec');
  $('rec-msg').textContent = '';
  let lowSince = 0, shortUntil = 0;
  const meter = $('rec-meter').children;
  every(() => {
    if (S.run !== run || !S.recorder) return;
    const el = S.recorder.elapsed;
    $('rec-elapsed').textContent = fmt(el);
    $('rec-progress').style.width = Math.min(100, el / config.record_max_sec * 100) + '%';
    $('screen-record').classList.toggle('past-min', el >= config.record_min_sec);
    const lv = Math.min(1, Math.sqrt(S.level) * 1.6);
    const on = Math.round(lv * METER_N);
    for (let i = 0; i < METER_N; i++) meter[i].classList.toggle('on', i < on);
    const now = performance.now();
    if (el > 1 && S.level < config.low_volume_threshold) { if (!lowSince) lowSince = now; } else lowSince = 0;
    if (now < shortUntil) {
      $('rec-msg').textContent = 'もう少し詳しく教えてください';
    } else if (lowSince && now - lowSince > 2500) {
      $('rec-msg').textContent = 'マイクに近づいて話してね';
    } else {
      $('rec-msg').textContent = '';
    }
    if (el >= config.record_max_sec) submitRecording(true);
  }, 100);
  S.shortMsg = () => { shortUntil = performance.now() + 3500; };
});

async function submitRecording(auto) {
  const rec = S.recorder;
  if (!rec) return;
  if (!auto && rec.elapsed < config.record_min_sec) { S.shortMsg && S.shortMsg(); return; }
  S.recorder = null;
  const { blob, durationSec } = rec.stop();
  log('record_submit');
  goConnecting(blob, durationSec);
}
$('btn-rec-send').addEventListener('click', () => submitRecording(false));

$('btn-rec-redo').addEventListener('click', () => {
  if (S.recorder) { S.recorder.cancel(); S.recorder = null; }
  clearAllTimers();
  goRecord();
});

// ---------- 接続中 ----------
const STEP_PCT = { upload: 12, stt: 32, story: 58, tts: 82, done: 100 };

async function goConnecting(blob, durationSec) {
  const run = S.run;
  show('connecting');
  clearAllTimers();
  $('conn-progress').style.width = '5%';
  S.connectStart = performance.now();
  let sid = null;
  try {
    sid = await S.sessionPromise;
    if (!sid) { sid = (await api.createSession()).session_id; S.sessionId = sid; }
    let lastErr = null;
    for (let i = 0; i < 3; i++) {
      try { await api.uploadRecording(sid, blob, durationSec); lastErr = null; break; }
      catch (e) { lastErr = e; if (e.status === 404) { if (S.run === run) goIdle(); return; } await new Promise((r) => setTimeout(r, 800)); }
    }
    if (lastErr) throw lastErr;
  } catch (e) {
    if (S.run !== run) return;
    log('client_error');
    startFallbackRing();
    return;
  }
  if (S.run !== run) return;
  $('conn-progress').style.width = STEP_PCT.upload + '%';
  poll(run);
}

function startFallbackRing() {
  S.fallback = true;
  clearTimeout(S.pollTimer);
  goRinging();
}

function armPoll(run) {
  if (S.pollInFlight || S.pollTimer || S.fallback || !S.sessionId) return;
  S.pollTimer = setTimeout(() => { S.pollTimer = null; poll(run); }, config.status_poll_ms);
}

async function poll(run) {
  if (S.run !== run || !S.sessionId) return;
  S.pollInFlight = true;
  if (S.screen === 'connecting' && (performance.now() - S.connectStart) / 1000 > config.max_wait_sec) {
    log('client_error');
    startFallbackRing();
    return;
  }
  try {
    const st = await api.status(S.sessionId);
    S.pollInFlight = false;
    if (S.run !== run) return;
    S.status = st;
    onStatus(st);
  } catch (e) {
    S.pollInFlight = false;
    if (S.run !== run) return;
    if (e.status === 404) { goIdle(); return; }
  }
  S.pollInFlight = false;
  if (S.run === run) armPoll(run);
}

function onStatus(st) {
  if (S.screen === 'connecting') {
    const pct = STEP_PCT[st.step];
    if (pct) $('conn-progress').style.width = pct + '%';
  }
  if (st.phase === 'ready' && st.playback !== 'browser_tts' && !S.player && !S.fallback) {
    S.player = new CallPlayer(S.sessionId, config.call_volume);
  }
  if (S.player) S.player.update(st);
  if (st.phase === 'ready' && S.screen === 'connecting') {
    $('conn-progress').style.width = '100%';
    after(() => goRinging(), 400);
  }
}

// ---------- 着信 ----------
function goRinging() {
  const run = S.run;
  show('ringing');
  $('ring-caller').textContent = config.caller_name;
  $('ring-state').textContent = 'ちゃくしん';
  $('ring-sub').textContent = 'でんわに でてね';
  $('btn-answer').style.visibility = 'visible';
  document.querySelector('#screen-ringing .avatar').classList.add('pulse');
  if (!S.ringLogged) { log('ring_start'); S.ringLogged = true; }
  const phone = $('ring-phone');
  phone.classList.add('shake');
  if (!S.ringtone) S.ringtone = new Ringtone(config.ringtone_volume);
  try { S.ringtone.start(); } catch (e) { log('client_error'); }
  const buzz = () => vibrate([400, 200, 400, 200, 400]);
  buzz();
  every(buzz, 2400);
  after(() => { if (S.run === run && S.screen === 'ringing') goMissed(); }, config.ring_timeout_sec * 1000);
}

function goMissed() {
  const run = S.run;
  if (S.ringtone) { S.ringtone.stop(); S.ringtone = null; }
  clearAllTimers();
  armPoll(run);
  vibrate(0);
  $('ring-phone').classList.remove('shake');
  show('missed');
  $('ring-state').textContent = '不在着信';
  $('ring-sub').textContent = 'もういちど かかってくるよ';
  $('btn-answer').style.visibility = 'hidden';
  document.querySelector('#screen-ringing .avatar').classList.remove('pulse');
  log('missed_call');
  after(() => { if (S.run === run) goRinging(); }, config.missed_call_display_sec * 1000);
}

$('btn-answer').addEventListener('click', () => {
  if (S.screen !== 'ringing') return;
  if (S.ringtone) { S.ringtone.stop(); S.ringtone = null; }
  clearAllTimers();
  armPoll(S.run);
  vibrate(0);
  $('ring-phone').classList.remove('shake');
  log('answer');
  goCall();
});

// ---------- 返事待ち(疑似的なやりとり) ----------
function stopReplyWait() {
  if (S.reply) { S.reply.cancel(); S.reply = null; }
  const el = $('call-listen'); if (el) el.classList.remove('on');
}

// 返事の検知を始める。検知が終わったら(または失敗しても固定待ちの後)resume を呼ぶ。
function beginReplyWait(run, resume) {
  stopReplyWait();
  $('call-listen').classList.add('on');
  const r = detectReply(config);
  S.reply = r;
  r.promise.then((why) => {
    if (S.run !== run || S.reply !== r) return;
    S.reply = null;
    $('call-listen').classList.remove('on');
    resume();
  });
}

// ---------- 通話 ----------
function goCall() {
  const run = S.run;
  show('call');
  $('call-caller').textContent = config.caller_name;
  $('call-timer').textContent = '0:00';
  S.callStart = performance.now();
  if (config.ambient_enabled) {
    try { S.ambient = new Ambient({ volume: config.ambient_volume, file: config.ambient_file }); S.ambient.start(); } catch (e) { S.ambient = null; }
  }
  every(() => { $('call-timer').textContent = fmt((performance.now() - S.callStart) / 1000); }, 250);

  const st = S.status;
  const startSpeech = (sentences, waitAfter = []) => {
    if (S.player) { S.player.stop(); S.player = null; }
    stopReplyWait();
    S.speech = speak(sentences, {
      volume: config.call_volume,
      waitAfter: config.reply_wait_enabled ? waitAfter : [],
      onWait: (resume) => { if (S.run === run) beginReplyWait(run, resume); },
      onDone: () => { if (S.run === run) endCall(); },
    });
    if (S.stopWave) S.stopWave();
    S.stopWave = startWave($('wave'), () => (S.reply ? S.reply.getAnalyser() : null));
  };
  const startFallback = () => { const f = fallbackScript(config.future_years); startSpeech(f.sentences, f.waitAfter); };

  if (S.fallback) {
    startFallback();
    return;
  }
  if (st && st.playback === 'browser_tts' && Array.isArray(st.sentences) && st.sentences.length) {
    startSpeech(st.sentences, Array.isArray(st.wait_after) ? st.wait_after : []);
    return;
  }
  if (!S.player) S.player = new CallPlayer(S.sessionId, config.call_volume);
  if (st) S.player.update(st);
  S.player.start();
  S.stopWave = startWave($('wave'), () => (S.reply && S.reply.getAnalyser()) || (S.player ? S.player.analyser : null));
  every(() => {
    const p = S.player;
    if (S.run !== run || !p) return;
    if (p.waitDue()) {
      p.waiting = true;
      beginReplyWait(run, () => { if (S.run === run && S.player === p) p.resume(); });
      return;
    }
    if (p.finished()) { playHangupTone(config.call_volume); endCall(); return; }
    const sinceAnswer = performance.now() - S.callStart;
    if (!p.hasScheduled && sinceAnswer > 20000) {
      // 音声が取得できない: 最終フォールバック
      log('client_error');
      S.fallback = true; clearTimeout(S.pollTimer);
      startFallback();
    } else if (p.hasScheduled && p.stalledMs() > (p.allDone ? 30000 : (config.max_wait_sec || 200) * 1000)) {
      // 生成が続いている間は、次のパートを待って切らない(上限は生成の上限秒数まで)
      endCall();
    }
  }, 300);
}
$('btn-hangup').addEventListener('click', () => { if (S.screen === 'call') endCall(); });

function endCall() {
  if (S.screen !== 'call') return;
  const dur = (performance.now() - S.callStart) / 1000;
  log('call_end', dur * 1000);
  clearAllTimers();
  if (S.player) { S.player.stop(); S.player = null; }
  if (S.speech) { S.speech.cancel(); S.speech = null; }
  if (S.stopWave) { S.stopWave(); S.stopWave = null; }
  stopReplyWait();
  if (S.ambient) { S.ambient.stop(); S.ambient = null; }
  try { window.speechSynthesis && speechSynthesis.cancel(); } catch (e) {}
  goEnd(dur);
}

// ---------- 終話 ----------
function goEnd(dur) {
  const run = S.run;
  show('end');
  $('end-duration').textContent = fmt(dur);
  after(() => { if (S.run === run) goIdle(); }, config.end_screen_sec * 1000);
}

// ---------- スタッフ用リセット (F-60) ----------
async function staffReset() {
  log('staff_reset');
  cleanupAll();
  try { await api.reset(); } catch (e) { /* ignore */ }
  goIdle();
}
(function setupStaff() {
  const hot = $('staff-hotspot');
  let timer = null;
  const cancel = () => { clearTimeout(timer); timer = null; };
  hot.addEventListener('pointerdown', (e) => {
    e.preventDefault(); cancel();
    timer = setTimeout(() => { timer = null; staffReset(); }, config.staff_reset_hold_ms);
  });
  ['pointerup', 'pointercancel', 'pointerleave'].forEach((ev) => hot.addEventListener(ev, cancel));
  let escTimer = null;
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !escTimer) escTimer = setTimeout(() => { escTimer = null; staffReset(); }, config.staff_reset_hold_ms);
    if ((e.ctrlKey || e.metaKey) && ['+', '-', '=', '0'].includes(e.key)) e.preventDefault();
  });
  window.addEventListener('keyup', (e) => { if (e.key === 'Escape') { clearTimeout(escTimer); escTimer = null; } });
})();

// ---------- ブラウザ挙動の抑止 ----------
['contextmenu', 'selectstart', 'dragstart', 'gesturestart', 'gesturechange'].forEach((ev) =>
  document.addEventListener(ev, (e) => e.preventDefault()));
document.addEventListener('wheel', (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });
document.addEventListener('touchmove', (e) => e.preventDefault(), { passive: false });
window.addEventListener('error', () => log('client_error'));
window.addEventListener('unhandledrejection', () => log('client_error'));

// ---------- 起動 ----------
(async function boot() {
  try { applyConfig(await api.config()); } catch (e) { /* 既定値 */ }
  goIdle();
  healthLoop();
})();
