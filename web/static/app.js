const form = document.querySelector('#download-form');
const input = document.querySelector('#url');
const submit = document.querySelector('#submit');
const result = document.querySelector('#result');
const title = document.querySelector('#status-title');
const percent = document.querySelector('#percent');
const bar = document.querySelector('#bar');
const text = document.querySelector('#status-text');
const save = document.querySelector('#save-link');
let timer;

function show(status, message, progress = 0, error = false) {
  result.hidden = false;
  result.classList.toggle('error', error);
  title.textContent = status;
  text.textContent = message;
  percent.textContent = progress ? `${Math.round(progress)}%` : '';
  bar.style.width = `${progress}%`;
}

async function readJson(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'The download could not start.');
  return data;
}

async function poll(id) {
  try {
    const data = await readJson(await fetch(`/api/jobs/${encodeURIComponent(id)}`, { cache: 'no-store' }));
    if (data.status === 'ready') {
      show('Your video is ready', data.filename, 100);
      save.href = `/api/jobs/${encodeURIComponent(id)}/file`;
      save.hidden = false;
      submit.disabled = false;
      submit.textContent = 'Get another video ↗';
      return;
    }
    if (data.status === 'error') {
      show('Could not download this video', data.message, 0, true);
      submit.disabled = false;
      return;
    }
    show(data.status === 'processing' ? 'Finishing video…' : 'Downloading video…', data.message, data.progress);
    timer = window.setTimeout(() => poll(id), 1000);
  } catch (error) {
    show('Connection lost', error.message, 0, true);
    submit.disabled = false;
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  window.clearTimeout(timer);
  save.hidden = true;
  submit.disabled = true;
  show('Checking video…', 'This may take a moment on a free server.');
  try {
    const data = await readJson(await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: input.value.trim() }),
    }));
    poll(data.id);
  } catch (error) {
    show('Could not start', error.message, 0, true);
    submit.disabled = false;
  }
});
