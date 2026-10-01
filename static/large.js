"use strict";
const main = document.getElementById('large-main');
const upload = document.getElementById('large-upload');
if (main && upload) {
  const csrf = main.dataset.csrf;
  const status = document.getElementById('large-status');
  const progress = document.getElementById('large-progress');
  const fileInput = document.getElementById('large-file');
  let sending = false;
  async function api(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', ...options,
      headers: {'X-CSRF-Token': csrf, ...(options.headers || {})}});
    let result;
    try { result = await response.json(); } catch { throw new Error('O servidor ficou indisponível. Recarregue a página para verificar sua importação.'); }
    if (!response.ok) throw new Error(result.error || 'Não foi possível concluir. Recarregue a página.');
    return result;
  }
  function addJob(job) {
    const article = document.createElement('article');
    article.className = 'large-job'; article.dataset.job = job.id;
    const name = document.createElement('strong'); name.textContent = job.name;
    const text = document.createElement('p'); text.className = 'job-status';
    const actions = document.createElement('div'); actions.className = 'job-actions';
    const open = document.createElement('a'); open.className = 'secondary-button job-open';
    open.href = `/large/${job.id}/data`; open.textContent = 'Explorar dados'; open.hidden = true;
    const finish = document.createElement('button'); finish.type = 'button'; finish.className = 'secondary-button job-finish'; finish.textContent = 'Processar envio'; finish.hidden = true;
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary-button job-delete'; remove.textContent = 'Cancelar / descartar';
    actions.append(open, finish, remove); article.append(name, text, actions);
    document.getElementById('large-jobs').prepend(article);
    document.getElementById('jobs-empty').hidden = true;
    bind(article); return article;
  }
  function show(article, job) {
    article.querySelector('.job-status').textContent = job.state === 'uploading'
      ? `Enviados ${(job.received / 1048576).toFixed(1)} de ${(job.size / 1048576).toFixed(1)} MB. Se o envio foi interrompido, descarte e envie novamente.`
      : `${job.message} · ${job.rows.toLocaleString('pt-BR')} registros`;
    article.querySelector('.job-open').hidden = job.state !== 'ready';
    article.querySelector('.job-finish').hidden = job.state !== 'uploading' || job.received !== job.size;
  }
  async function poll(article) {
    if (!article.isConnected) return;
    try {
      const job = await api(`/large/${article.dataset.job}/status`);
      show(article, job);
      if (job.state === 'processing' || job.state === 'uploading') setTimeout(() => poll(article), 3000);
    } catch (error) { article.querySelector('.job-status').textContent = error.message; }
  }
  function bind(article) {
    article.querySelector('.job-delete').addEventListener('click', async event => {
      event.target.disabled = true;
      try { await api(`/large/${article.dataset.job}/cancel`, {method:'POST'}); article.remove(); }
      catch(error) { status.textContent = error.message; event.target.disabled = false; }
    });
    article.querySelector('.job-finish').addEventListener('click', async event => {
      event.target.disabled = true;
      try { show(article, await api(`/large/${article.dataset.job}/finish`, {method:'POST'})); poll(article); }
      catch(error) { status.textContent = error.message; }
      finally { event.target.disabled = false; }
    });
  }
  for (const article of document.querySelectorAll('[data-job]')) { bind(article); poll(article); }
  upload.addEventListener('submit', async event => {
    event.preventDefault(); if (sending) return;
    const file = fileInput.files[0]; if (!file) return;
    if (file.size > Number(fileInput.dataset.max)) { status.textContent = 'O limite deste modo é de 250 MB por arquivo.'; return; }
    sending = true; const button = upload.querySelector('button[type=submit]'); button.disabled = true;
    progress.hidden = false; progress.value = 0; status.textContent = 'Preparando o envio…';
    let article;
    try {
      const header = document.getElementById('large-header').value;
      const job = await api('/large/start', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:file.name,size:file.size,header:header === '' ? null : Number(header)})});
      article = addJob(job);
      for(let offset=0; offset<file.size; offset+=4194304) {
        const part = file.slice(offset, offset+4194304);
        const result = await api(`/large/${job.id}/chunk?offset=${offset}`, {method:'POST',headers:{'Content-Type':'application/octet-stream'},body:part});
        progress.value = 100*result.received/file.size;
        status.textContent = `Enviando… ${Math.round(progress.value)}%`; show(article, result);
      }
      const result = await api(`/large/${job.id}/finish`, {method:'POST'});
      show(article, result); poll(article); status.textContent = 'Envio concluído. Acompanhe o processamento abaixo.';
    } catch(error) { status.textContent = error.message; if(article) poll(article); }
    finally { sending=false; button.disabled=false; }
  });
}
// Colunas de outra aba não devem ser reutilizadas por posição silenciosamente.
const sheetSelect = document.querySelector('.large-filters select[name=sheet]');
if(sheetSelect) sheetSelect.addEventListener('change', () => {
  const form = sheetSelect.form;
  form.querySelector('[name=metric]').value = '-1';
  form.querySelector('[name=group]').value = '-1';
  form.querySelector('[name=category]').value = '';
  form.submit();
});
