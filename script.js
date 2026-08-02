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

let state = {
  slots: [],      // filled by loadSchedule() after login
  takenLog: {}    // filled by loadTakenLog() after login
};

let authToken = null;

function authHeaders(){
  return authToken ? { 'Authorization': 'Bearer ' + authToken } : {};
}

const api = {
  async login(user, password){
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user, password })
    });
    const data = await res.json().catch(()=> ({}));
    if(!res.ok || !data.ok) throw new Error(data.error || 'Credenciales incorrectas');
    authToken = data.token;
    return true;
  },
  async logout(){
    try {
      await fetch('/api/logout', { method: 'POST', headers: authHeaders() });
    } catch(e){ /* la sesión local se limpia igual */ }
    authToken = null;
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
  async getDriverStatus(){
    const res = await fetch('/api/status', { headers: authHeaders() });
    if(!res.ok) throw new Error('No se pudo leer el estado del driver');
    return res.json();
  },
  // Simulación local del sensor (DevDriver): el firmware real reporta
  // slot_open/slot_closed como eventos; acá se simulan con este endpoint.
  async simDriver(action, slotId){
    const res = await fetch('/api/driver/sim', {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, slot_id: slotId })
    });
    if(!res.ok) throw new Error('No se pudo simular el sensor');
    return res.json();
  }
};

/* ========================= AUTH / NAV ========================= */

function handleLogin(){
  const user = document.getElementById('loginUser').value;
  const pass = document.getElementById('loginPass').value;
  const errEl = document.getElementById('loginError');
  const btn = document.getElementById('loginBtn');
  errEl.textContent = '';
  btn.disabled = true;

  api.login(user, pass)
    .then(loadApp)
    .then(()=>{
      document.getElementById('view-login').classList.add('hidden');
      document.getElementById('view-app').classList.remove('hidden');
      connectWS();
      renderDashboard();
      startPendingWatcher();
    })
    .catch(err=>{
      errEl.textContent = err.message || 'No se pudo conectar con el servidor';
    })
    .finally(()=>{ btn.disabled = false; });
}

async function loadApp(){
  const [slots, log] = await Promise.all([api.getSchedule(), api.getTakenLog()]);
  state.slots = slots;
  // El backend devuelve una lista de registros {key, taken, ts}; lo
  // aplanamos a un mapa clave -> booleano para las vistas.
  state.takenLog = Object.fromEntries((log||[]).map(r => [r.key, !!r.taken]));
}

document.getElementById('loginPass').addEventListener('keydown', e=>{
  if(e.key === 'Enter') handleLogin();
});

/* ========================= WEBSOCKET PUSH (H4/H6) ========================= */

let ws = null;
let wsRetry = 0;

function connectWS(){
  if(!authToken) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws?token=${encodeURIComponent(authToken)}`);
  ws.onopen = ()=>{ wsRetry = 0; };
  ws.onmessage = ev=>{
    let msg;
    try { msg = JSON.parse(ev.data); } catch(e){ return; }
    if(msg.type === 'on_pill_taken'){
      state.takenLog[msg.key] = !!msg.taken;
      renderDashboard();
    }
  };
  ws.onclose = ()=>{
    ws = null;
    if(authToken){
      wsRetry += 1;
      setTimeout(connectWS, Math.min(1000 * Math.pow(2, wsRetry), 15000));
    }
  };
}

function closeWS(){
  if(ws){ ws.onclose = null; ws.close(); ws = null; }
  wsRetry = 0;
}

function handleLogout(){
  stopPendingWatcher();
  hideDoseModal();
  closeWS();
  api.logout().finally(()=>{
    document.getElementById('view-app').classList.add('hidden');
    document.getElementById('view-login').classList.remove('hidden');
    document.getElementById('loginPass').value = '';
  });
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
    if(slot.enabled && slot.enabled[todayKey] === false) return;
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
        <span class="dose-check">${taken?'✓':''}</span>
      </div>`;
  }).join('');
}

/* ========================= DOSE MODAL (dosis pendiente) ========================= */

let modalDose = null;   // dosis actualmente mostrada en el modal
let pendingTimer = null;

function showDoseModal(dose){
  modalDose = dose;
  const slot = state.slots.find(s=>s.id===dose.slotId);
  document.getElementById('doseModalSlot').textContent = slot ? `Casilla ${slot.id}` : `Casilla ${dose.slotId}`;
  document.getElementById('doseModalTime').textContent = dose.time;
  document.getElementById('doseModalName').textContent = dose.name;
  document.getElementById('doseModal').classList.remove('hidden');
}

function hideDoseModal(){
  document.getElementById('doseModal').classList.add('hidden');
  modalDose = null;
}

// Detección: la dosis cuya hora ya llegó, aún no tomada Y pendiente en el
// backend (el scheduler la dispensó). Sin sensor, la dosis queda pendiente
// hasta confirmarla acá (Decisión B). Si el server estaba apagado a la hora,
// nunca se dispensó y el modal no aparece (no hay nada que confirmar).
function findPendingDose(pendingSlots){
  const now = nowHHMM();
  return getTodayDoses().find(dose =>
    !isTaken(dose) && dose.time <= now && pendingSlots.includes(dose.slotId)
  ) || null;
}

// "Abrir y tomar" usa delegación de eventos (V3: sin onclick en strings).
document.getElementById('doseModal').addEventListener('click', ev=>{
  if(ev.target.id !== 'doseModalTake') return;
  const dose = modalDose;
  if(!dose) return;
  hideDoseModal();
  // Simula el sensor: abrir + cerrar el compartimiento confirma la toma.
  // El endpoint dice si el cierre realmente confirmó (evita falso éxito).
  api.simDriver('open', dose.slotId)
    .then(()=> api.simDriver('close', dose.slotId))
    .then(res=>{
      if(res && res.confirmed){
        showToast('Dosis marcada como tomada');
      } else {
        showToast('No había dosis pendiente en esta casilla');
      }
    })
    .catch(err=> showToast(err.message))
    .finally(()=> renderDashboard());
});

function startPendingWatcher(){
  stopPendingWatcher();
  checkPendingDose();
  pendingTimer = setInterval(checkPendingDose, 15000);
}

function stopPendingWatcher(){
  if(pendingTimer){ clearInterval(pendingTimer); pendingTimer = null; }
}

async function checkPendingDose(){
  if(document.getElementById('view-app').classList.contains('hidden')) return;
  let pendingSlots = [];
  try {
    const st = await api.getDriverStatus();
    pendingSlots = Object.keys(st.pending || {}).map(Number);
  } catch(e){ return; } // sin conexión: no cambiar el modal
  const dose = findPendingDose(pendingSlots);
  const modalOpen = !document.getElementById('doseModal').classList.contains('hidden');
  if(dose && !modalOpen){
    showDoseModal(dose);
  } else if(!dose && modalOpen){
    // La dosis ya no está pendiente (confirmada por otro lado): cerrar.
    hideDoseModal();
    renderDashboard();
  }
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
  if(!editingSlot.enabled){
    editingSlot.enabled = {};
    DAY_KEYS.forEach(d => editingSlot.enabled[d] = true);
  }
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
    const off = editingSlot.enabled[d] === false;
    return `<button class="day-chip ${d===editingDay?'active':''} ${hasTimes?'has-times':''} ${off?'off':''}"
              onclick="selectDay('${d}')">${d}<span class="dot"></span></button>`;
  }).join('');
}

function selectDay(d){
  if(d === editingDay){
    // Deseleccionar: apaga el día conservando sus horas (no se ejecutan).
    editingSlot.enabled[d] = false;
    editingDay = null;
    renderDayStrip();
    renderTimesPanel();
    return;
  }
  if(editingSlot.schedule[d].length === 0){
    // UX: al elegir un día sin horario, se copian las horas del día visible
    // (o del último día que tenga horas) para no configurarlas una por una.
    const source = editingDay && editingSlot.schedule[editingDay].length > 0
      ? editingDay
      : DAY_KEYS.find(k => editingSlot.schedule[k].length > 0);
    if(source){
      editingSlot.schedule[d] = [...editingSlot.schedule[source]];
    }
  }
  // Reactivar si estaba desactivado.
  if(editingSlot.enabled[d] === false){
    editingSlot.enabled[d] = true;
  }
  editingDay = d;
  renderDayStrip();
  renderTimesPanel();
}

function renderTimesPanel(){
  if(!editingDay){
    document.getElementById('timesLabel').textContent = 'Horarios';
    document.getElementById('timesList').innerHTML =
      `<div style="color:var(--text-muted);font-size:12.5px;padding:4px 0 8px;">Seleccioná un día</div>`;
    return;
  }
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
  DAY_KEYS.forEach(d => editingSlot.enabled[d] = true);
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