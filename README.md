# NetAuto (Django + Ansible)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment variables

```bash
export POSTGRES_DB=netauto
export POSTGRES_USER=netauto
export POSTGRES_PASSWORD=netauto
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
```

## Run

```bash
python manage.py migrate
python manage.py runserver
```

## Run with Docker

```bash
docker compose up --build
```

## Deploy on another machine (GitHub)

1) Clone and prepare env:

```bash
git clone <YOUR_REPO_URL>
cd netauto
cp .env.example .env
```

2) Edit `.env` with real values (`SWITCH_USER`, `SWITCH_PASS`, `SWITCH_IPS`, `SWITCH_SITES`).

3) Start stack:

```bash
docker compose up -d --build
```

4) Open UI:

```bash
http://<SERVER-IP>:8000/devices/ui/ops/
```

5) AI authorization dashboard endpoint:

```bash
http://<SERVER-IP>:8000/audit/ai-dashboard/
```

## Full reset after changing .env

```bash
./reset_all.sh
```

## Kubernetes (offline / sin registry)

1) Carga de imagenes en el nodo:

```bash
docker load -i netauto-images.tar
```

2) Aplicar manifiestos:

```bash
kubectl apply -f k8s/netauto.yaml
```

3) Acceso (NodePort):

```bash
http://<NODE-IP>:30080/devices/ui/ops/
```

## UI

```bash
Inventario removido.
```

## Operacion 802.1X

```bash
http://localhost:8000/devices/ui/ops/
```

## Autosync

El worker sincroniza cada 5 minutos.

## Trigger a sync (Docker)

```bash
curl -X POST http://localhost:8000/devices/1/sync/
```

## List ports (Docker)

```bash
curl http://localhost:8000/devices/1/ports/
```

## Validate ports (Docker)

```bash
curl http://localhost:8000/devices/1/validate/
```

Validation results are stored on each port record.

## Change Requests

Create a request:

```bash
curl -X POST http://localhost:8000/audit/change-requests/ \
  -H "Content-Type: application/json" \
  -d '{"device_id":1,"ports":[{"interface":"Gi1/0/10","description":"User","vlan":10}],"template_name":"STANDARD_8021X"}'
```

Approve a request:

```bash
curl -X POST http://localhost:8000/audit/change-requests/1/approve/
```

Deploy a request:

```bash
curl -X POST http://localhost:8000/audit/change-requests/1/deploy/
```

Deployment results and change logs are stored in PostgreSQL.

## Casos de uso (actualizados)

1) Migracion automatica de puertos elegibles (`MIGRAR`):

- La IA autoriza y dispara deploy.
- El dashboard reporta `deployed` cuando termina bien.

2) Bloqueo seguro de puertos no elegibles (`EXCLUIR` / `REVISAR`):

- No se despliega en red productiva.
- El dashboard reporta `no_migrar` (no se cuenta como error tecnico).

3) Monitoreo de jobs desde otros clientes web:

- `GET /audit/jobs/`
- `GET /audit/jobs/<task_id>/`
- Ambos endpoints exponen cabeceras CORS para consumo cross-origin.

4) Batch rapido por interfaz:

- `NETAUTO_BATCH_INTERFACE=Gi1/1/1` para ejecutar sobre una interfaz objetivo.
- Si se deja vacio, procesa candidatos `MIGRAR`.

Fetch deployment results and change logs:

```bash
curl http://localhost:8000/audit/change-requests/1/results/
```

## Auth & Roles

```bash
docker compose exec web python manage.py seed_roles
```

Use Django admin to create users and assign groups: Engineer, Approver, Admin.

All API endpoints return JSON 401/403 responses for unauthorized/forbidden access.

API tokens are manageable in Django Admin.

## API Tokens

Create a token:

```bash
docker compose exec web python manage.py create_token admin "local"
```

Use it:

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/devices/1/ports/
```

List tokens (admin only):

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/audit/tokens/
```

Rotate token:

```bash
curl -X POST http://localhost:8000/audit/tokens/rotate/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"token":"<token>"}'
```

Revoke token:

```bash
curl -X POST http://localhost:8000/audit/tokens/revoke/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"token":"<token>"}'
```

## Mock lab + Ansible

```bash
python lab/start_lab.py
python -m ansible_runner run ansible -p playbooks/gather_port_config.yml -i ansible/inventory/mock.ini
```

## SSH legacy compatibility

Si necesitas conectarte a equipos legacy:

```bash
ssh -o KexAlgorithms=+diffie-hellman-group1-sha1 \
  -o HostKeyAlgorithms=+ssh-rsa \
  -o Ciphers=+aes128-cbc \
  admin@192.168.122.10
```

## Ansible inventory (real switch)

```bash
ansible-playbook -i ansible/inventory/mock.ini ansible/playbooks/gather_port_config.yml -l legacy-switch
```

## Sync and import CLI output

Trigger a sync for a device (device id from Django DB):

```bash
curl -X POST http://127.0.0.1:8000/devices/1/sync/
```
