const BOOK = new URLSearchParams(location.search).get('book') || '';
const $ = (s) => document.querySelector(s);
let INFO = null;
let PAGE = 1;
let THINKING = true;
let POLLING = false;
let busy = false;

const fmt = (n) => (n >= 10000 ? (n / 1000).toFixed(1) + 'k' : String(n || 0));
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function renderMD(src) {
  src = src || '';
  if (!window.marked) return esc(src);
  const store = [];
  const ph = (raw) => { store.push(raw); return '\u0000M' + (store.length - 1) + '\u0000'; };
  let s = src;
  s = s.replace(/```[\s\S]*?```/g, (m) => ph(m));
  s = s.replace(/`[^`\n]+`/g, (m) => ph(m));
  s = s.replace(/\\\[[\s\S]+?\\\]/g, (m) => ph(m));
  s = s.replace(/\\\([\s\S]+?\\\)/g, (m) => ph(m));
  s = s.replace(/\$\$[\s\S]+?\$\$/g, (m) => ph(m));
  s = s.replace(/(?<![\\$])\$(?!\$)([^\n$]+?)\$(?!\$)/g, (m) => ph(m));
  let html = marked.parse(s);
  html = html.replace(/\u0000M(\d+)\u0000/g, (m, i) => {
    const raw = store[+i] || '';
    if (raw.startsWith('```')) {
      const body = raw.replace(/^```[^\n]*\n?/, '').replace(/```$/, '');
      return '<pre><code>' + esc(body) + '</code></pre>';
    }
    if (raw.startsWith('`')) return '<code>' + esc(raw.slice(1, -1)) + '</code>';
    return esc(raw);
  });
  return html;
}

function typeset(el) {
  if (!window.renderMathInElement) return;
  try {
    renderMathInElement(el, {
      delimiters: [
        {left: '$$', right: '$$', display: true},
        {left: '\\[', right: '\\]', display: true},
        {left: '\\(', right: '\\)', display: false},
        {left: '$', right: '$', display: false}
      ],
      throwOnError: false,
      ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
    });
  } catch (e) {}
}

function addMsg(role, text, isMd) {
  const el = document.createElement('div');
  el.className = 'msg ' + (role === 'user' ? 'user' : 'ai');
  el.innerHTML = '<div class="who">' + (role === 'user' ? '我' : 'AI') + '</div><div class="body"></div>';
  const body = el.querySelector('.body');
  if (isMd) { body.innerHTML = renderMD(text); typeset(body); } else { body.textContent = text || ''; }
  $('#msgs').appendChild(el);
  $('#msgs').scrollTop = $('#msgs').scrollHeight;
  return body;
}

function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const m = Math.floor(sec / 60), s = sec % 60;
  return m ? (m + ' 分 ' + s + ' 秒') : (s + ' 秒');
}

function setHint(t) { $('#hint').textContent = t || ''; }

async function loadBook() {
  if (!BOOK) { $('#bookTitle').textContent = '没有指定书（缺少 book 参数）'; return; }
  try {
    const r = await fetch('/api/book?id=' + encodeURIComponent(BOOK));
    INFO = await r.json();
  } catch (e) {
    $('#bookTitle').textContent = '连不上后端：' + e;
    return;
  }
  if (INFO.error) { $('#bookTitle').textContent = '载入失败：' + INFO.error; return; }
  $('#bookTitle').textContent = INFO.title;
  document.title = INFO.title + ' · AI 批注';
  $('#ingestChip').textContent = '入账 ' + INFO.ingest.done + '/' + INFO.pages;
  const cst = INFO.cost || {};
  $('#costChip').textContent = fmt(cst.in + cst.out) + ' tok' + (cst.cache_rate ? ' · 缓存 ' + cst.cache_rate + '%' : '');
  const bc = $('#briefChip');
  if (bc) {
    bc.textContent = INFO.has_brief ? '约定 ✓' : '约定 ○';
    bc.classList.toggle('ok', !!INFO.has_brief);
  }
  $('#costChip').title = '输入 ' + (cst.in || 0) + ' / 输出 ' + (cst.out || 0) + ' / 缓存命中 ' + (cst.cache_hit || 0) + ' / 未命中 ' + (cst.cache_miss || 0);
  $('#page').max = INFO.pages;
  $('#page').value = PAGE;
  $('#pageChip').textContent = '第 ' + PAGE + ' 页 · 共 ' + INFO.pages + ' 页';
  if (typeof INFO.thinking === 'boolean') { THINKING = INFO.thinking; }
  applyThinkState();
  if (!document.body.dataset.ready) {
    document.body.dataset.ready = '1';
    renderToc();
    renderHistory(INFO.chat || []);
    maybePoll();
  }
}

function appendAIMessage(draft, review) {
  const hasReview = !!(review && review.trim());
  const el = document.createElement('div');
  el.className = 'msg ai';
  el.innerHTML = '<div class="who">AI</div>' + (hasReview
    ? '<details class="draftBox"><summary>初稿（点开看）</summary><div class="body"></div></details>' +
      '<div class="review"><div class="sec-label">核查后</div><div class="review-body"></div></div>'
    : '<details class="draftBox plain" open><summary>初稿</summary><div class="body"></div></details>');
  el.querySelector('.body').innerHTML = renderMD(draft || '');
  if (hasReview) el.querySelector('.review-body').innerHTML = renderMD(review);
  $('#msgs').appendChild(el);
  typeset(el);
  $('#msgs').scrollTop = $('#msgs').scrollHeight;
  return el;
}

function renderHistory(rows) {
  if (!rows || !rows.length) return;
  const box = document.createElement('div');
  box.className = 'history';
  $('#msgs').appendChild(box);
  rows.forEach((t) => {
    if (t.role === 'user') { addMsg('user', t.content, false); }
    else if (t.review !== undefined) { appendAIMessage(t.content, t.review); }
    else { addMsg('assistant', t.content, true); }
  });
}

function renderToc() {
  if (!INFO || !INFO.toc || !INFO.toc.length) return;
  const box = document.createElement('div');
  box.className = 'toc';
  INFO.toc.slice(0, 300).forEach((it) => {
    const d = document.createElement('div');
    d.textContent = '\u3000'.repeat(Math.max(0, it.level - 1)) + it.title + '  · p' + it.page;
    d.onclick = async () => {
      PAGE = it.page; $('#page').value = PAGE; $('#pageChip').textContent = '第 ' + PAGE + ' 页';
      await fetch('/api/goto', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({book: BOOK, page: PAGE})});
    };
    box.appendChild(d);
  });
  const first = $('#msgs').firstChild;
  $('#msgs').insertBefore(box, first);
}

async function ask() {
  const q = $('#q').value.trim();
  if (!q || busy) return;
  busy = true; $('#btnSend').disabled = true; $('#q').value = '';
  addMsg('user', q, false);

  const el = document.createElement('div');
  el.className = 'msg ai';
  el.innerHTML =
    '<div class="who">AI</div>' +
    '<details class="think" hidden><summary>思考中…</summary><div class="think-body"></div></details>' +
    '<details class="draftBox plain" open><summary>初稿（点开看）</summary><div class="body"></div></details>' +
    '<div class="review" hidden><div class="sec-label">核查后</div><div class="review-body"></div></div>';
  const body = el.querySelector('.body');
  const th = el.querySelector('.think');
  const thBody = th.querySelector('.think-body');
  const rv = el.querySelector('.review');
  const rvBody = el.querySelector('.review-body');
  const draftBox = el.querySelector('.draftBox');
  $('#msgs').appendChild(el);
  $('#msgs').scrollTop = $('#msgs').scrollHeight;

  let acc = '', think = '', rev = '';
  let answerStarted = false, userToggled = false, dirty = false, rdirty = false;
  th.addEventListener('toggle', () => { userToggled = true; });

  const timer = setInterval(() => {
    if (dirty) {
      dirty = false;
      body.innerHTML = renderMD(acc);
      typeset(body);
      $('#msgs').scrollTop = $('#msgs').scrollHeight;
    }
    if (rdirty) {
      rdirty = false;
      rvBody.innerHTML = renderMD(rev);
      typeset(rvBody);
    }
  }, 90);

  try {
    const resp = await fetch('/api/ask', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({book: BOOK, question: q, page: PAGE}),
    });
    if (!resp.ok) { body.innerHTML = '<span class="err">请求失败 ' + resp.status + '</span>'; return; }
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split('\n').find((l) => l.startsWith('data:'));
        if (!line) continue;
        let evt; try { evt = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }

        if (evt.type === 'reasoning') {
          th.hidden = false;
          think += evt.text;
          thBody.textContent = think;
          // 默认折叠，只在标题里报进度
          if (!userToggled) {
            th.querySelector('summary').textContent = '思考中…（' + think.length + ' 字，点开看）';
          }
        } else if (evt.type === 'delta') {
          if (!answerStarted) {
            answerStarted = true;
            if (think) {
              if (!userToggled) th.open = false;
              th.querySelector('summary').textContent = '思考过程（' + think.length + ' 字，点开看）';
            } else {
              th.hidden = true;
            }
          }
          acc += evt.text;
          dirty = true;
        } else if (evt.type === 'review_start') {
          rv.hidden = false;
          rvBody.textContent = '核查中…';
        } else if (evt.type === 'review') {
          rv.hidden = false;
          if (!rev) {
            // 第一段核查内容到达：收起初稿，只留核查后的最终答案
            draftBox.classList.remove('plain');
            draftBox.open = false;
          }
          rev += evt.text;
          rdirty = true;
        } else if (evt.type === 'usage') {
          setHint('tokens ' + (evt.usage.prompt_tokens || 0) + ' → ' + (evt.usage.completion_tokens || 0));
        } else if (evt.type === 'error') {
          acc += '\n\n> ' + evt.message; dirty = true;
        } else if (evt.type === 'done') {
          if (evt.page) {
            PAGE = Math.min(evt.page, INFO.pages || evt.page);
            $('#page').value = PAGE;
            $('#pageChip').textContent = '第 ' + PAGE + ' 页';
          }
          setHint('完成 · ' + evt.chars + ' 字 · ' + (evt.capture === 'screen' ? '用屏幕画面' : '用 PDF 墨迹'));
        }
      }
    }
  } catch (e) {
    acc += '\n\n> ' + e;
  } finally {
    clearInterval(timer);
    body.innerHTML = renderMD(acc || '（空）');
    typeset(body);
    if (rev && !/^\s*（/.test(rev)) {
      rvBody.innerHTML = renderMD(rev);
      typeset(rvBody);
    } else {
      rv.hidden = true;
      draftBox.classList.add('plain');
      draftBox.open = true;
    }
    busy = false; $('#btnSend').disabled = false; $('#q').focus();
  }
}

async function sync() {
  setHint('正在从 Edge 取画面…');
  const r = await fetch('/api/peek', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({book: BOOK})});
  const j = await r.json();
  if (!j.ok) { setHint(j.hint || '抓取失败'); return; }
  if (j.page) { PAGE = j.page; $('#page').value = PAGE; $('#pageChip').textContent = '第 ' + PAGE + ' 页'; }
  setHint('已抓到第 ' + (j.page || '?') + ' 页 · ' + Math.round(j.bytes / 1024) + ' KB');
}

function chapterRange(page) {
  const tops = (INFO.toc || []).filter((t) => t.level === 1).sort((x, y) => x.page - y.page);
  if (!tops.length) return [Math.max(1, page - 1), Math.min(INFO.pages, page + 1)];
  let start = tops[0].page;
  for (const t of tops) { if (t.page <= page) start = t.page; }
  const next = tops.find((t) => t.page > page);
  const end = next ? next.page - 1 : INFO.pages;
  return [start, Math.max(start, end)];
}

async function maybePoll() {
  if (POLLING) return;
  try {
    const st = await (await fetch('/api/ingest/status?book=' + encodeURIComponent(BOOK))).json();
    if (st && st.running) {
      POLLING = true;
      await pollIngest();
      POLLING = false;
    }
  } catch (e) {}
}

async function pollIngest() {
  $('#bar').hidden = false;
  for (;;) {
    let st = {};
    try {
      st = await (await fetch('/api/ingest/status?book=' + encodeURIComponent(BOOK))).json();
    } catch (e) { setHint('状态查询失败'); $('#bar').hidden = true; return; }
    const done = (st.done || 0) + (st.skipped || 0) + (st.failed || 0);
    const started = (st.from && st.current) ? Math.min(st.total || 0, Math.max(0, st.current - st.from + 1)) : done;
    const pct = st.total ? Math.round(100 * Math.max(done, started) / st.total) : 0;
    let eta = '';
    if (st.started && done > 2 && st.running) {
      const elapsed = Date.now() / 1000 - st.started;
      const rate = done / Math.max(1, elapsed);
      if (rate > 0) eta = fmtDur((st.total - done) / rate);
    }
    $('#barFill').style.width = Math.min(100, pct) + '%';
    if (st.phase === 'brief') {
      $('#barText').textContent = '页面转写完成，正在生成这本书的背景卡…';
      $('#barFill').style.width = '99%';
    } else {
      $('#barText').textContent = '入账 ' + pct + '% · ' + Math.min(st.current || 0, st.total || 0) + '/' + (st.total || 0) +
        ' 页 · 成功 ' + (st.done || 0) + ' · 失败 ' + (st.failed || 0) + (eta ? ' · 还需 ' + eta : '');
    }
    if (st.error) setHint('入账出错：' + st.error);
    if (!st.running) {
      $('#barFill').style.width = '100%';
      $('#barText').textContent = '入账完成 · 新 ' + (st.done || 0) + ' · 跳过 ' + (st.skipped || 0) + ' · 失败 ' + (st.failed || 0) + (st.brief ? ' · 背景卡已生成' : '');
      setTimeout(() => { $('#bar').hidden = true; }, 4000);
      setHint('入账结束');
      break;
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
  loadBook();
}

async function startIngest(from, to, label) {
  if (busy) return;
  busy = true;
  $('#btnIngest').disabled = true;
  $('#btnAll').disabled = true;
  setHint(label + '：第 ' + from + '–' + to + ' 页，检查中…');
  try {
    // 先看这几页是不是都已经入账过
    try {
      const pj = await (await fetch('/api/ingest/plan?book=' + encodeURIComponent(BOOK) +
        '&from=' + from + '&to=' + to)).json();
      if (pj && pj.total > 0 && pj.missing === 0) {
        setHint(label + '：第 ' + from + '–' + to + ' 页（共 ' + pj.total + ' 页）之前已经入账过了，不用重跑');
        busy = false;
        $('#btnIngest').disabled = false;
        $('#btnAll').disabled = false;
        return;
      }
      if (pj && pj.missing > 0) {
        setHint(label + '：共 ' + pj.total + ' 页，其中 ' + pj.missing + ' 页未入账，只补这些');
      }
    } catch (e) {}

    const r = await fetch('/api/ingest', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({book: BOOK, from: from, to: to}),
    });
    const j = await r.json();
    if (j.error) { setHint('入账失败：' + j.error); }
    else if (j.started) { await pollIngest(); }
    else { setHint('已经有一个入账任务在跑'); await pollIngest(); }
  } finally {
    busy = false;
    $('#btnIngest').disabled = false;
    $('#btnAll').disabled = false;
  }
}

function ingestChapter() {
  const [from, to] = chapterRange(PAGE);
  startIngest(from, to, '入账本章');
}

function ingestAll() {
  startIngest(1, INFO.pages, '全书入账');
}

function applyThinkState() {
  const b = $('#btnThink');
  if (!b) return;
  b.classList.toggle('on', THINKING);
  b.title = THINKING ? '深度思考：开（点击关闭）' : '深度思考：关（点击打开）';
}

async function toggleThink() {
  THINKING = !THINKING;
  applyThinkState();
  setHint(THINKING ? '深度思考：开 · 会显示思考过程' : '深度思考：关 · 回答更快更省');
  try {
    await fetch('/api/config', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({thinking: THINKING})});
  } catch (e) {}
}

async function togglePin() {
  const r = await fetch('/api/pin', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({book: BOOK, toggle: true})});
  const j = await r.json();
  if (!j.found) { setHint('没找到面板窗口'); return; }
  $('#btnPin').style.opacity = j.topmost ? '1' : '0.45';
  setHint(j.topmost ? '窗口已置顶' : '已取消置顶');
}

async function toggleBrief() {
  const d = $('#briefDrawer');
  if (!d.hidden) { d.hidden = true; return; }   // 再点一次关闭
  $('#drawer').hidden = true;                    // 另一个抽屉互斥
  await openBrief();
}

async function toggleSettings() {
  const d = $('#drawer');
  if (!d.hidden) { d.hidden = true; return; }
  $('#briefDrawer').hidden = true;
  await openSettings();
}

async function openBrief() {
  const r = await (await fetch('/api/brief?book=' + encodeURIComponent(BOOK))).json();
  $('#briefText').value = (r && r.text) || '';
  $('#briefDrawer').hidden = false;
}

async function saveBrief() {
  await fetch('/api/brief', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({book: BOOK, text: $('#briefText').value})});
  setHint('约定卡已保存');
  $('#briefDrawer').hidden = true;
  loadBook();
}

async function regenBrief() {
  $('#btnRegenBrief').disabled = true;
  setHint('正在根据已入账的页面生成约定卡…');
  try {
    const r = await (await fetch('/api/brief', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({book: BOOK, regenerate: true})})).json();
    if (r.ok) {
      $('#briefText').value = r.text || '';
      setHint('约定卡已生成 · ' + (r.chars || 0) + ' 字');
      loadBook();
    } else {
      setHint('生成失败：' + (r.error || '未知原因'));
    }
  } catch (e) {
    setHint('生成失败：' + e);
  } finally {
    $('#btnRegenBrief').disabled = false;
  }
}

async function openSettings() {
  const c = await (await fetch('/api/config')).json();
  $('#c_base').value = c.base_url || '';
  $('#c_model').value = c.model || '';
  $('#c_vision').value = c.vision_model || '';
  $('#c_side').value = c.max_side || 1400;
  $('#c_conc').value = c.ingest_concurrency || 6;
  $('#c_prompt').value = c.custom_prompt || '';
  $('#connBrief').textContent = (c.model || '未设置') + ' · ' + (c.api_key_set ? (c.api_key_session ? 'key 仅本次' : 'key 已存') : '未配置 key');
  $('#c_review').checked = !!c.review;
  $('#c_think').checked = !!c.thinking;
  $('#c_effort').value = c.reasoning_effort || 'medium';
  $('#c_key').value = '';
  $('#c_savekey').checked = !c.api_key_session;
  $('#c_think').checked = THINKING;
  $('#drawer').hidden = false;
}

async function saveSettings() {
  const patch = {
    base_url: $('#c_base').value.trim(),
    model: $('#c_model').value.trim(),
    vision_model: $('#c_vision').value.trim(),
    max_side: Number($('#c_side').value) || 1400,
    ingest_concurrency: Number($('#c_conc').value) || 6,
    custom_prompt: $('#c_prompt').value,
    review: $('#c_review').checked,
    thinking: $('#c_think').checked,
    reasoning_effort: $('#c_effort').value,
  };
  const k = $('#c_key').value.trim();
  patch.save_key = $('#c_savekey').checked;
  if (k) patch.api_key = k;
  await fetch('/api/config', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(patch)});
  $('#drawer').hidden = true;
  THINKING = $('#c_think').checked;
  applyThinkState();
  setHint($('#c_savekey').checked ? '设置已保存（key 已存盘）' : '设置已保存（key 只在本次运行有效）');
  try { const c2 = await (await fetch('/api/config')).json(); $('#connBrief').textContent = (c2.model || '未设置') + ' · ' + (c2.api_key_set ? (c2.api_key_session ? 'key 仅本次' : 'key 已存') : '未配置 key'); } catch (e) {}
}

$('#btnSend').onclick = ask;
$('#btnSync').onclick = sync;
$('#btnIngest').onclick = ingestChapter;
$('#btnAll').onclick = ingestAll;
$('#btnSettings').onclick = toggleSettings;
$('#btnPin').onclick = togglePin;
$('#btnThink').onclick = toggleThink;
$('#briefChip').onclick = toggleBrief;
$('#btnSaveBrief').onclick = saveBrief;
$('#btnRegenBrief').onclick = regenBrief;
$('#btnCloseBrief').onclick = () => { $('#briefDrawer').hidden = true; };
$('#btnSaveCfg').onclick = saveSettings;
$('#btnCloseCfg').onclick = () => { $('#drawer').hidden = true; };
$('#page').onchange = (e) => { PAGE = Number(e.target.value) || 1; $('#pageChip').textContent = '第 ' + PAGE + ' 页'; };
$('#q').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); }
});
if (!BOOK && new URLSearchParams(location.search).get('auto')) {
  fetch('/api/current')
    .then((r) => r.json())
    .then((c) => {
      if (c && c.book) {
        location.replace('/?book=' + encodeURIComponent(c.book) + '&auto=1');
      } else {
        document.querySelector('#bookTitle').textContent = '还没有打开的书：先把 PDF 拖到桌面快捷方式上';
      }
    })
    .catch(() => {});
} else {
  loadBook();
}
