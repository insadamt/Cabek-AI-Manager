/** Connect the local configuration and update UI to manager operations.
 * Depends on same-origin JSON APIs; inserts remote release text as text only.
 */
const $ = (selector) => document.querySelector(selector);
let latestStatus;
let lastJobId;
let savedConfiguration;

async function api(path, method = 'GET', body) {
  const response = await fetch(`/api/${path}`, {
    method,
    headers: method === 'GET' ? {} : { 'Content-Type': 'application/json' },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || value.detail || 'The request failed.');
  return value;
}

function notice(message, error = false) {
  $('#notice').textContent = message;
  $('#notice').classList.toggle('error', error);
  $('#notice').hidden = !message;
}

async function perform(action) {
  try {
    await api(action, 'POST', {});
    notice('Operation started. Follow its progress in Activity.');
    await refresh();
    $('#activity').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) { notice(error.message, true); }
}

function cell(row, text, className = '') {
  const element = document.createElement('td');
  element.textContent = text;
  element.className = className;
  row.append(element);
}

function renderComponents(updates, installed) {
  const tbody = $('#components');
  tbody.replaceChildren();
  for (const item of updates.components) {
    const row = document.createElement('tr');
    cell(row, item.name);
    cell(row, installed[item.key]?.tag || 'Not installed');
    cell(row, item.latest?.tag || 'Unavailable');
    cell(row, item.error || (item.update_available ? 'Update available' : 'Up to date'), item.error ? 'bad' : item.update_available ? 'warning' : 'good');
    tbody.append(row);
  }
  if (!updates.components.length) {
    const row = document.createElement('tr');
    cell(row, 'Check releases to see your ecosystem versions.');
    row.firstChild.colSpan = 4;
    tbody.append(row);
  }
}

async function refresh() {
  try {
    const status = await api('status');
    latestStatus = status;
    const installed = Object.keys(status.installed).length > 0;
    const running = status.job?.status === 'running';
    const count = status.updates.components.filter((item) => item.update_available).length;
    $('#manager-version').textContent = `Manager ${status.version}`;
    $('#installation-state').textContent = installed ? 'Installed' : 'Ready for setup';
    $('#update-count').textContent = count;
    $('#install').hidden = installed;
    $('#update-all').hidden = !installed || (!count && !status.configuration_pending);
    $('#update-all').textContent = count ? 'Update All' : 'Apply configuration';
    for (const id of ['start', 'stop', 'open-app']) $(`#${id}`).hidden = !installed;
    $('#open-app').href = status.application_url;
    for (const button of document.querySelectorAll('.toolbar button, #configuration button')) button.disabled = running;
    renderComponents(status.updates, status.installed);
    const job = status.job;
    $('#job-status').textContent = job?.status || 'Idle';
    $('#job-title').textContent = job?.name || 'Ready when you are';
    if (job) {
      $('#events').textContent = job.events.map((event) => `${new Date(event.at).toLocaleTimeString()}  ${event.message}`).join('\n') || 'Preparing operation…';
      if (job.error) $('#events').textContent += `\n\n${job.error}`;
      if (lastJobId !== `${job.id}:${job.status}`) {
        if (job.status === 'failed' || job.status === 'interrupted') notice(job.error, true);
        if (job.status === 'completed') {
          notice(count ? `${count} component update${count === 1 ? '' : 's'} available. Click Update All when ready.` : 'Operation completed.');
          await refreshServices();
        }
        lastJobId = `${job.id}:${job.status}`;
      }
    }
  } catch (error) { notice(`Cannot reach the manager: ${error.message}`, true); }
}

async function refreshServices() {
  try {
    const result = await api('services');
    $('#service-count').textContent = result.services.length;
    $('#running-count').textContent = result.services.filter((item) => item.State === 'running').length;
    $('#services').replaceChildren();
    for (const service of result.services) {
      const button = document.createElement('button');
      button.className = 'quiet';
      button.textContent = `${service.Service} · ${service.Health || service.State}`;
      button.addEventListener('click', async () => {
        try {
          const logs = await api(`logs/${encodeURIComponent(service.Service)}`);
          $('#logs-title').textContent = `${service.Service} logs`;
          $('#logs-text').textContent = logs.text || 'No recent logs.';
          $('#logs-dialog').showModal();
        } catch (error) { notice(error.message, true); }
      });
      $('#services').append(button);
    }
    if (result.error) notice(result.error, true);
  } catch (error) { notice(error.message, true); }
}

async function loadConfiguration() {
  const value = await api('configuration');
  savedConfiguration = value;
  const form = $('#configuration');
  for (const [name, item] of Object.entries(value)) {
    const input = form.elements.namedItem(name);
    if (!input) continue;
    if (input.type === 'checkbox') input.checked = item;
    else input.value = Array.isArray(item) ? item.join(name === 'camera_channels' ? ',' : '\n') : item;
  }
  for (const name of ['github_token', 'nvr_password']) {
    if (value[`${name}_configured`]) form.elements.namedItem(name).placeholder = 'Configured · leave empty to keep';
  }
  $('#station-mode').textContent = value.profile === 'station' ? 'Station' : 'Demo';
  toggleCameraFields();
}

function toggleCameraFields() {
  $('#camera-fields').hidden = $('#configuration').elements.profile.value !== 'station';
}

$('#configuration').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form));
  for (const name of ['app_port', 'api_port', 'interior_switch_id']) payload[name] = Number(payload[name]);
  for (const name of ['lighting_enabled', 'interior_enabled', 'ocr_enabled']) payload[name] = form.elements.namedItem(name).checked;
  payload.camera_channels = payload.camera_channels.split(',').map((value) => Number(value.trim())).filter(Boolean);
  payload.dataset_paths = payload.dataset_paths.split('\n').map((value) => value.trim()).filter(Boolean);
  try {
    await api('configuration', 'PUT', payload);
    await loadConfiguration();
    $('#configuration-status').textContent = 'Configuration saved.';
    notice('Configuration saved. Install the ecosystem or apply the new configuration.');
    await refresh();
  } catch (error) { notice(error.message, true); }
});
$('#configuration').elements.profile.addEventListener('change', toggleCameraFields);
for (const action of ['check-updates', 'install', 'update-all', 'start', 'stop']) $(`#${action}`).addEventListener('click', () => perform(action));
$('#refresh-services').addEventListener('click', refreshServices);
$('#close-logs').addEventListener('click', () => $('#logs-dialog').close());
$('#check-prerequisites').addEventListener('click', async () => {
  const button = $('#check-prerequisites');
  button.disabled = true;
  try {
    const result = await api('prerequisites');
    $('#prerequisites').replaceChildren();
    for (const check of result.checks) {
      const paragraph = document.createElement('p');
      paragraph.textContent = `${check.ok ? '✓' : '✕'} ${check.name}: ${check.detail}`;
      paragraph.className = check.ok ? 'good' : 'bad';
      $('#prerequisites').append(paragraph);
    }
    $('#serial-devices').replaceChildren(...result.serial_devices.map((path) => {
      const option = document.createElement('option'); option.value = path; return option;
    }));
  } catch (error) { notice(error.message, true); }
  finally { button.disabled = false; }
});
loadConfiguration().then(refresh).then(refreshServices).catch((error) => notice(error.message, true));
setInterval(refresh, 3000);
