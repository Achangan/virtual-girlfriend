/* 虚拟女友前端：视频渲染层 + 聊天 + 衣橱换装 + 语音输入/播放 */
'use strict';

const LOOKS = window.PURPLE_LOOKS || [];
const DEFAULT_LOOK = '04';

// 情绪 -> 氛围光颜色
const EMOTION_GLOW = {
  happy: 'rgba(255, 209, 102, 0.35)',
  shy: 'rgba(255, 143, 171, 0.35)',
  tsundere: 'rgba(255, 158, 125, 0.35)',
  sad: 'rgba(108, 142, 191, 0.4)',
  angry: 'rgba(239, 71, 111, 0.4)',
  surprised: 'rgba(255, 214, 255, 0.35)',
  relaxed: 'rgba(144, 224, 160, 0.3)',
  calm: 'rgba(142, 202, 230, 0.25)',
};

const stage = document.getElementById('stage');
const edgeLight = document.getElementById('edgeLight');
const speakHint = document.getElementById('speakHint');
const messagesEl = document.getElementById('messages');
const textInput = document.getElementById('textInput');
const sendBtn = document.getElementById('sendBtn');
const micBtn = document.getElementById('micBtn');
const wardrobeBtn = document.getElementById('wardrobeBtn');
const wardrobeEl = document.getElementById('wardrobe');

let currentLook = null;
let lastState = null;

/* ---------- 形象层 ---------- */
function groupOf(id) {
  if (id.startsWith('sit-loop')) return '坐姿 · 循环';
  if (id.startsWith('sit')) return '坐姿';
  if (id.startsWith('recline')) return '躺姿';
  if (id.startsWith('classic')) return '经典';
  return '站姿';
}

function switchLook(look) {
  currentLook = look;
  stage.poster = `/assets/images/look-${look.id}.jpg`;
  stage.src = `/assets/media/1080p/look-${look.id}.webm`;
  stage.play().catch(() => {});
  document.querySelectorAll('.look-card').forEach(c =>
    c.classList.toggle('active', c.dataset.id === look.id));
}

// 定格模式：播放到 look.freeze 秒时暂停在那一帧
stage.addEventListener('timeupdate', () => {
  if (currentLook?.freeze && stage.currentTime >= currentLook.freeze) stage.pause();
});

// 她说话时重新播放一遍入场动作，制造"动起来回应你"的效果
function motionBurst() {
  if (!currentLook) return;
  stage.currentTime = 0;
  stage.play().catch(() => {});
}

function setEmotionGlow(emotion) {
  edgeLight.style.setProperty('--glow', EMOTION_GLOW[emotion] || EMOTION_GLOW.calm);
}

/* ---------- 衣橱 ---------- */
function buildWardrobe() {
  const groups = new Map();
  for (const look of LOOKS) {
    if (look.locked) continue; // 未开放穿搭没有素材，跳过避免 404
    const g = groupOf(look.id);
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(look);
  }
  wardrobeEl.innerHTML = '';
  for (const [name, looks] of groups) {
    const section = document.createElement('div');
    section.className = 'wardrobe-group';
    section.innerHTML = `<h3>${name}</h3>`;
    const grid = document.createElement('div');
    grid.className = 'look-grid';
    for (const look of looks) {
      const card = document.createElement('div');
      card.className = 'look-card';
      card.dataset.id = look.id;
      card.innerHTML =
        `<img src="/assets/images/thumb-${look.id}.jpg" onerror="this.src='/assets/images/look-${look.id}.jpg'">` +
        `<span>${look.name}</span>`;
      card.addEventListener('click', () => switchLook(look));
      grid.appendChild(card);
    }
    section.appendChild(grid);
    wardrobeEl.appendChild(section);
  }
}
wardrobeBtn.addEventListener('click', () => wardrobeEl.classList.toggle('hidden'));

/* ---------- 聊天 ---------- */
function addBubble(text, who) {
  const div = document.createElement('div');
  div.className = `msg ${who}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

const ws = new WebSocket(`ws://${location.host}/ws`);
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.type === 'state') {
    updateStatus(msg.state);
  } else if (msg.type === 'heard') {
    // 语音识别结果：立即回显你的话；空文本表示没听清
    if (msg.text) addBubble(msg.text, 'me');
    else {
      const moodEl = document.getElementById('mood');
      moodEl.textContent = '没听清，再说一次？';
      setTimeout(() => updateStatus(lastState), 2000);
    }
  } else if (msg.type === 'reply') {
    addBubble(msg.text, 'her');
    updateStatus(msg.state);
    setEmotionGlow(msg.emotion);
    motionBurst();
    if (msg.audio) {
      speaking = true;
      speakHint.classList.remove('hidden');
      const audio = new Audio(`data:audio/mp3;base64,${msg.audio}`);
      currentAudio = audio;
      const done = () => {
        speaking = false;
        speakHint.classList.add('hidden');
      };
      audio.addEventListener('ended', done);
      audio.play().catch(done);
    }
  }
});

function updateStatus(state) {
  if (!state) return;
  lastState = state;
  document.getElementById('mood').textContent = `心情：${state.mood}`;
  document.getElementById('affection').textContent = `好感度：${state.affection}（${state.level}）`;
}

function sendChat() {
  const text = textInput.value.trim();
  if (!text || ws.readyState !== WebSocket.OPEN) return;
  addBubble(text, 'me');
  ws.send(JSON.stringify({ type: 'chat', text }));
  textInput.value = '';
}
sendBtn.addEventListener('click', sendChat);
textInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });

/* ---------- 连续语音对话（本地录音 + VAD 断句 + 服务端识别） ---------- */
let voiceMode = false;      // 语音对话循环开关
let speaking = false;       // 她正在说话（此时不录音，避免把她自己的声音录进去）
let currentAudio = null;

let mediaStream = null, recorder = null, audioCtx = null, analyser = null;
let vadTimer = null, uttering = false, silenceTicks = 0, utterStart = 0;
const VAD_START = 0.02;     // 超过该音量判定为开始说话
const VAD_STOP = 0.012;     // 低于该音量并持续 800ms 判定为说完
const MAX_UTTER_MS = 15000;

async function startMic() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    voiceMode = false;
    micBtn.classList.remove('active');
    micBtn.textContent = '🎤';
    const tips = {
      NotAllowedError: '麦克风权限被拒绝：点地址栏左侧的 🔒 图标 → 网站设置 → 麦克风 → 允许，然后刷新页面',
      NotFoundError: '没检测到麦克风设备：请检查麦克风是否插好/被禁用',
      NotReadableError: '麦克风被其他程序占用：请关闭正在用麦克风的应用（如微信/QQ 语音、会议软件）',
    };
    alert(tips[e.name] || `麦克风不可用：${e.name} ${e.message}`);
    return;
  }
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = audioCtx.createMediaStreamSource(mediaStream);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 512;
  src.connect(analyser);

  let chunks = [];
  recorder = new MediaRecorder(mediaStream);
  recorder.addEventListener('dataavailable', (e) => { if (e.data.size) chunks.push(e.data); });
  recorder.addEventListener('stop', () => {
    const blob = new Blob(chunks, { type: recorder.mimeType });
    chunks = [];
    if (blob.size > 1000 && ws.readyState === WebSocket.OPEN) {
      const reader = new FileReader();
      reader.onload = () => ws.send(JSON.stringify(
        { type: 'voice', audio: reader.result.split(',')[1] }));
      reader.readAsDataURL(blob);
    }
  });

  vadTimer = setInterval(vadTick, 100);
}

// 音量能量检测：开口自动录音，停顿自动发送
function vadTick() {
  if (!voiceMode || speaking || !analyser || !recorder) return;
  const buf = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (const v of buf) { const d = (v - 128) / 128; sum += d * d; }
  const rms = Math.sqrt(sum / buf.length);

  if (!uttering && rms > VAD_START) {
    uttering = true; silenceTicks = 0; utterStart = Date.now();
    micBtn.classList.add('recording'); // 检测到你开口，按钮变红
    if (recorder.state === 'inactive') recorder.start();
  } else if (uttering) {
    silenceTicks = rms < VAD_STOP ? silenceTicks + 1 : 0;
    if (silenceTicks >= 8 || Date.now() - utterStart > MAX_UTTER_MS) {
      uttering = false;
      micBtn.classList.remove('recording');
      if (recorder.state !== 'inactive') recorder.stop();
    }
  }
}

function stopMic() {
  clearInterval(vadTimer); vadTimer = null;
  uttering = false;
  micBtn.classList.remove('recording');
  if (recorder && recorder.state !== 'inactive') { try { recorder.stop(); } catch (e) {} }
  if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
  if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
  recorder = null; analyser = null;
}

micBtn.addEventListener('click', () => {
  voiceMode = !voiceMode;
  micBtn.classList.toggle('active', voiceMode);
  micBtn.textContent = voiceMode ? '⏹' : '🎤';
  micBtn.title = voiceMode ? '结束语音对话' : '开始语音对话';
  if (voiceMode) startMic();
  else { stopMic(); if (currentAudio) currentAudio.pause(); }
});
ws.addEventListener('close', stopMic);

/* ---------- 初始化 ---------- */
buildWardrobe();
const initial = LOOKS.find(l => l.id === DEFAULT_LOOK) || LOOKS[0];
if (initial) {
  switchLook(initial);
  // 开场白取自资源包自带对白
  const enterLines = initial.dialogue?.enter || [];
  if (enterLines.length) addBubble(enterLines[0], 'her');
}
