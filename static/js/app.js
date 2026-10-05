const $ = id => document.getElementById(id);
const esc = s => { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; };
const ICON_DL = '<svg viewBox="0 0 24 24"><path d="M12 16l-5-5h3V4h4v7h3l-5 5zm-7 2h14v2H5v-2z"/></svg>';
const ICON_OK = '<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>';
const ICON_ERR = '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>';

/* ═══ State ═══ */
let mode = 'single', jobId = null, polling = false, lastInfo = null;

fetch('/api/health').then(r => r.json()).then(h => { if (!h.ffmpeg) $('ffmpegAlert').style.display = 'block'; }).catch(() => {});

/* ═══ URL parsing ═══ */
function parseUrl(url) {
    const m = (url || '').match(/spotify\.com\/(?:intl-[a-z]{2}\/)?(track|playlist|album)\/([A-Za-z0-9]+)/);
    return m ? { type: m[1] === 'track' ? 'song' : m[1], id: m[2] } : null;
}
function bulkUrls() {
    const seen = new Set();
    return $('bulkInput').value.split(/\s+/).map(s => s.trim()).filter(s => parseUrl(s) && !seen.has(s) && seen.add(s));
}

/* ═══ UI helpers ═══ */
function setHint(text, cls) { $('hint').innerHTML = cls ? `<span class="${cls}">${esc(text)}</span>` : esc(text); }
function setTag(text, cls) {
    const t = $('typeTag');
    if (!text) { t.hidden = true; return; }
    t.hidden = false; t.textContent = text; t.className = 'tag' + (cls ? ' ' + cls : '');
}
function setBusy(btn, on, label) {
    btn.disabled = on;
    const span = btn.querySelector('span'), svg = btn.querySelector('svg'), old = btn.querySelector('.spin');
    if (on && !old) { const s = document.createElement('div'); s.className = 'spin'; btn.prepend(s); }
    if (!on && old) old.remove();
    if (svg) svg.style.display = on ? 'none' : '';
    if (span) span.textContent = label;
}
function resetResults() {
    $('previewSection').style.display = 'none';
    $('dlSection').style.display = 'none';
}
const fmtTime = s => s ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` : '';

/* ═══ Mode & inputs ═══ */
function setMode(m) {
    mode = m;
    $('tabSingle').classList.toggle('active', m === 'single');
    $('tabBulk').classList.toggle('active', m === 'bulk');
    $('singleWrap').style.display = m === 'single' ? 'block' : 'none';
    $('bulkWrap').style.display = m === 'bulk' ? 'block' : 'none';
    $('viewBtn').style.display = m === 'single' ? '' : 'none';
    document.querySelector('.btn-row').style.gridTemplateColumns = m === 'single' ? '' : '1fr';
    resetResults(); setTag(''); setHint('');
    m === 'single' ? onSingleInput() : onBulkInput();
}

function onSingleInput() {
    const v = $('urlInput').value.trim();
    $('clearBtn').style.display = v ? 'flex' : 'none';
    const p = parseUrl(v);
    if (p) { setTag(p.type, p.type === 'song' ? '' : 'purple'); setHint(''); }
    else { setTag(''); if (v) setHint('Not a Spotify song, album or playlist link', 'err'); else setHint(''); }
}
function onBulkInput() {
    const n = bulkUrls().length;
    $('hint').innerHTML = `<span><b>${n}</b> valid link${n !== 1 ? 's' : ''} detected</span>`;
    n ? setTag('bulk · ' + n, 'warn') : setTag('');
}
$('urlInput').addEventListener('input', onSingleInput);
$('bulkInput').addEventListener('input', onBulkInput);
$('urlInput').addEventListener('keydown', e => { if (e.key === 'Enter') handleView(); });
$('clearBtn').addEventListener('click', () => { $('urlInput').value = ''; onSingleInput(); resetResults(); $('urlInput').focus(); });
$('formatSel').addEventListener('change', () => {
    const fmt = $('formatSel').value;
    $('bitrateSel').disabled = ['flac', 'wav'].includes(fmt);
    document.querySelectorAll('#formatSeg .seg-btn').forEach(b => {
        const on = b.dataset.v === fmt;
        b.classList.toggle('active', on);
        b.setAttribute('aria-checked', on);
    });
});
$('formatSeg').addEventListener('click', e => {
    const btn = e.target.closest('.seg-btn');
    if (!btn) return;
    $('formatSel').value = btn.dataset.v;
    $('formatSel').dispatchEvent(new Event('change'));
});

/* ═══ Preview ═══ */
async function handleView() {
    const url = $('urlInput').value.trim();
    if (!url) { setHint('Paste a Spotify link first', 'err'); return; }
    if (!parseUrl(url)) { setHint('Not a Spotify song, album or playlist link', 'err'); return; }

    setBusy($('viewBtn'), true, 'Loading...');
    setHint('Fetching info...');
    try {
        const data = await (await fetch('/fetch-info', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url })
        })).json();
        if (!data.success) { setHint(data.message || 'Could not load that link', 'err'); return; }
        lastInfo = data;
        showPreview(data, url);
        setHint(data.type === 'song' ? 'Song loaded' : `${data.tracks.length} tracks loaded`, 'ok');
    } catch {
        setHint('Server not reachable - is app.py running?', 'err');
    } finally {
        setBusy($('viewBtn'), false, 'Preview');
    }
}

function showPreview(info, url) {
    const thumb = $('pvThumb');
    if (info.thumbnail) { thumb.src = info.thumbnail; thumb.classList.remove('hidden'); } else thumb.classList.add('hidden');
    $('pvTitle').textContent = info.title || 'Unknown';
    $('pvSub').textContent = info.type === 'song' ? info.artist : (info.artist || '');
    const n = info.tracks.length;
    $('pvTags').innerHTML = `<span class="tag ${info.type === 'song' ? '' : 'purple'}">${info.type}</span>` +
        (info.type !== 'song' ? `<span class="tag muted">${n} tracks</span>` : '');

    const isSong = info.type === 'song';
    $('embedBox').style.display = isSong ? 'block' : 'none';
    if (isSong) $('embedPlayer').src = info.embed_url;
    $('pickerBox').style.display = isSong ? 'none' : 'block';

    if (!isSong) {
        $('trackPicker').innerHTML = info.tracks.map((t, i) => `
            <li class="track-row">
                <input type="checkbox" class="pick" value="${esc(t.id)}" checked>
                <span class="num">${i + 1}</span>
                <div class="meta"><div class="t">${esc(t.title)}</div><div class="a">${esc(t.artist)}</div></div>
                <span class="dur">${fmtTime(t.duration)}</span>
            </li>`).join('');
        $('selAll').checked = true;
        updateSelCount();
    }
    $('openLink').href = url;
    $('previewSection').style.display = 'block';
    $('previewSection').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function pickedIds() { return [...document.querySelectorAll('.pick:checked')].map(c => c.value); }
function updateSelCount() {
    const all = document.querySelectorAll('.pick'), on = pickedIds().length;
    $('selCount').textContent = on;
    $('selAll').checked = on === all.length;
}
$('trackPicker').addEventListener('change', updateSelCount);
$('selAll').addEventListener('change', e => { document.querySelectorAll('.pick').forEach(c => c.checked = e.target.checked); updateSelCount(); });

/* ═══ Download ═══ */
async function handleDownload() {
    const body = { format: $('formatSel').value, bitrate: $('bitrateSel').value };
    if (mode === 'bulk') {
        body.urls = bulkUrls();
        if (!body.urls.length) { setHint('No valid Spotify links found - add one per line', 'err'); return; }
    } else {
        const url = $('urlInput').value.trim();
        if (!url) { setHint('Paste a Spotify link first', 'err'); return; }
        if (!parseUrl(url)) { setHint('Not a Spotify song, album or playlist link', 'err'); return; }
        body.urls = [url];
        // honour the track selection if this exact link is being previewed
        if (lastInfo && lastInfo.type !== 'song' && $('previewSection').style.display === 'block' && lastInfo.id === parseUrl(url).id) {
            const ids = pickedIds();
            if (!ids.length) { setHint('Select at least one track', 'err'); return; }
            if (ids.length < lastInfo.tracks.length) body.selected = ids;
        }
    }

    setBusy($('dlBtn'), true, 'Starting...');
    try {
        const data = await (await fetch('/start-download', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
        })).json();
        if (!data.success) { setHint(data.message || 'Could not start download', 'err'); setBusy($('dlBtn'), false, 'Download'); return; }
        jobId = data.job_id;
        setHint('');
        initProgress();
        poll();
    } catch {
        setHint('Server not reachable - is app.py running?', 'err');
        setBusy($('dlBtn'), false, 'Download');
    }
}

function initProgress() {
    $('dlIcon').className = 'dl-icon'; $('dlIcon').innerHTML = '<div class="ring"></div>';
    $('dlTitle').textContent = 'Preparing...'; $('dlSub').textContent = 'Reading your link';
    $('barFill').style.width = '2%'; $('barFill').className = 'bar-fill'; $('barCount').textContent = '0 / 0';
    $('fileList').innerHTML = ''; $('actions').style.display = 'none';
    $('cancelBtn').style.display = '';
    $('dlSection').style.display = 'block';
    $('dlSection').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

const STATUS_TEXT = { queued: 'Waiting...', searching: 'Finding best match...', downloading: 'Downloading...', converting: 'Converting...', tagging: 'Adding tags...', cancelled: 'Cancelled' };

async function poll() {
    if (!jobId || polling) return;
    polling = true;
    try {
        while (true) {
            let d;
            try { d = await (await fetch('/download-status/' + jobId)).json(); }
            catch { await new Promise(r => setTimeout(r, 2500)); continue; }
            if (!d.success) break;
            render(d);
            if (['done', 'error', 'cancelled'].includes(d.status)) break;
            await new Promise(r => setTimeout(r, 1000));
        }
    } finally { polling = false; }
}

function render(d) {
    const finished = ['done', 'error', 'cancelled'].includes(d.status);
    $('barFill').style.width = Math.max(2, d.percent) + '%';
    $('barCount').textContent = `${d.done} / ${d.total}`;

    if (d.status === 'resolving' || d.total === 0) {
        $('dlTitle').textContent = 'Preparing...'; $('dlSub').textContent = d.message || '';
    } else if (!finished) {
        $('dlTitle').textContent = d.name ? `Downloading "${d.name}"` : 'Downloading...';
        $('dlSub').textContent = `${d.done} of ${d.total} complete` + (d.failed ? ` · ${d.failed} failed` : '');
    }

    // track list
    $('fileList').innerHTML = d.tracks.map((t, i) => {
        const active = ['searching', 'downloading', 'converting', 'tagging'].includes(t.status);
        const sub = t.status === 'done' ? (t.file ? 'Ready' : 'Done') : t.status === 'failed' ? (t.error || 'Failed') : STATUS_TEXT[t.status] || t.status;
        return `<li class="file-item">
            <span class="num">${String(i + 1).padStart(2, '0')}</span>
            <div class="meta">
                <div class="t" title="${esc(t.title)}">${esc(t.title)}</div>
                <div class="s ${t.status}">${esc(t.artist.split(', ').slice(0, 2).join(', '))} · ${esc(sub)}</div>
                ${active ? `<div class="mini-bar"><i style="width:${t.progress}%"></i></div>` : ''}
            </div>
            ${t.status === 'done' && t.file
                ? `<button class="icon-btn" title="Save file" onclick="dlFile(${i})">${ICON_DL}</button>`
                : `<span class="status-dot ${active ? 'active' : t.status === 'failed' ? 'failed' : ''}"></span>`}
        </li>`;
    }).join('');
    window._files = d.tracks.map(t => t.file);

    if (!finished) return;

    $('cancelBtn').style.display = 'none';
    setBusy($('dlBtn'), false, 'Download');
    if (d.status === 'error') {
        $('dlIcon').className = 'dl-icon error'; $('dlIcon').innerHTML = ICON_ERR;
        $('dlTitle').textContent = 'Download failed'; $('dlSub').textContent = d.error || 'Something went wrong';
        $('barFill').className = 'bar-fill fail'; $('barFill').style.width = '100%';
    } else if (d.status === 'cancelled') {
        $('dlIcon').className = 'dl-icon error'; $('dlIcon').innerHTML = ICON_ERR;
        $('dlTitle').textContent = 'Cancelled'; $('dlSub').textContent = `${d.done} of ${d.total} finished before cancelling`;
    } else {
        $('dlIcon').className = 'dl-icon'; $('dlIcon').innerHTML = ICON_OK;
        $('dlTitle').textContent = d.failed ? 'Finished with errors' : 'Download complete';
        $('dlSub').textContent = `${d.done} file${d.done !== 1 ? 's' : ''} ready` + (d.failed ? ` · ${d.failed} failed` : '');
        $('barFill').style.width = '100%';
        if (d.failed) $('barFill').className = 'bar-fill fail';
    }
    const retryable = d.tracks.some(t => ['failed', 'cancelled'].includes(t.status));
    $('retryBtn').style.display = retryable ? '' : 'none';
    $('zipBtn').style.display = d.done > 1 ? '' : 'none';
    $('actions').style.display = (retryable || d.done > 1) ? 'flex' : 'none';

    if (!window._autoSaved?.[jobId] && d.done === 1 && d.total === 1) {
        (window._autoSaved ||= {})[jobId] = true;
        dlFile(0);
    }
}

function dlFile(i) {
    const name = window._files?.[i];
    if (!name) return;
    const a = document.createElement('a');
    a.href = `/get-file/${jobId}/${encodeURIComponent(name)}`;
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
}
function downloadZip() { window.location.href = '/get-zip/' + jobId; }
async function cancelJob() {
    if (!jobId) return;
    $('cancelBtn').disabled = true; $('cancelBtn').textContent = 'Cancelling...';
    await fetch('/cancel/' + jobId, { method: 'POST' });
    $('cancelBtn').disabled = false; $('cancelBtn').textContent = 'Cancel';
}
async function retryFailed() {
    const r = await (await fetch('/retry/' + jobId, { method: 'POST' })).json();
    if (!r.success) return;
    $('actions').style.display = 'none'; $('cancelBtn').style.display = '';
    $('barFill').className = 'bar-fill';
    setBusy($('dlBtn'), true, 'Download');
    poll();
}
