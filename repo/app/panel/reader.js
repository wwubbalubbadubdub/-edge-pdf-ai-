(function () {
  var q = new URLSearchParams(location.search);
  var book = q.get('book') || '';
  var b64 = q.get('pdfb64') || '';
  var pdf = '';
  try {
    var s = b64.replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    pdf = atob(s);
  } catch (e) { pdf = ''; }

  var TOOLBAR = 41;          // 原生 PDF 工具栏高度（100% DPI）
  var GAP = 10;              // 书页与面板的间距
  var DEF_W = 380;           // 面板默认宽度

  var pdfFrame = document.getElementById('pdf');
  var panel = document.getElementById('panel');
  var handle = document.getElementById('handle');
  var loading = document.getElementById('loading');

  var pw = 595, ph = 842;    // A4 兜底，稍后从服务端取真实尺寸
  var offX = 0, panelW = DEF_W;

  try { panelW = parseFloat(localStorage.getItem('panelW') || '0') || DEF_W; } catch (e) {}
  try { offX = parseFloat(localStorage.getItem('panelOffX') || '0') || 0; } catch (e) {}

  if (pdf) {
    pdfFrame.src = pdf;
    document.title = decodeURIComponent(pdf.split('/').pop() || '') + ' · AI 批注';
  } else if (loading) {
    loading.textContent = '没有拿到 PDF 路径';
  }
  panel.src = 'http://127.0.0.1:8760/?book=' + encodeURIComponent(book) + '&embed=1';

  var measured = null;

  function pageRect() {
    if (measured && measured.w > 80) {
      return {x: measured.x, y: measured.y, w: measured.w, h: measured.h,
              W: window.innerWidth, H: window.innerHeight};
    }
    var W = window.innerWidth, H = window.innerHeight;
    var availH = Math.max(50, H - TOOLBAR);
    var k = Math.min(W / pw, availH / ph);
    var w = pw * k, h = ph * k;
    return {x: (W - w) / 2, y: TOOLBAR + (availH - h) / 2, w: w, h: h, W: W, H: H};
  }

  var MIN_W = 240;          // 面板最窄宽度

  function baseX() {
    var r = pageRect();
    return r.x + r.w + GAP;
  }

  function clampOff(v) {
    var r = pageRect();
    var base = baseX();
    var minOff = 6 - base;
    var maxOff = (r.W - MIN_W) - base;
    if (maxOff < minOff) { maxOff = minOff; }
    return Math.min(maxOff, Math.max(minOff, v));
  }

  function layout() {
    var r = pageRect();
    var x = r.x + r.w + GAP + clampOff(offX);   // 左缘：贴着书页右边
    if (x < 6) { x = 6; }
    if (x > r.W - MIN_W) { x = r.W - MIN_W; }
    var w = r.W - x;                  // 右缘：顶到窗口最右
    var top = TOOLBAR + 2;
    var h = Math.max(120, r.H - top); // 垂直：工具栏下方一直到窗口底部

    panel.style.left = x + 'px';
    panel.style.top = top + 'px';
    panel.style.width = w + 'px';
    panel.style.height = h + 'px';
    panel.classList.add('on');

    handle.style.left = (x - 4) + 'px';
    handle.style.top = top + 'px';
    handle.style.height = h + 'px';
    handle.classList.add('on');

    if (loading && loading.parentNode) { loading.remove(); }
  }

  function loadMeta() {
    fetch('http://127.0.0.1:8760/api/pdfmeta?book=' + encodeURIComponent(book))
      .then(function (r) { return r.json(); })
      .then(function (m) {
        if (m && m.pw && m.ph) { pw = m.pw; ph = m.ph; }
        if (m && m.page_rect && m.page_rect.w > 80) { measured = m.page_rect; }
        layout();
      })
      .catch(function () { layout(); });
  }

  // ---- 拖动面板 ----
  var dragging = false, startX = 0, startOff = 0;
  function endDrag() {
    if (!dragging) return;
    dragging = false;
    document.body.style.cursor = '';
    try {
      localStorage.setItem('panelOffX', String(Math.round(offX)));
      localStorage.setItem('panelW', String(Math.round(panelW)));
    } catch (e) {}
  }
  handle.addEventListener('pointerdown', function (e) {
    if (e.detail >= 2) {
      offX = 0;
      try { localStorage.removeItem('panelOffX'); localStorage.removeItem('panelW'); } catch (err) {}
      layout();
      return;
    }
    dragging = true; startX = e.clientX; startOff = offX;
    document.body.style.cursor = 'col-resize';
    try { handle.setPointerCapture(e.pointerId); } catch (err) {}
    e.preventDefault();
  });
  handle.addEventListener('pointermove', function (e) {
    if (!dragging) return;
    offX = clampOff(startOff + (e.clientX - startX));
    layout();
    e.preventDefault();
  });
  handle.addEventListener('pointerup', endDrag);
  handle.addEventListener('pointercancel', endDrag);
  handle.addEventListener('lostpointercapture', endDrag);
  window.addEventListener('blur', endDrag);

  window.__aiPageRect = function () {
    var r = pageRect();
    return {x: r.x, y: r.y, w: r.w, h: r.h, dpr: window.devicePixelRatio || 1};
  };

  setInterval(function () {
    fetch('http://127.0.0.1:8760/api/pdfmeta?book=' + encodeURIComponent(book))
      .then(function (r2) { return r2.json(); })
      .then(function (m) {
        if (m && m.page_rect && m.page_rect.w > 80) {
          var ch = !measured || Math.abs(measured.w - m.page_rect.w) > 4 ||
                   Math.abs(measured.x - m.page_rect.x) > 4;
          measured = m.page_rect;
          if (ch) { layout(); }
        }
      })
      .catch(function () {});
  }, 3000);

  window.addEventListener('resize', layout);
  loadMeta();
  setTimeout(layout, 600);
})();