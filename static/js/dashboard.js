const $ = id => document.getElementById(id);
const $$ = q => document.querySelectorAll(q);

// ─────────────────────────────
// SECCIÓN ACTIVA (persiste con hash)
// ─────────────────────────────
// Secciones que requieren rol miembro/admin
const SECCIONES_MIEMBRO = ['galeria', 'recaudacion', 'noticias'];
// Rol del usuario actual (inyectado desde Flask en base.html o dashboard)
const ROL_USUARIO = document.body.dataset.rol || 'invitado';

function irSeccion(sec) {
  // Si es sección restringida y no tiene permiso → ir a inicio
  if (SECCIONES_MIEMBRO.includes(sec) && ROL_USUARIO === 'invitado') {
    sec = 'inicio';
  }

  // Limpiar cualquier overflow bloqueado por modales/videos de sección anterior
  document.body.style.overflow = '';
  document.documentElement.style.overflow = '';

  // Si sale de mundial → avisar para limpiar video/modales
  const seccionActual = localStorage.getItem('seccion') || '';
  if (seccionActual === 'mundial' && sec !== 'mundial') {
    document.dispatchEvent(new CustomEvent('mundial:salir'));
  }

  // Si navega a mundial desde el menú → disparar evento para la intro
  if (sec === 'mundial') {
    document.dispatchEvent(new CustomEvent('mundial:entrar'));
  }

  $$('.section').forEach(s => s.classList.remove('active'));
  $$('.nav-item').forEach(n => n.classList.remove('active'));

  const target = $('sec-' + sec);
  const item   = document.querySelector('.nav-item[data-sec="' + sec + '"]');

  if (target) target.classList.add('active');
  if (item)   item.classList.add('active');

  const navTitle = $('nav-title');
  if (navTitle && item) navTitle.textContent = item.querySelector('.menu-text')?.textContent || sec;

  history.replaceState(null, '', '#' + sec);
  localStorage.setItem('seccion', sec);

  if (window.innerWidth <= 768) {
    $('sidebar')?.classList.remove('open');
    $('overlay')?.classList.remove('active');
  }
}

// ─────────────────────────────
// INIT: restaurar sección
// ─────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  const hash    = window.location.hash.replace('#', '');
  const fromSrv = document.body.dataset.seccion || '';
  const fromLS  = localStorage.getItem('seccion') || '';
  const target  = hash || fromSrv || fromLS || 'inicio';

  $$('.section').forEach(s => s.classList.remove('active'));
  $$('.nav-item').forEach(n => n.classList.remove('active'));

  const sec  = $('sec-' + target);
  const item = document.querySelector('.nav-item[data-sec="' + target + '"]');
  if (sec)  sec.classList.add('active');
  if (item) item.classList.add('active');

  const navTitle = $('nav-title');
  if (navTitle && item) navTitle.textContent = item.querySelector('.menu-text')?.textContent || target;

  initTheme();
  iniciarCountdown();

  const accent = localStorage.getItem('accent');
  if (accent) document.documentElement.style.setProperty('--accent', accent);

  initPublicarAjax();
  initAjaxForms();
});

// ─────────────────────────────
// NAV SIDEBAR clicks
// ─────────────────────────────
document.addEventListener('click', e => {
  const item = e.target.closest('.nav-item[data-sec]');
  if (item) {
    e.preventDefault();
    irSeccion(item.dataset.sec);
  }
});

// ─────────────────────────────
// LOADER
// ─────────────────────────────
window.addEventListener('load', () => {
  setTimeout(() => $('loader')?.classList.add('hidden'), 600);
});

// ─────────────────────────────
// SIDEBAR TOGGLE
// ─────────────────────────────
function toggleSidebar() {
  $('sidebar')?.classList.toggle('open');
  $('overlay')?.classList.toggle('active');
}

// ─────────────────────────────
// COUNTDOWN
// ─────────────────────────────
function iniciarCountdown() {
  const meta = new Date('2026-06-11T12:30:00').getTime(); // Apertura FIFA 2026
  function tick() {
    const diff = meta - Date.now();
    if (diff <= 0) {
      [$('cd-dias'), $('cd-horas'), $('cd-min'), $('cd-seg')].forEach(el => { if (el) el.textContent = '00'; });
      return;
    }
    const pad = n => String(n).padStart(2, '0');
    if ($('cd-dias'))  $('cd-dias').textContent  = pad(Math.floor(diff / 86400000));
    if ($('cd-horas')) $('cd-horas').textContent = pad(Math.floor((diff % 86400000) / 3600000));
    if ($('cd-min'))   $('cd-min').textContent   = pad(Math.floor((diff % 3600000) / 60000));
    if ($('cd-seg'))   $('cd-seg').textContent   = pad(Math.floor((diff % 60000) / 1000));
  }
  tick();
  setInterval(tick, 1000);
}

// ─────────────────────────────
// LIKE (sin recarga)
// ─────────────────────────────
async function darLike(id, btn) {
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  try {
    const res  = await fetch(`/like/${id}`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      btn.querySelector('.like-count').textContent = data.likes;
      btn.classList.toggle('liked', data.liked);
      btn.classList.add('pop');
      setTimeout(() => btn.classList.remove('pop'), 200);
    }
  } catch (e) { console.warn(e); }
  setTimeout(() => btn.disabled = false, 400);
}

// ─────────────────────────────
// COMENTARIOS toggle
// ─────────────────────────────
function abrirComentarios(id) {
  $('comentarios-' + id)?.classList.toggle('open');
}

// ─────────────────────────────
// PUBLICAR SIN RECARGAR (AJAX)
// ─────────────────────────────
function initPublicarAjax() {
  const form = document.getElementById('form-publicar');
  if (!form) return;

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const fd  = new FormData(form);
    const btn = form.querySelector('button[type="submit"]');
    if (btn) { btn.disabled = true; btn.textContent = 'Publicando...'; }

    try {
      const res  = await fetch('/publicar_ajax', { method: 'POST', body: fd });
      const data = await res.json();
      if (data.ok) {
        const feed = document.getElementById('feed-posts');
        if (feed) {
          const div = document.createElement('div');
          div.innerHTML = data.html;
          feed.prepend(div.firstElementChild);
        }
        form.querySelector('textarea[name="texto"]').value = '';
        const mediaInput = form.querySelector('input[name="media"]');
        if (mediaInput) mediaInput.value = '';
        const lblMedia = document.getElementById('lbl-media');
        if (lblMedia) lblMedia.textContent = 'Foto/Video';
        mostrarToast('✅ Publicado correctamente');
      }
    } catch (err) {
      mostrarToast('❌ Error al publicar', 'error');
    }

    if (btn) { btn.disabled = false; btn.textContent = 'Publicar'; }
  });
}

// ─────────────────────────────
// AJAX UNIVERSAL — intercepta TODOS los formularios POST
// Excepciones: form-publicar (ya tiene su handler), login/registro
// ─────────────────────────────
function initAjaxForms() {
  document.addEventListener('submit', async e => {
    const form = e.target;

    // Saltar formularios excluidos
    if (!form || form.tagName !== 'FORM') return;
    if (form.id === 'form-publicar') return;           // ya tiene handler
    if (form.dataset.noajax === 'true') return;         // override manual
    if (form.method && form.method.toLowerCase() !== 'post') return;
    const action = form.action || '';
    if (action.includes('/login') || action.includes('/registro') || action.includes('/logout')) return;
    // mundial tiene su propio handler en la template
    const cleanAction = action.replace(window.location.origin, '').replace(/\/$/, '');
    if (cleanAction === '/pronostico' || cleanAction === '/admin_resultado') return;

    e.preventDefault();
    e.stopPropagation();

    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
    const originalText = submitBtn ? (submitBtn.textContent || submitBtn.value) : '';
    if (submitBtn) {
      submitBtn.disabled = true;
      if (submitBtn.textContent !== undefined) submitBtn.textContent = 'Guardando...';
    }

    try {
      const fd = new FormData(form);
      const res = await fetch(form.action || window.location.pathname, {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: fd
      });

      let data = {};
      try { data = await res.json(); } catch (_) {}

      if (data.redirect) {
        // Redirigir (p.ej. después de eliminar cuenta)
        window.location.href = data.redirect;
        return;
      }

      if (res.ok && (data.ok !== false)) {
        // Éxito
        const msg = data.msg || '✅ Guardado correctamente';
        mostrarToast(msg);

        // Acciones post-guardado según la acción del form
        _postFormSuccess(form, data);
      } else {
        const errMsg = data.error || `Error ${res.status}`;
        mostrarToast('❌ ' + errMsg, 'error');
      }
    } catch (err) {
      console.error('AJAX form error:', err);
      mostrarToast('❌ Error de conexión', 'error');
    }

    if (submitBtn) {
      submitBtn.disabled = false;
      if (submitBtn.textContent !== undefined) submitBtn.textContent = originalText;
      else submitBtn.value = originalText;
    }
  });
}

// ─────────────────────────────
// Acciones post-éxito por tipo de acción
// ─────────────────────────────
function _postFormSuccess(form, data) {
  const action = (form.action || '').replace(window.location.origin, '');

  // Eliminar post: quitar la tarjeta del DOM
  if (action.startsWith('/eliminar_post/')) {
    const postId = action.split('/').pop();
    const card = document.getElementById('post-' + postId);
    if (card) {
      card.style.opacity = '0';
      card.style.transition = 'opacity 0.3s';
      setTimeout(() => card.remove(), 300);
    }
    return;
  }

  // Eliminar media de galería
  if (action.startsWith('/eliminar_media/')) {
    const mid = action.split('/').pop();
    const card = document.querySelector(`[data-media-id="${mid}"]`);
    if (card) {
      card.style.opacity = '0';
      card.style.transition = 'opacity 0.3s';
      setTimeout(() => card.remove(), 300);
    }
    return;
  }

  // Eliminar evento
  if (action.startsWith('/eliminar_evento/')) {
    const eid = action.split('/').pop();
    const card = document.querySelector(`[data-evento-id="${eid}"]`);
    if (card) {
      card.style.opacity = '0';
      card.style.transition = 'opacity 0.3s';
      setTimeout(() => card.remove(), 300);
    }
    return;
  }

  // Agregar evento nuevo al DOM
  if (action === '/crear_evento' && data.id) {
    const lista = document.getElementById('lista-eventos');
    if (lista) {
      const el = document.createElement('div');
      el.className = 'evento-card';
      el.dataset.eventoId = data.id;
      el.innerHTML = `<strong>${_esc(data.titulo)}</strong> — ${_esc(data.fecha)}${data.hora ? ' ' + _esc(data.hora) : ''}`;
      lista.prepend(el);
    }
    form.reset();
    return;
  }

  // Subir archivo a galería
  if (action === '/subir_archivo' && data.url) {
    const grid = document.getElementById('galeria-grid');
    if (grid) {
      const el = document.createElement('div');
      el.className = 'galeria-item';
      if (data.tipo === 'video') {
        el.innerHTML = `<video controls class="galeria-media"><source src="${_esc(data.url)}"></video>`;
      } else {
        el.innerHTML = `<img src="${_esc(data.url)}" class="galeria-media">`;
      }
      grid.prepend(el);
    }
    form.reset();
    return;
  }

  // Resultado mundial — actualizar tabla sin recargar
  if (action === '/admin_resultado' || action === '/pronostico') {
    // Quedarse en sección mundial
    irSeccion('mundial');
    form.reset();
    return;
  }

  // Aporte / finanzas
  if (action === '/aporte' || action.includes('polla') || action.includes('cajita')) {
    irSeccion('recaudacion');
    form.reset();
    return;
  }

  // Noticia creada
  if (action === '/crear_noticia' && data.id) {
    const lista = document.getElementById('lista-noticias');
    if (lista) {
      const el = document.createElement('div');
      el.className = 'noticia-card';
      el.innerHTML = `<strong>${_esc(data.titulo)}</strong>`;
      lista.prepend(el);
    }
    form.reset();
    return;
  }

  // Verificar / eliminar pago (admin): solo quitar row del DOM
  if (action.startsWith('/verificar_evento/') || action.startsWith('/verificar_aporte/') ||
      action.startsWith('/verificar_polla/') || action.startsWith('/eliminar_aporte/') ||
      action.startsWith('/eliminar_pago/')) {
    const row = form.closest('tr, .pago-row, .aporte-row, [data-pago-id]');
    if (row) {
      row.style.opacity = '0';
      row.style.transition = 'opacity 0.3s';
      setTimeout(() => row.remove(), 300);
    }
    return;
  }

  // Perfil / ajustes / contraseña: solo toast, no recargar
  if (action === '/actualizar_perfil') {
    if (data.foto) {
      // Actualizar TODOS los avatares (img y letter-divs)
      document.querySelectorAll('img.user-avatar-img').forEach(img => { img.src = data.foto; img.style.display = ''; });
      document.querySelectorAll('.sidebar-av-letter, .navbar-av-letter, #pf-avatar-letter').forEach(el => el.style.display = 'none');
      document.querySelectorAll('.sidebar-av-img, .navbar-av-img').forEach(img => { img.src = data.foto; img.style.display = ''; });
      const prev = document.getElementById('preview-foto-perfil');
      if (prev) { prev.src = data.foto; prev.style.display = ''; }
    }
    if (data.nombre) {
      $$('.user-display-name').forEach(el => el.textContent = data.nombre);
      const heroNombre = document.getElementById('pf-hero-nombre');
      if (heroNombre) heroNombre.textContent = data.nombre;
    }
    mostrarToast('✅ Perfil actualizado');
    return;
  }

  if (action === '/guardar_ajustes') {
    if (data.nombre) {
      $$('.user-display-name').forEach(el => el.textContent = data.nombre);
    }
    return;
  }

  // Por defecto: solo toast, sin recargar
}

// Escape HTML helper
function _esc(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─────────────────────────────
// TOAST NOTIFICACIONES
// ─────────────────────────────
function mostrarToast(msg, tipo = 'ok') {
  const t = document.createElement('div');
  t.className = 'app-toast toast-' + tipo;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.classList.add('visible'), 50);
  setTimeout(() => { t.classList.remove('visible'); setTimeout(() => t.remove(), 300); }, 3000);
}

// ─────────────────────────────
// TEMA OSCURO
// ─────────────────────────────
function initTheme() {
  if (localStorage.getItem('theme') === 'light') {
    document.body.classList.remove('dark-mode');
  } else {
    document.body.classList.add('dark-mode');
  }
  const cb = document.getElementById('toggle-dark');
  if (cb) cb.checked = document.body.classList.contains('dark-mode');
}

function toggleTheme(isDark) {
  document.body.classList.toggle('dark-mode', isDark);
  localStorage.setItem('theme', isDark ? 'dark' : 'light');
}

function setCheckbox(s) {
  const cb = document.querySelector('input[name="tema_oscuro"]');
  if (cb) cb.checked = s;
}

// ─────────────────────────────
// FIX MODALES: Mover al body para que position:fixed funcione correctamente
// Esto soluciona el problema de modales cortadas en desktop cuando están
// dentro de contenedores con overflow o transform.
// ─────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  const modalSelectors = [
    '.modal-overlay',
    '.ntm-overlay',
    '.rec-modal-overlay',
    '#umu-overlay',
    '#media-modal',
    '.as-modal-overlay'
  ];
  modalSelectors.forEach(function(sel) {
    document.querySelectorAll(sel).forEach(function(modal) {
      if (modal.parentElement !== document.body) {
        document.body.appendChild(modal);
      }
    });
  });
});
