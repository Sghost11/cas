import json
import os
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views import View

from .models import Device, Port, Site
from .services import (
    import_cli_for_device,
    serialize_ports,
)


class DeviceListView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        _ensure_postgres_seeded()
        devices = Device.objects.select_related("site").order_by("hostname")
        payload = []
        for device in devices:
            payload.append(
                {
                    "id": device.id,
                    "hostname": device.hostname,
                    "ip": device.ip,
                    "model": device.model,
                    "os_version": device.os_version,
                    "serial": device.serial,
                    "device_type": device.device_type,
                    "site": device.site.name if device.site else "",
                    "last_sync": device.last_sync,
                }
            )
        return JsonResponse({"status": "ok", "devices": payload})


class DeviceDbListView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        _ensure_postgres_seeded()
        devices = Device.objects.select_related("site").order_by("hostname")
        payload = []
        for device in devices:
            payload.append(
                {
                    "id": device.id,
                    "hostname": device.hostname,
                    "ip": device.ip,
                    "site": device.site.name if device.site else "",
                    "last_sync": device.last_sync,
                }
            )
        return JsonResponse({"status": "ok", "devices": payload})


class DeviceDetailView(View):
    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        device = Device.objects.get(pk=pk)
        payload = {
            "id": device.id,
            "hostname": device.hostname,
            "ip": device.ip,
            "model": device.model,
            "os_version": device.os_version,
            "serial": device.serial,
            "device_type": device.device_type,
            "site": device.site.name if device.site else "",
            "last_sync": device.last_sync,
        }
        return JsonResponse({"status": "ok", "device": payload})


@method_decorator(csrf_exempt, name="dispatch")
class DeviceSyncView(View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        from devices.tasks import sync_device_task

        task = sync_device_task.delay(pk)
        return JsonResponse({"status": "accepted", "task_id": task.id})


@method_decorator(csrf_exempt, name="dispatch")
class ImportCLIView(View):
    def post(self, request: HttpRequest) -> HttpResponse:
        payload = request.body.decode("utf-8", errors="ignore")
        if not payload:
            return JsonResponse({"status": "error", "message": "empty body"}, status=400)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "invalid json"}, status=400)

        device_id = data.get("device_id")
        raw_cli = data.get("raw_cli")
        if not device_id or not raw_cli:
            return JsonResponse(
                {"status": "error", "message": "device_id and raw_cli required"},
                status=400,
            )

        device = Device.objects.get(pk=device_id)
        ports = import_cli_for_device(device, raw_cli)
        return JsonResponse({"status": "ok", "ports": serialize_ports(ports)})


class DevicePortsView(View):
    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        device = Device.objects.get(pk=pk)
        ports = Port.objects.filter(device=device).order_by("interface")
        return JsonResponse({"status": "ok", "ports": serialize_ports(ports)})


class DeviceValidateView(View):
    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        from devices.tasks import validate_device_task

        task = validate_device_task.delay(pk)
        return JsonResponse({"status": "accepted", "task_id": task.id})


class DeviceOpsUiView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        _ensure_postgres_seeded()
        html = """<!doctype html>
<html lang=\"es\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>NetAuto | Operacion 802.1X</title>
    <link rel=\"stylesheet\" href=\"/static/ui.css\" />
  </head>
  <body>
    <div class=\"ops-layout\">
      <header class=\"ops-topbar\">
        <div>
          <h1>Operacion 802.1X</h1>
          <p>Sincroniza puertos, valida y despliega cambios desde un solo tablero.</p>
        </div>
        <div class=\"ops-actions\">
          <button class=\"ghost\" id=\"refreshOpsBtn\">Actualizar</button>
          <button class=\"ghost\" id=\"syncBtn\">Sync</button>
          <button class=\"ghost\" id=\"validateBtn\">Validar</button>
          <button class=\"ghost\" id=\"diffTopBtn\">Ver diff</button>
        </div>
        <div class=\"ops-search\">
          <span class=\"search-icon\">⌕</span>
          <input type=\"search\" id=\"opsSearch\" placeholder=\"Buscar puerto, descripcion o estado\" />
        </div>
      </header>

      <div class=\"ops-banner\" id=\"statusBanner\">Listo.</div>
      <div class=\"progress-wrap\" id=\"syncProgressWrap\">
        <div class=\"progress-label\" id=\"syncProgressLabel\">Progreso: 0%</div>
        <div class=\"progress-bar\">
          <div class=\"progress-fill\" id=\"syncProgressFill\"></div>
        </div>
        <div class=\"progress-value\" id=\"syncProgressValue\">0%</div>
        <div class=\"progress-steps\" id=\"syncProgressSteps\">
          <div class=\"step\" data-step=\"1\">
            <span class=\"dot\"></span>
            <span class=\"label\">Inicio</span>
          </div>
          <div class=\"step\" data-step=\"2\">
            <span class=\"dot\"></span>
            <span class=\"label\">Conexion</span>
          </div>
          <div class=\"step\" data-step=\"3\">
            <span class=\"dot\"></span>
            <span class=\"label\">Lectura</span>
          </div>
          <div class=\"step\" data-step=\"4\">
            <span class=\"dot\"></span>
            <span class=\"label\">Listo</span>
          </div>
        </div>
      </div>

      <section class=\"ops-grid\">
        <aside class=\"ops-panel\">
          <h3>Dispositivos reales</h3>
          <p class=\"muted\">Inventario operativo en PostgreSQL.</p>
          <div id=\"deviceList\" class=\"device-list\"></div>
        </aside>

        <main class=\"ops-panel ops-main\">
          <section class=\"ops-kpis\">
            <div class=\"kpi-card\">
              <span>Total puertos</span>
              <strong id=\"kpiTotal\">0</strong>
            </div>
            <div class=\"kpi-card\">
              <span>Candidatos MIGRAR</span>
              <strong id=\"kpiMigrate\">0</strong>
            </div>
            <div class=\"kpi-card\">
              <span>Excluidos</span>
              <strong id=\"kpiExclude\">0</strong>
            </div>
            <div class=\"kpi-card\">
              <span>Revisar</span>
              <strong id=\"kpiReview\">0</strong>
            </div>
            <div class=\"kpi-card\">
              <span>Ya migrados</span>
              <strong id=\"kpiMigrated\">0</strong>
            </div>
          </section>

          <div class=\"ops-toolbar\">
            <div>
              <h3 id=\"selectedDeviceTitle\">Selecciona un dispositivo</h3>
              <span id=\"selectedDeviceMeta\" class=\"muted\">-</span>
            </div>
            <div class=\"ops-toolbar-actions\"></div>
          </div>

          <div class=\"ops-content\">
            <div class=\"ops-table-wrap\">
              <div class=\"table-scroll\">
                <table>
                <thead>
                  <tr>
                    <th><input type=\"checkbox\" id=\"selectAllPorts\" /></th>
                    <th>Interface</th>
                    <th>VLAN</th>
                    <th>Modo</th>
                    <th>Descripcion</th>
                    <th>Estado</th>
                    <th>Validacion</th>
                  </tr>
                </thead>
                <tbody id=\"portsTable\"></tbody>
                </table>
              </div>
            <div class=\"ops-table-actions\">
              <label class=\"ghost\">
                Filas
                <select id=\"pageSizeSelect\">
                  <option value=\"20\">20</option>
                  <option value=\"50\">50</option>
                  <option value=\"100\" selected>100</option>
                    <option value=\"200\">200</option>
                  </select>
                </label>
                <div class=\"ghost\" id=\"pager\">
                  <button class=\"ghost\" id=\"prevPageBtn\">Prev</button>
                  <span id=\"pageIndicator\">1 / 1</span>
                  <button class=\"ghost\" id=\"nextPageBtn\">Next</button>
                </div>
                <button class=\"ghost\" id=\"filterAll\">Todos</button>
                <button class=\"ghost\" id=\"filterMigrate\">Migrar</button>
                <button class=\"ghost\" id=\"filterExclude\">Excluir</button>
                <button class=\"ghost\" id=\"filterReview\">Revisar</button>
                <button class=\"ghost\" id=\"filterMigrated\">Ya migrado</button>
                <button class=\"ghost\" id=\"bulkExcludeBtn\">Excluir seleccion</button>
                <button class=\"ghost\" id=\"exportBtn\">Exportar</button>
              </div>
            </div>

            <div class=\"ops-side\">
              <div class=\"ops-card\">
                <h4>Change Request</h4>
                <p class=\"muted\">Solo se incluyen puertos con accion MIGRAR. Desmarca para excluir.</p>
                <button class=\"primary\" id=\"createCrBtn\">Crear CR</button>
                <button class=\"ghost\" id=\"openDiffBtn\">Ver diff</button>
              </div>

              <div class=\"ops-card\">
                <h4>Flujo de despliegue</h4>
                <label>ID Change Request</label>
                <input type=\"number\" id=\"crIdInput\" placeholder=\"Ej: 1\" />
                <div class=\"ops-inline\">
                  <button class=\"ghost\" id=\"approveBtn\">Aprobar</button>
                  <button class=\"primary\" id=\"deployBtn\">Desplegar</button>
                </div>
                <div class=\"ops-inline\">
                  <button class=\"ghost\" id=\"resultsBtn\">Ver logs</button>
                  <button class=\"ghost\" id=\"diffBtn\">Ver diff</button>
                </div>
              </div>

              <div class=\"ops-card\">
                <h4>Logs</h4>
                <pre id=\"logOutput\">Sin ejecuciones recientes.</pre>
                <div class=\"ops-debug\" id=\"opsDebug\"></div>
              </div>

              <div class=\"ops-card\">
                <h4>Dashboard Agentes IA</h4>
                <p class=\"muted\">Solo autorizacion IA: tokens, estado, tiempos y resultado por tarea.</p>
                <div class=\"ops-inline\">
                  <button class=\"primary\" id=\"runAiBatchBtn\">Ejecutar todo</button>
                  <button class=\"ghost\" id=\"refreshAiDashboardBtn\">Actualizar</button>
                </div>
                <div class=\"ai-run-state\" id=\"aiRunState\">Sin ejecucion activa.</div>
                <div class=\"ai-summary\" id=\"aiSummary\"></div>
                <div class=\"ai-table-wrap\">
                  <table class=\"ai-table\">
                    <thead>
                      <tr>
                        <th>Tarea</th>
                        <th>Dispositivo</th>
                        <th>Estado</th>
                        <th>Tokens</th>
                        <th>Inicio</th>
                        <th>Fin</th>
                        <th>Interfaces</th>
                        <th>Resultado</th>
                      </tr>
                    </thead>
                    <tbody id=\"aiDashboardTable\"></tbody>
                  </table>
                </div>
              </div>

              <div class=\"ops-card\">
                <h4>Historial</h4>
                <div class=\"history-meta\" id=\"historyMeta\">Selecciona un puerto para ver detalles.</div>
                <div class=\"history-list\" id=\"historyList\"></div>
              </div>
            </div>
          </div>
        </main>
      </section>
    </div>

    <script>
      const devicesApi = '/devices/db/';
       const portsApi = (id) => `/devices/${id}/ports/`;
       const validateApi = (id) => `/devices/${id}/validate/`;
      const syncApi = (id) => `/devices/${id}/sync/`;
      const migrationAction = 'MIGRAR';
      const escapeHtml = (value) => String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
      const crApi = '/audit/change-requests/';
      const approveApi = (id) => `/audit/change-requests/${id}/approve/`;
      const deployApi = (id) => `/audit/change-requests/${id}/ai-approve-deploy/`;
      const resultsApi = (id) => `/audit/change-requests/${id}/results/`;
      const aiDashboardApi = '/audit/ai-dashboard/?limit=40';
      const aiBatchAsyncApi = '/audit/change-requests/ai-approve-deploy/async/';

      const deviceList = document.getElementById('deviceList');
      const portsTable = document.getElementById('portsTable');
      const selectedDeviceTitle = document.getElementById('selectedDeviceTitle');
      const selectedDeviceMeta = document.getElementById('selectedDeviceMeta');
      const selectAllPorts = document.getElementById('selectAllPorts');
      const refreshOpsBtn = document.getElementById('refreshOpsBtn');
      const syncBtn = document.getElementById('syncBtn');
      const validateBtn = document.getElementById('validateBtn');
      const createCrBtn = document.getElementById('createCrBtn');
      const openDiffBtn = document.getElementById('openDiffBtn');
      const approveBtn = document.getElementById('approveBtn');
      const deployBtn = document.getElementById('deployBtn');
      const resultsBtn = document.getElementById('resultsBtn');
      const diffBtn = document.getElementById('diffBtn');
      const diffTopBtn = document.getElementById('diffTopBtn');
      const crIdInput = document.getElementById('crIdInput');
      const logOutput = document.getElementById('logOutput');
      const opsDebug = document.getElementById('opsDebug');
      const opsSearch = document.getElementById('opsSearch');
      const bulkExcludeBtn = document.getElementById('bulkExcludeBtn');
      const exportBtn = document.getElementById('exportBtn');
      const filterAll = document.getElementById('filterAll');
      const filterMigrate = document.getElementById('filterMigrate');
      const filterExclude = document.getElementById('filterExclude');
      const filterReview = document.getElementById('filterReview');
      const filterMigrated = document.getElementById('filterMigrated');
      const kpiTotal = document.getElementById('kpiTotal');
      const kpiMigrate = document.getElementById('kpiMigrate');
      const kpiExclude = document.getElementById('kpiExclude');
      const kpiReview = document.getElementById('kpiReview');
      const kpiMigrated = document.getElementById('kpiMigrated');
      const historyMeta = document.getElementById('historyMeta');
      const historyList = document.getElementById('historyList');
      const runAiBatchBtn = document.getElementById('runAiBatchBtn');
      const refreshAiDashboardBtn = document.getElementById('refreshAiDashboardBtn');
      const aiRunState = document.getElementById('aiRunState');
      const aiDashboardTable = document.getElementById('aiDashboardTable');
      const aiSummary = document.getElementById('aiSummary');
      const statusBanner = document.getElementById('statusBanner');
      const pageSizeSelect = document.getElementById('pageSizeSelect');
      const prevPageBtn = document.getElementById('prevPageBtn');
      const nextPageBtn = document.getElementById('nextPageBtn');
      const pageIndicator = document.getElementById('pageIndicator');
      const syncProgressWrap = document.getElementById('syncProgressWrap');
      const syncProgressLabel = document.getElementById('syncProgressLabel');
      const syncProgressFill = document.getElementById('syncProgressFill');
      const syncProgressSteps = document.getElementById('syncProgressSteps');
      const syncProgressValue = document.getElementById('syncProgressValue');

      let devices = [];
      let ports = [];
      let visiblePorts = [];
      let selectedDevice = null;
      let selectedPorts = new Set();
      const autoSynced = new Set();
      let activeFilter = 'all';
      let currentPage = 1;
      let pageSize = 100;

      const setStatus = (message, tone = 'info') => {
        statusBanner.textContent = message;
        statusBanner.dataset.tone = tone;
      };

        const setProgress = (percent = 0, stage = '') => {
          const safe = Math.max(0, Math.min(100, Number(percent) || 0));
          syncProgressWrap.style.display = 'block';
          syncProgressFill.style.width = `${safe}%`;
          syncProgressLabel.textContent = `Progreso: ${safe}%${stage ? ` · ${stage}` : ''}`;
          syncProgressValue.textContent = `${safe}%`;

          const stepMap = {
            start: 1,
            connecting: 2,
            running: 3,
            done: 4,
            validating: 3,
            deploying: 3,
            saving: 4,
          };
        const step = stepMap[stage] || (safe >= 100 ? 4 : safe >= 60 ? 3 : safe >= 30 ? 2 : 1);
        if (syncProgressSteps) {
          syncProgressSteps.querySelectorAll('.step').forEach((node) => {
            const idx = Number(node.dataset.step || 0);
            node.classList.toggle('complete', idx < step);
            node.classList.toggle('active', idx === step);
          });
        }
      };

      const setBusy = (button, busy, label) => {
        if (!button) return;
        button.disabled = busy;
        button.dataset.label = button.dataset.label || button.textContent;
        button.textContent = busy ? label : button.dataset.label;
      };

      const formatDuration = (ms) => {
        if (ms === null || ms === undefined) return '-';
        if (ms < 1000) return `${ms}ms`;
        return `${(ms / 1000).toFixed(2)}s`;
      };

      const toneClass = (status) => {
        if (status === 'deployed') return 'analyst';
        if (status === 'approved') return 'known';
        if (status === 'error' || status === 'rejected') return 'new';
        return 'system';
      };

      const renderAiDashboard = (payload) => {
        if (!aiDashboardTable || !aiSummary) return;
        const summary = payload.summary || {};
        aiSummary.innerHTML = `
          <span class="pill system">Tareas: ${summary.total_tasks || 0}</span>
          <span class="pill ai">Tokens: ${summary.total_tokens || 0}</span>
          <span class="pill analyst">Deploy: ${summary.deployed || 0}</span>
          <span class="pill new">Errores: ${summary.errors || 0}</span>
        `;
        const rows = payload.items || [];
        aiDashboardTable.innerHTML = '';
        if (!rows.length) {
          aiDashboardTable.innerHTML = '<tr><td colspan="8" class="empty">Sin tareas de autorizacion IA.</td></tr>';
          return;
        }
        rows.forEach((item) => {
          const tr = document.createElement('tr');
          const started = item.started_at ? new Date(item.started_at).toLocaleString('es-CO') : '-';
          const finished = item.finished_at ? new Date(item.finished_at).toLocaleString('es-CO') : '-';
          const device = item.device || {};
          const tokens = item.tokens || {};
          const interfaces = item.interfaces || {};
          const resultText = item.error || item.final_info || item.reason || '-';
          tr.innerHTML = `
            <td class="mono">${escapeHtml(item.task_id || '-')}</td>
            <td>${escapeHtml(device.hostname || '-')}<div class="sub">${escapeHtml(device.ip || '-')}</div></td>
            <td><span class="pill ${toneClass(item.status)}">${escapeHtml(item.status || '-')}</span><div class="sub">${escapeHtml(item.actor || '-')}</div></td>
            <td>${tokens.total || 0}<div class="sub">p:${tokens.prompt || 0} c:${tokens.completion || 0}</div></td>
            <td>${started}</td>
            <td>${finished}<div class="sub">${formatDuration(item.duration_ms)}</div></td>
            <td>${interfaces.migrated || 0}/${interfaces.requested || 0}<div class="sub">${escapeHtml(interfaces.status || '-')}</div></td>
            <td>${escapeHtml(resultText)}</td>
          `;
          aiDashboardTable.appendChild(tr);
        });
      };

      const loadAiDashboard = async () => {
        if (!aiDashboardTable) return;
        setBusy(refreshAiDashboardBtn, true, 'Actualizando...');
        try {
          const data = await withTimeout(fetchJson(aiDashboardApi));
          renderAiDashboard(data);
        } catch (err) {
          aiDashboardTable.innerHTML = `<tr><td colspan="8" class="empty">Error cargando dashboard IA: ${escapeHtml(err.message)}</td></tr>`;
        } finally {
          setBusy(refreshAiDashboardBtn, false);
        }
      };

      const pollAiBatchJob = async (taskId) => {
        const started = Date.now();
        while (Date.now() - started < 1800000) {
          const job = await fetchJson(`/audit/jobs/${taskId}/`);
          const progress = (job.task && job.task.progress) || {};
          const percent = typeof progress.percent === 'number' ? progress.percent : 0;
          const stage = progress.stage || (job.task && job.task.status) || 'running';
          const device = progress.device ? ` · ${progress.device}` : '';
          const message = progress.message ? ` · ${progress.message}` : '';
          if (aiRunState) {
            aiRunState.textContent = `Tarea ${taskId}: ${percent}% · ${stage}${device}${message}`;
          }
          if (job.task && job.task.ready) {
            if (job.task.successful === false) {
              throw new Error('La ejecucion batch de IA fallo');
            }
            return job.task.result;
          }
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }
        throw new Error('Timeout esperando finalizacion del batch IA');
      };

      const fetchJson = async (url, options = {}) => {
        const response = await fetch(url, options);
        const contentType = response.headers.get('content-type') || '';
        let data = null;
         if (contentType.includes('application/json')) {
           data = await response.json();
         } else {
           const text = await response.text();
           throw new Error(text.slice(0, 120) || `HTTP ${response.status}`);
         }
         if (!response.ok) {
           throw new Error(data.message || `HTTP ${response.status}`);
         }
        return data;
      };

      const pollJob = async (taskId, label = 'Job') => {
        if (!taskId) return;
        const started = Date.now();
        while (Date.now() - started < 120000) {
          const job = await fetchJson(`/audit/jobs/${taskId}/`);
          if (job.task && job.task.progress && typeof job.task.progress.percent === 'number') {
            const pct = job.task.progress.percent;
            const stage = job.task.progress.stage || '';
            setStatus(`${label}: ${pct}% ${stage}`.trim(), 'info');
            if (label === 'Sync') {
              setProgress(pct, stage);
            }
            if (label === 'Validar') {
              setProgress(pct, 'validating');
            }
            if (label === 'Deploy') {
              setProgress(pct, pct >= 90 ? 'saving' : 'deploying');
            }
          }
          if (job.task && job.task.ready) {
            if (job.task.successful === false) {
              throw new Error('Job fallo en background');
            }
            if (job.task.result && (job.task.result.status === 'failed' || job.task.result.rc)) {
              throw new Error(job.task.result.status || 'Sync fallo');
            }
            return job.task.result;
          }
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }
        throw new Error('Timeout esperando job');
      };

      const withTimeout = (promise, ms = 120000) => {
        let timer;
        const timeout = new Promise((_resolve, reject) => {
          timer = setTimeout(() => reject(new Error('Tiempo de espera agotado.')), ms);
        });
        return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
      };

      const renderDevices = () => {
        deviceList.innerHTML = '';
        if (!devices.length) {
          deviceList.innerHTML = '<div class="empty">No hay dispositivos cargados.</div>';
          return;
        }
        const grouped = {};
        devices.forEach((device) => {
          const key = device.site || 'Sin sede';
          grouped[key] = grouped[key] || [];
          grouped[key].push(device);
        });

        Object.keys(grouped).sort().forEach((siteName) => {
          const section = document.createElement('details');
          section.className = 'site-group';
          section.open = false;
          const summary = document.createElement('summary');
          summary.textContent = siteName;
          summary.className = 'site-title';
          section.appendChild(summary);

          grouped[siteName].forEach((device) => {
            const item = document.createElement('button');
            item.className = `device-item ${selectedDevice && selectedDevice.id === device.id ? 'active' : ''}`;
            item.innerHTML = `
              <div class="device-meta">
                <strong>${device.hostname}</strong>
                <span>${device.ip}</span>
              </div>
              <span class="device-site">${device.site || '-'}</span>
            `;
            item.addEventListener('click', () => {
              selectedDevice = device;
              selectedDeviceTitle.textContent = device.hostname;
              selectedDeviceMeta.textContent = `${device.ip} · ${device.site || 'sin sitio'}`;
              selectedPorts.clear();
              loadPorts();
              renderDevices();
            });
            section.appendChild(item);
          });

          deviceList.appendChild(section);
        });
      };

      const shouldSelectPort = (_port) => true;

      const renderKpis = () => {
        const total = ports.length;
        const countMigrate = ports.filter((port) => (port.validation_action || '') === migrationAction).length;
        const countExclude = ports.filter((port) => (port.validation_action || '') === 'EXCLUIR').length;
        const countReview = ports.filter((port) => (port.validation_action || '') === 'REVISAR').length;
        const countMigrated = ports.filter((port) => (port.validation_action || '') === 'YA_MIGRADO').length;
        kpiTotal.textContent = String(total);
        kpiMigrate.textContent = String(countMigrate);
        kpiExclude.textContent = String(countExclude);
        kpiReview.textContent = String(countReview);
        kpiMigrated.textContent = String(countMigrated);
      };

      const applyFilters = () => {
        const query = (opsSearch.value || '').toLowerCase().trim();
        visiblePorts = ports.filter((port) => {
          const action = (port.validation_action || '').toUpperCase();
          if (activeFilter === 'migrate' && action !== 'MIGRAR') return false;
          if (activeFilter === 'exclude' && action !== 'EXCLUIR') return false;
          if (activeFilter === 'review' && action !== 'REVISAR') return false;
          if (activeFilter === 'migrated' && action !== 'YA_MIGRADO') return false;
          if (!query) return true;
          return (
            (port.interface || '').toLowerCase().includes(query) ||
            (port.description || '').toLowerCase().includes(query) ||
            (port.status || '').toLowerCase().includes(query) ||
            (port.validation_reason || '').toLowerCase().includes(query)
          );
        });
        currentPage = 1;
      };

      const getPagedPorts = () => {
        const total = visiblePorts.length || 0;
        const totalPages = Math.max(1, Math.ceil(total / pageSize));
        if (currentPage > totalPages) {
          currentPage = totalPages;
        }
        const start = (currentPage - 1) * pageSize;
        const end = start + pageSize;
        return {
          slice: visiblePorts.slice(start, end),
          totalPages,
        };
      };

      const renderPager = (totalPages) => {
        pageIndicator.textContent = `${currentPage} / ${totalPages}`;
        prevPageBtn.disabled = currentPage <= 1;
        nextPageBtn.disabled = currentPage >= totalPages;
      };

      const renderPorts = () => {
        portsTable.innerHTML = '';
        if (!visiblePorts.length) {
          portsTable.innerHTML = `
            <tr>
              <td colspan="7" class="empty">Sin puertos cargados.</td>
            </tr>
          `;
          renderPager(1);
          selectAllPorts.checked = false;
          return;
        }
        const { slice, totalPages } = getPagedPorts();
        renderPager(totalPages);
        if (slice.length) {
          selectAllPorts.checked = slice.every(
            (port) => !shouldSelectPort(port) || selectedPorts.has(port.interface)
          );
        } else {
          selectAllPorts.checked = false;
        }
        slice.forEach((port) => {
          const row = document.createElement('tr');
          const checked = selectedPorts.has(port.interface);
          const action = port.validation_action || '-';
          const canSelect = true;
          const reason = port.validation_reason || '';
          const ruleTitle = reason
            ? `${port.validation_category || 'Regla'}: ${reason}`
            : '';
          const approvalSource = port.last_change_approved_by
            ? (String(port.last_change_approved_by).toUpperCase() === 'IA' ? 'IA' : 'Analista')
            : '';
          const approvalActor = port.last_change_approved_by && approvalSource === 'Analista'
            ? `: ${port.last_change_approved_by}`
            : '';
          const tooltipAttr = ruleTitle ? `data-tooltip="${escapeHtml(ruleTitle)}"` : '';
          row.innerHTML = `
            <td data-label="Seleccion"><input type="checkbox" data-if="${port.interface}" ${checked ? 'checked' : ''} ${canSelect ? '' : 'disabled'} /></td>
            <td class="mono" data-label="Interface">${port.interface}</td>
            <td data-label="VLAN">${port.vlan ?? '-'}</td>
            <td data-label="Modo">${port.mode || '-'}</td>
            <td data-label="Descripcion">${port.description || '-'}</td>
            <td data-label="Estado">${port.status || '-'}</td>
            <td data-label="Validacion">
              <span class="pill ${action === 'EXCLUIR' ? 'new' : 'known'}">${action}</span>
              <div class="sub">${reason}</div>
              ${ruleTitle ? `<span class="info-btn" ${tooltipAttr}>i</span>` : ''}
              ${port.last_change_request_id ? `<div class="sub">CR #${port.last_change_request_id}${approvalSource ? ` · Aut: ${approvalSource}${approvalActor}` : ''}${port.last_change_approved_at ? ` · ${new Date(port.last_change_approved_at).toLocaleString('es-CO')}` : ''}</div>` : ''}
            </td>
          `;
          row.addEventListener('click', () => {
            renderHistory(port);
          });
          portsTable.appendChild(row);
        });
      };

      const renderHistory = async (port) => {
        historyMeta.textContent = `${port.interface} · ${port.validation_action || '-'}`;
        historyList.innerHTML = '';
        if (!port.last_change_request_id) {
          historyList.innerHTML = '<div class="history-item">Sin cambios registrados.</div>';
          return;
        }
        historyList.innerHTML = '<div class="history-item">Cargando decision...</div>';
        try {
          const data = await withTimeout(fetchJson(resultsApi(port.last_change_request_id)));
          const summary = data.decision_summary || {};
          const source = String(summary.source || '').toLowerCase();
          const sourceLabel = source === 'ai' ? 'IA' : source === 'analyst' ? 'Analista' : 'Sistema';
          const sourceClass = source === 'ai' ? 'ai' : source === 'analyst' ? 'analyst' : 'system';
          const actor = summary.actor || port.last_change_approved_by || 'N/A';
          const reason = summary.reason || 'Sin motivo registrado.';
          const when = summary.approved_at
            ? new Date(summary.approved_at).toLocaleString('es-CO')
            : (port.last_change_approved_at ? new Date(port.last_change_approved_at).toLocaleString('es-CO') : 'N/A');
          historyList.innerHTML = `
            <div class="history-item">CR #${port.last_change_request_id}</div>
            <div class="history-item"><span class="pill ${sourceClass}">${sourceLabel}</span> · ${actor}</div>
            <div class="history-item">Motivo: ${escapeHtml(reason)}</div>
            <div class="history-item">Fecha: ${when}</div>
          `;
        } catch (err) {
          historyList.innerHTML = `
            <div class="history-item">CR #${port.last_change_request_id}</div>
            <div class="history-item">Aprobado por: ${port.last_change_approved_by || 'N/A'}</div>
            <div class="history-item">Fecha: ${port.last_change_approved_at ? new Date(port.last_change_approved_at).toLocaleString('es-CO') : 'N/A'}</div>
          `;
        }
      };

      const loadDevices = async () => {
        try {
          setStatus('Cargando dispositivos...', 'info');
          const data = await fetchJson(devicesApi);
          devices = data.devices || [];
          renderDevices();
          setStatus('Dispositivos actualizados.', 'success');
        } catch (err) {
          setStatus(`Error cargando dispositivos: ${err.message}`, 'error');
        }
      };

      const loadPorts = async () => {
        if (!selectedDevice) return;
        try {
          setStatus('Cargando puertos...', 'info');
          opsDebug.textContent = `GET ${portsApi(selectedDevice.id)}`;
          const data = await fetchJson(portsApi(selectedDevice.id));
          ports = data.ports || [];
          if (!ports.length && !autoSynced.has(selectedDevice.id)) {
            autoSynced.add(selectedDevice.id);
            setStatus('Sincronizando dispositivo...', 'info');
            setProgress(10, 'inicio');
            opsDebug.textContent = `POST ${syncApi(selectedDevice.id)}`;
            const syncResp = await withTimeout(fetchJson(syncApi(selectedDevice.id), { method: 'POST' }));
            await pollJob(syncResp.task_id, 'Sync');
            opsDebug.textContent = `GET ${portsApi(selectedDevice.id)}`;
            const refreshed = await fetchJson(portsApi(selectedDevice.id));
            ports = refreshed.ports || [];
          }
          if (ports.length) {
            opsDebug.textContent = `GET ${validateApi(selectedDevice.id)}`;
            await withTimeout(fetchJson(validateApi(selectedDevice.id)));
            opsDebug.textContent = `GET ${portsApi(selectedDevice.id)}`;
            const validated = await fetchJson(portsApi(selectedDevice.id));
            ports = validated.ports || [];
          }
          selectedPorts = new Set();
          renderKpis();
          applyFilters();
          renderPorts();
          selectAllPorts.checked = false;
          setProgress(100, 'listo');
          setStatus('Puertos actualizados.', 'success');
        } catch (err) {
           ports = [];
           renderPorts();
           setProgress(0, 'error');
           setStatus(`No se pudo cargar/sincronizar: ${err.message}`, 'error');
           opsDebug.textContent = `Error: ${err.message}`;
         }
       };

      pageSizeSelect.addEventListener('change', () => {
        pageSize = Number(pageSizeSelect.value || 50);
        currentPage = 1;
        renderPorts();
      });

      prevPageBtn.addEventListener('click', () => {
        if (currentPage > 1) {
          currentPage -= 1;
          renderPorts();
        }
      });

      nextPageBtn.addEventListener('click', () => {
        const total = visiblePorts.length || 0;
        const totalPages = Math.max(1, Math.ceil(total / pageSize));
        if (currentPage < totalPages) {
          currentPage += 1;
          renderPorts();
        }
      });

      portsTable.addEventListener('change', (event) => {
        if (event.target.type !== 'checkbox') return;
        const iface = event.target.getAttribute('data-if');
        if (event.target.checked) {
          selectedPorts.add(iface);
        } else {
          selectedPorts.delete(iface);
        }
      });

      selectAllPorts.addEventListener('change', (event) => {
        event.stopPropagation();
        const { slice } = getPagedPorts();
        if (event.target.checked) {
          slice.forEach((port) => {
            selectedPorts.add(port.interface);
          });
        } else {
          slice.forEach((port) => {
            selectedPorts.delete(port.interface);
          });
        }
        renderPorts();
      });

      refreshOpsBtn.addEventListener('click', loadDevices);
      opsSearch.addEventListener('input', () => {
        applyFilters();
        renderPorts();
      });
      filterAll.addEventListener('click', () => {
        activeFilter = 'all';
        applyFilters();
        renderPorts();
      });
      filterMigrate.addEventListener('click', () => {
        activeFilter = 'migrate';
        applyFilters();
        renderPorts();
      });
      filterExclude.addEventListener('click', () => {
        activeFilter = 'exclude';
        applyFilters();
        renderPorts();
      });
      filterReview.addEventListener('click', () => {
        activeFilter = 'review';
        applyFilters();
        renderPorts();
      });
      filterMigrated.addEventListener('click', () => {
        activeFilter = 'migrated';
        applyFilters();
        renderPorts();
      });
      bulkExcludeBtn.addEventListener('click', () => {
        selectedPorts.clear();
        renderPorts();
      });
      exportBtn.addEventListener('click', () => {
        const data = visiblePorts.map((port) => ({
          interface: port.interface,
          vlan: port.vlan,
          mode: port.mode,
          description: port.description,
          status: port.status,
          action: port.validation_action,
          reason: port.validation_reason,
        }));
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `puertos_${selectedDevice ? selectedDevice.hostname : 'device'}.json`;
        link.click();
        URL.revokeObjectURL(url);
      });
       syncBtn.addEventListener('click', async () => {
        if (!selectedDevice) {
          setStatus('Selecciona un dispositivo para sincronizar.', 'error');
          return;
        }
        setStatus('Sincronizando dispositivo...', 'info');
        setBusy(syncBtn, true, 'Sincronizando...');
        try {
            opsDebug.textContent = `POST ${syncApi(selectedDevice.id)}`;
            const syncResp = await withTimeout(fetchJson(syncApi(selectedDevice.id), { method: 'POST' }));
            await pollJob(syncResp.task_id, 'Sync');
            await loadPorts();
            logOutput.textContent = 'Sync finalizado.';
            setStatus('Sync finalizado.', 'success');
        } catch (err) {
           logOutput.textContent = `Error en sync: ${err.message}`;
           setStatus(`Error en sync: ${err.message}`, 'error');
           opsDebug.textContent = `Error: ${err.message}`;
         } finally {
           setBusy(syncBtn, false);
         }
       });
      validateBtn.addEventListener('click', async () => {
        if (!selectedDevice) {
          setStatus('Selecciona un dispositivo para validar.', 'error');
          return;
        }
        setStatus('Validando puertos...', 'info');
        setBusy(validateBtn, true, 'Validando...');
        try {
          const validateResp = await withTimeout(fetchJson(validateApi(selectedDevice.id)));
          await pollJob(validateResp.task_id, 'Validacion');
          await loadPorts();
          logOutput.textContent = 'Validacion finalizada.';
          setStatus('Validacion finalizada.', 'success');
        } catch (err) {
          logOutput.textContent = `Error en validacion: ${err.message}`;
          setStatus(`Error en validacion: ${err.message}`, 'error');
        } finally {
          setBusy(validateBtn, false);
        }
      });
      createCrBtn.addEventListener('click', async () => {
        if (!selectedDevice) {
          setStatus('Selecciona un dispositivo para crear el CR.', 'error');
          return;
        }
        if (!ports.length) {
          setStatus('No hay puertos disponibles para generar CR.', 'error');
          return;
        }
        if (!selectedPorts.size) {
          setStatus('Selecciona alguna interface.', 'error');
          return;
        }

        const portsPayload = ports
          .filter((port) => selectedPorts.has(port.interface))
          .map((port) => ({
            interface: port.interface,
            description: port.description || '',
            vlan: port.vlan ?? 10,
            mode: 'access',
            template_name: 'STANDARD_8021X',
          }));

        if (!portsPayload.length) {
          setStatus('Selecciona alguna interface.', 'error');
          return;
        }
        setBusy(createCrBtn, true, 'Creando...');
        try {
          const data = await withTimeout(fetchJson(crApi, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                device_id: selectedDevice.id,
                ports: portsPayload,
              }),
            }));
          crIdInput.value = data.id;
            logOutput.textContent = `CR creado: ${data.id}`;
            setStatus(`CR creado: ${data.id}`, 'success');
            crIdInput.value = data.id;
          } catch (err) {
            logOutput.textContent = `Error creando CR: ${err.message}`;
            setStatus(`Error creando CR: ${err.message}`, 'error');
          } finally {
            setBusy(createCrBtn, false);
          }
        });
      approveBtn.addEventListener('click', async () => {
        if (!crIdInput.value) {
          setStatus('Ingresa un ID de Change Request.', 'error');
          return;
        }
        setStatus('Aprobando CR...', 'info');
        setBusy(approveBtn, true, 'Aprobando...');
        try {
          await withTimeout(fetchJson(approveApi(crIdInput.value), { method: 'POST' }));
          logOutput.textContent = `CR ${crIdInput.value} aprobado.`;
          setStatus(`CR ${crIdInput.value} aprobado.`, 'success');
        } catch (err) {
          logOutput.textContent = `Error aprobando: ${err.message}`;
          setStatus(`Error aprobando: ${err.message}`, 'error');
        } finally {
          setBusy(approveBtn, false);
        }
      });
      deployBtn.addEventListener('click', async () => {
        if (!crIdInput.value) {
          setStatus('Ingresa un ID de Change Request.', 'error');
          return;
        }
        setStatus('Desplegando cambios...', 'info');
        setBusy(deployBtn, true, 'Desplegando...');
        try {
          const data = await withTimeout(fetchJson(deployApi(crIdInput.value), { method: 'POST' }));
          logOutput.textContent = JSON.stringify(data, null, 2);
          if (selectedDevice) {
            await withTimeout(fetchJson(validateApi(selectedDevice.id)));
            await loadPorts();
          }
          await loadAiDashboard();
          setStatus('Despliegue finalizado y estado actualizado.', 'success');
          } catch (err) {
            const message = (err && err.message) ? err.message : 'Error desconocido.';
            if (message.toLowerCase().includes('auth') || message.toLowerCase().includes('authentication')) {
              setStatus('Error de autenticacion SSH. Verifica usuario y password.', 'error');
            } else {
              setStatus(`Error desplegando: ${message}`, 'error');
            }
            logOutput.textContent = `Error desplegando: ${message}`;
          } finally {
            setBusy(deployBtn, false);
          }
        });
      resultsBtn.addEventListener('click', async () => {
        if (!crIdInput.value) {
          setStatus('Ingresa un ID de Change Request.', 'error');
          return;
        }
        setStatus('Cargando logs...', 'info');
        setBusy(resultsBtn, true, 'Cargando...');
        try {
          const data = await withTimeout(fetchJson(resultsApi(crIdInput.value)));
          const summary = data.decision_summary || null;
          const header = summary
            ? `Decision: ${summary.source || 'unknown'} | Actor: ${summary.actor || '-'} | Motivo: ${summary.reason || '-'}`
            : 'Sin decision registrada.';
          logOutput.textContent = `${header}\n\n${JSON.stringify(data, null, 2)}`;
          setStatus('Logs actualizados.', 'success');
        } catch (err) {
          logOutput.textContent = `Error cargando logs: ${err.message}`;
          setStatus(`Error cargando logs: ${err.message}`, 'error');
        } finally {
          setBusy(resultsBtn, false);
        }
      });

      runAiBatchBtn.addEventListener('click', async () => {
        setStatus('Iniciando ejecucion batch IA...', 'info');
        setBusy(runAiBatchBtn, true, 'Ejecutando...');
        try {
          const start = await withTimeout(fetchJson(aiBatchAsyncApi, { method: 'POST' }));
          const taskId = start.task_id;
          if (aiRunState) {
            aiRunState.textContent = `Tarea ${taskId} iniciada.`;
          }
          const result = await pollAiBatchJob(taskId);
          logOutput.textContent = JSON.stringify(result, null, 2);
          await loadAiDashboard();
          setStatus('Batch IA finalizado.', 'success');
          if (aiRunState) {
            aiRunState.textContent = `Tarea ${taskId} finalizada.`;
          }
        } catch (err) {
          const msg = err && err.message ? err.message : 'Error ejecutando batch IA';
          if (aiRunState) {
            aiRunState.textContent = msg;
          }
          setStatus(msg, 'error');
        } finally {
          setBusy(runAiBatchBtn, false);
        }
      });

      refreshAiDashboardBtn.addEventListener('click', loadAiDashboard);

      diffBtn.addEventListener('click', () => {
        if (!crIdInput.value) {
          setStatus('Ingresa un ID de Change Request.', 'error');
          return;
        }
        window.open(`/audit/diff/${crIdInput.value}/`, '_blank');
      });

      openDiffBtn.addEventListener('click', () => {
        if (!crIdInput.value) {
          setStatus('Ingresa un ID de Change Request.', 'error');
          return;
        }
        window.open(`/audit/diff/${crIdInput.value}/`, '_blank');
      });

      diffTopBtn.addEventListener('click', () => {
        if (!crIdInput.value) {
          setStatus('Ingresa un ID de Change Request.', 'error');
          return;
        }
        window.open(`/audit/diff/${crIdInput.value}/`, '_blank');
      });

      loadDevices();
      loadAiDashboard();

      setInterval(() => {
        loadDevices();
        loadAiDashboard();
        if (selectedDevice) {
          loadPorts();
        }
      }, 300000);
    </script>
  </body>
</html>"""
        return HttpResponse(html)


def _ensure_postgres_seeded() -> None:
    if Device.objects.exists():
        return
    switch_ips = os.environ.get("SWITCH_IPS", "").strip()
    if not switch_ips:
        return
    switch_sites = os.environ.get("SWITCH_SITES", "")
    sites = [site.strip() for site in switch_sites.split(",") if site.strip()]
    ip_items = [item.strip() for item in switch_ips.split(",") if item.strip()]
    for idx, raw in enumerate(ip_items):
        if "@" in raw:
            host, ip = raw.split("@", 1)
            hostname = host.strip()
            ip = ip.strip()
        else:
            ip = raw
            hostname = f"switch-{ip.split('.')[-1]}"
        site_name = sites[idx] if idx < len(sites) else (sites[-1] if sites else "LAB")
        site, _ = Site.objects.get_or_create(name=site_name, type=Site.SITE_STANDARD)
        Device.objects.create(
            hostname=hostname,
            ip=ip,
            device_type="ios",
            site=site,
        )
