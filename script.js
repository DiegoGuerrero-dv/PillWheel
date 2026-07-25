/* =========================================================================
   DATA LAYER
   -------------------------------------------------------------------------
   No pill data is hardcoded here anymore. Everything comes from the API
   below, which talks to whatever is serving this page:
     - Right now (testing on your computer): dev_server.py, which reads
       and writes schedule.json / taken_log.json on disk.
     - Later (real device): the ESP32 sketch, which reads and writes the
       same two files on LittleFS.
   Both backends expose the exact same routes, so nothing in this file
   needs to change when you swap one for the other.
   ========================================================================= */

const DAY_KEYS = ['Dom','Lun','Mar','Mie','Jue','Vie','Sab']; // Sun..Sat — matches Date.getDay() AND C's tm_wday, index-for-index
const DAY_FULL_NAMES = {
  Dom:'Domingo', Lun:'Lunes', Mar:'Martes', Mie:'Miércoles',
  Jue:'Jueves', Vie:'Viernes', Sab:'Sábado'
};
const SLOT_COUNT = 8;

function emptySchedule(){
  const s = {}; DAY_KEYS.forEach(d => s[d] = []); return s;
}

let state = {
  slots: [],      // filled by loadSchedule() after login
  takenLog: {}    // filled by loadTakenLog() after login
};

let authToken = null;

function authHeaders(){
  return authToken ? { 'Authorization': 'Bearer ' + authToken } : {};
}

const api = {
  async login(password){
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password })
    });
    const data = await res.json().catch(()=> ({}));
    if(!res.ok || !data.ok) throw new Error(data.error || 'Contraseña incorrecta');
    authToken = data.token;
    return true;
  },
  async getSchedule(){
    const res = await fetch('/api/schedule', { headers: authHeaders() });
    if(!res.ok) throw new Error('No se pudo cargar el horario');
    return res.json();
  },
  async saveSlot(slot){
    const res = await fetch('/api/schedule', {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(slot)
    });
    if(!res.ok) throw new Error('No se pudo guardar la casilla');
    return slot;
  },
  async getTakenLog(){
    const res = await fetch('/api/taken', { headers: authHeaders() });
    if(!res.ok) throw new Error('No se pudo cargar el registro de dosis tomadas');
    return res.json();
  },
  async markTaken(key, val){
    const res = await fetch('/api/taken', {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, value: val })
    });
    if(!res.ok) throw new Error('No se pudo actualizar');
    return true;
  }
};

/* ========================= AUTH / NAV ========================= */

function handleLogin(){
  const pass = document.getElementById('loginPass').value;
  const errEl = document.getElementById('loginError');
  const btn = document.getElementById('loginBtn');
  errEl.textContent = '';
  btn.disabled = true;

  api.login(pass)
    .then(loadApp)
    .then(()=>{
      document.getElementById('view-login').classList.add('hidden');
      document.getElementById('view-app').classList.remove('hidden');
      renderDashboard();
    })
    .catch(err=>{
      errEl.textContent = err.message || 'No se pudo conectar con el servidor';
    })
    .finally(()=>{ btn.disabled = false; });
}

async function loadApp(){
  const [slots, log] = await Promise.all([api.getSchedule(), api.getTakenLog()]);
  state.slots = slots;
  state.takenLog = log;
}

document.getElementById('loginPass').addEventListener('keydown', e=>{
  if(e.key === 'Enter') handleLogin();
});

function handleLogout(){
  authToken = null;
  document.getElementById('view-app').classList.add('hidden');
  document.getElementById('view-login').classList.remove('hidden');
  document.getElementById('loginPass').value = '';
}

function switchTab(tab){
  const dash = tab === 'dashboard';
  document.getElementById('view-dashboard').classList.toggle('hidden', !dash);
  document.getElementById('view-manage').classList.toggle('hidden', dash);
  document.getElementById('tabDash').classList.toggle('active', dash);
  document.getElementById('tabManage').classList.toggle('active', !dash);
  if(dash) renderDashboard(); else renderManage();
}

/* ========================= DASHBOARD ========================= */

function pad2(n){ return n.toString().padStart(2,'0'); }
function dateKey(d){ return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}`; }
function nowHHMM(){ const d=new Date(); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; }

function getTodayDoses(){
  const todayKey = DAY_KEYS[new Date().getDay()]; // getDay(): 0=Dom..6=Sab, same order as DAY_KEYS
  let doses = [];
  state.slots.forEach(slot=>{
    if(!slot.name) return;
    (slot.schedule[todayKey] || []).forEach(time=>{
      doses.push({slotId:slot.id, name:slot.name, color:slot.color, time});
    });
  });
  doses.sort((a,b)=> a.time.localeCompare(b.time));
  return doses;
}

function isTaken(dose){
  return !!state.takenLog[`${dateKey(new Date())}_${dose.slotId}_${dose.time}`];
}

function toggleTaken(dose){
  const key = `${dateKey(new Date())}_${dose.slotId}_${dose.time}`;
  const newVal = !state.takenLog[key];
  api.markTaken(key, newVal).then(()=>{
    state.takenLog[key] = newVal;
    renderDashboard();
  }).catch(err=> showToast(err.message));
}

function renderDashboard(){
  const d = new Date();
  document.getElementById('todayDayName').textContent = d.toLocaleDateString('es-MX',{weekday:'long'});
  document.getElementById('todayDate').textContent = d.toLocaleDateString('es-MX',{day:'numeric',month:'long'});

  const doses = getTodayDoses();
  const hero = document.getElementById('heroBox');
  const now = nowHHMM();
  const next = doses.find(dose => !isTaken(dose) && dose.time >= now) || doses.find(dose => !isTaken(dose));

  if(!next){
    hero.className = 'hero empty';
    hero.innerHTML = doses.length
      ? 'Ya tomaste todas tus dosis de hoy ✓'
      : 'No hay dosis programadas para hoy';
  } else {
    hero.className = 'hero';
    const slot = state.slots.find(s=>s.id===next.slotId);
    hero.innerHTML = `
      <div class="eyebrow">Próxima dosis</div>
      <div class="hero-row">
        <div>
          <div class="pill-name">${escapeHtml(next.name)}</div>
          <div class="pill-slot">Casilla ${slot.id}</div>
        </div>
        <div class="time">${next.time}</div>
      </div>`;
  }

  const list = document.getElementById('doseList');
  if(doses.length === 0){
    list.innerHTML = `<div class="empty-state">Aún no hay pastillas programadas para hoy.<br>Ve a la pestaña "Casillas" para agregarlas.</div>`;
    return;
  }
  list.innerHTML = doses.map(dose=>{
    const taken = isTaken(dose);
    return `
      <div class="dose-row ${taken?'taken':''}">
        <div class="dose-dot" style="background:${dose.color}"></div>
        <div class="dose-info">
          <div class="n">${escapeHtml(dose.name)}</div>
          <div class="s">Casilla ${dose.slotId}</div>
        </div>
        <div class="dose-time">${dose.time}</div>
        <button class="dose-check" onclick='toggleTaken(${JSON.stringify(dose)})'>${taken?'✓':''}</button>
      </div>`;
  }).join('');
}

/* ========================= MANAGE / BLISTER GRID ========================= */

function renderManage(){
  const grid = document.getElementById('blisterGrid');
  grid.innerHTML = state.slots.map(slot=>{
    const empty = !slot.name;
    return `
      <button class="cell ${empty?'empty':''}" onclick="openEditor(${slot.id})">
        <span class="num">${slot.id}</span>
        <span class="led" style="background:${slot.color}"></span>
        <span class="cname">${empty ? 'Vacío' : escapeHtml(slot.name)}</span>
      </button>`;
  }).join('');
}

/* ========================= EDIT SHEET ========================= */

let editingSlot = null;
let editingDay = 'Dom';

function openEditor(slotId){
  editingSlot = JSON.parse(JSON.stringify(state.slots.find(s=>s.id===slotId))); // clone
  editingDay = 'Dom';
  document.getElementById('editTitle').textContent = `Casilla ${slotId}`;
  document.getElementById('editName').value = editingSlot.name;
  document.getElementById('editColor').value = editingSlot.color;
  renderDayStrip();
  renderTimesPanel();
  document.getElementById('editOverlay').classList.remove('hidden');
}

function closeEditor(){
  document.getElementById('editOverlay').classList.add('hidden');
  editingSlot = null;
}

function onColorChange(){
  editingSlot.color = document.getElementById('editColor').value;
}

function renderDayStrip(){
  const strip = document.getElementById('dayStrip');
  strip.innerHTML = DAY_KEYS.map(d=>{
    const hasTimes = editingSlot.schedule[d].length > 0;
    return `<button class="day-chip ${d===editingDay?'active':''} ${hasTimes?'has-times':''}"
              onclick="selectDay('${d}')">${d}<span class="dot"></span></button>`;
  }).join('');
}

function selectDay(d){
  editingDay = d;
  renderDayStrip();
  renderTimesPanel();
}

function renderTimesPanel(){
  document.getElementById('timesLabel').textContent = `Horarios · ${DAY_FULL_NAMES[editingDay]}`;
  const times = editingSlot.schedule[editingDay];
  const list = document.getElementById('timesList');
  if(times.length === 0){
    list.innerHTML = `<div style="color:var(--text-muted);font-size:12.5px;padding:4px 0 8px;">Sin horario este día</div>`;
    return;
  }
  list.innerHTML = times.map((t,i)=>`
    <div class="time-chip">
      <input type="time" value="${t}" onchange="updateTime(${i}, this.value)">
      <button class="rm" onclick="removeTime(${i})">✕</button>
    </div>`).join('');
}

function addTimeToDay(){
  editingSlot.schedule[editingDay].push('08:00');
  editingSlot.schedule[editingDay].sort();
  renderDayStrip();
  renderTimesPanel();
}

function updateTime(index, value){
  editingSlot.schedule[editingDay][index] = value;
  editingSlot.schedule[editingDay].sort();
  renderTimesPanel();
}

function removeTime(index){
  editingSlot.schedule[editingDay].splice(index,1);
  renderDayStrip();
  renderTimesPanel();
}

function clearSlot(){
  editingSlot.name = '';
  DAY_KEYS.forEach(d => editingSlot.schedule[d] = []);
  document.getElementById('editName').value = '';
  renderDayStrip();
  renderTimesPanel();
}

function saveSlot(){
  editingSlot.name = document.getElementById('editName').value.trim();
  api.saveSlot(editingSlot).then(()=>{
    const i = state.slots.findIndex(s=>s.id===editingSlot.id);
    if(i>-1) state.slots[i] = editingSlot;
    closeEditor();
    renderManage();
    showToast('Casilla guardada');
  }).catch(err=> showToast(err.message));
}

/* ========================= UTIL ========================= */

function escapeHtml(str){
  return str.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

let toastTimer;
function showToast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=> t.classList.remove('show'), 1800);
}