import json
import os
import re
import socket
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

from celery.result import AsyncResult

from django.contrib.auth.decorators import login_required, permission_required
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.csrf import csrf_exempt
import difflib
import html

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from audit.models import (
    ChangeApproval,
    ChangeLog,
    ChangeRequest,
    ConfigSnapshot,
    DeploymentResult,
)
from accounts.models import ApiToken
from devices.models import Device, Port
from devices.services import sync_device
from netauto.celery import app as celery_app
from netauto.automation import run_playbook
from validator.config_generator import generate_config


class AuditHomeView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return JsonResponse({"status": "ok", "message": "audit placeholder"})


@method_decorator(csrf_exempt, name="dispatch")
class ChangeRequestListView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        items = ChangeRequest.objects.order_by("-created_at")[:200]
        payload = []
        for item in items:
            payload.append(
                {
                    "id": item.id,
                    "device_id": item.device_id,
                    "status": item.status,
                    "requested_by": item.requested_by_id,
                    "site": item.site,
                    "created_at": item.created_at,
                }
            )
        return JsonResponse({"status": "ok", "change_requests": payload})

    @method_decorator(csrf_exempt)
    def post(self, request: HttpRequest) -> HttpResponse:
        payload = request.body.decode("utf-8", errors="ignore")
        if not payload:
            return JsonResponse({"status": "error", "message": "empty body"}, status=400)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "invalid json"}, status=400)

        device_id = data.get("device_id")
        ports = data.get("ports")
        template_name = data.get("template_name", "STANDARD_8021X")
        if not device_id or not ports:
            return JsonResponse(
                {"status": "error", "message": "device_id and ports required"},
                status=400,
            )

        device = Device.objects.get(pk=device_id)
        config_lines = []
        for port in ports:
            interface = port.get("interface")
            description = port.get("description", "")
            vlan = port.get("vlan", 10)
            port_template = port.get("template_name") or template_name
            config_lines.append(
                generate_config(
                    port_template,
                    {
                        "interface": _expand_interface(interface),
                        "description": description,
                        "vlan": vlan,
                    },
                )
            )

        change_request = ChangeRequest.objects.create(
            device=device,
            requested_by=request.user if request.user.is_authenticated else None,
            status=ChangeRequest.STATUS_PENDING,
            ports_json=ports,
            generated_config="\n".join(config_lines),
            site=device.site.name if device.site else "",
        )
        return JsonResponse({"status": "ok", "id": change_request.id})


@method_decorator(csrf_exempt, name="dispatch")
class ChangeRequestApproveView(View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        change_request = ChangeRequest.objects.get(pk=pk)
        if change_request.status != ChangeRequest.STATUS_PENDING:
            return JsonResponse({"status": "error", "message": "invalid status"}, status=400)
        comments = "Approved"
        payload = request.body.decode("utf-8", errors="ignore").strip()
        if payload:
            try:
                data = json.loads(payload)
                comments = (data.get("comments") or data.get("reason") or comments).strip()
            except json.JSONDecodeError:
                comments = comments
        change_request.status = ChangeRequest.STATUS_APPROVED
        change_request.save(update_fields=["status"])
        ChangeApproval.objects.create(
            change_request=change_request,
            approved_by=request.user if request.user.is_authenticated else None,
            comments=comments,
        )
        return JsonResponse({"status": "ok", "id": change_request.id})


def _approval_source_and_reason(approval: ChangeApproval) -> tuple[str, str, str]:
    comments = (approval.comments or "").strip()
    if approval.approved_by_id:
        actor = approval.approved_by.username
        source = "analyst"
        reason = comments or "Aprobacion manual sin detalle."
        return source, actor, reason

    if comments.upper().startswith("IA ") or comments.upper().startswith("IA"):
        actor = "IA"
        source = "ai"
        reason = comments.split(":", 1)[-1].strip() if ":" in comments else comments
        return source, actor, (reason or "Decision automatica por IA.")

    return "system", "Sistema", (comments or "Decision automatica del sistema.")


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _env_enabled(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _ollama_decide(change_request: ChangeRequest, ports: list[dict]) -> tuple[bool, str, dict]:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "qwen3.5:9b")
    timeout = float(os.environ.get("OLLAMA_TIMEOUT", "20"))
    num_predict = int(os.environ.get("OLLAMA_NUM_PREDICT", "80"))
    config_max_lines = int(os.environ.get("OLLAMA_CONFIG_MAX_LINES", "80"))
    think_enabled = os.environ.get("OLLAMA_THINK", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    meta: dict[str, object] = {
        "provider": "ollama",
        "model": model,
        "base_url": base_url,
        "thinking_enabled": think_enabled,
    }
    if num_predict <= 0:
        meta["num_predict"] = "unlimited"
    else:
        meta["num_predict"] = num_predict

    port_payload = []
    for port in ports:
        port_payload.append(
            {
                "interface": port.get("interface"),
                "action": port.get("action"),
                "vlan": port.get("vlan"),
                "mode": port.get("mode"),
            }
        )

    config_lines = change_request.generated_config.splitlines()
    if config_max_lines > 0 and len(config_lines) > config_max_lines:
        config_for_prompt = "\n".join(config_lines[:config_max_lines])
        config_for_prompt += (
            f"\n... (truncado, {len(config_lines) - config_max_lines} lineas omitidas)"
        )
        meta["config_truncated"] = True
        meta["config_total_lines"] = len(config_lines)
        meta["config_used_lines"] = config_max_lines
    else:
        config_for_prompt = change_request.generated_config
        meta["config_truncated"] = False
        meta["config_total_lines"] = len(config_lines)

    prompt = (
        "Eres un analista senior de redes. Responde SOLO JSON estrictamente con "
        '{"approve": true|false, "reason": "..."}.\n'
        "Aprueba solo si TODOS los cambios son elegibles segun las reglas 802.1X y "
        "si no hay puertos con accion EXCLUIR o REVISAR. Si hay cualquier duda, rechaza.\n\n"
        f"CR #{change_request.id}\n"
        f"Dispositivo: {change_request.device.hostname} ({change_request.device.ip})\n"
        f"Sitio: {change_request.site}\n"
        f"Puertos: {json.dumps(port_payload, ensure_ascii=True)}\n"
        "Config generada:\n"
        f"{config_for_prompt}\n"
    )

    payload_dict: dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": think_enabled,
    }
    options: dict[str, object] = {}
    if num_predict > 0:
        options["num_predict"] = num_predict
    if options:
        payload_dict["options"] = options
    payload = json.dumps(payload_dict).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as exc:
        return False, f"No se pudo contactar a Ollama: {exc}", meta
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    parsed = None
    thinking = ""
    try:
        parsed = json.loads(raw)
        reply = parsed.get("response", "")
        thinking = parsed.get("thinking", "")
    except json.JSONDecodeError:
        reply = raw

    max_chars = int(os.environ.get("OLLAMA_LOG_MAX_CHARS", "8000"))
    prompt_max_chars = int(os.environ.get("OLLAMA_PROMPT_LOG_MAX_CHARS", "4000"))
    thinking_max_chars = int(os.environ.get("OLLAMA_THINKING_LOG_MAX_CHARS", "12000"))
    meta["latency_ms"] = elapsed_ms
    meta["response_truncated"] = len(reply) > max_chars
    meta["raw_response"] = reply[:max_chars]
    meta["thinking_truncated"] = len(thinking) > thinking_max_chars
    meta["thinking"] = thinking[:thinking_max_chars]
    meta["prompt_truncated"] = len(prompt) > prompt_max_chars
    meta["prompt"] = prompt[:prompt_max_chars]
    if parsed:
        meta["ollama_stats"] = {
            "done": parsed.get("done"),
            "total_duration": parsed.get("total_duration"),
            "load_duration": parsed.get("load_duration"),
            "prompt_eval_count": parsed.get("prompt_eval_count"),
            "eval_count": parsed.get("eval_count"),
            "eval_duration": parsed.get("eval_duration"),
        }

    verdict_source = reply or thinking
    verdict = _extract_json_object(verdict_source) or {}
    approve = bool(verdict.get("approve"))
    if verdict.get("reason"):
        reason = str(verdict.get("reason"))
    else:
        maybe_ollama_stats = meta.get("ollama_stats")
        ollama_stats = maybe_ollama_stats if isinstance(maybe_ollama_stats, dict) else {}
        eval_count = int(ollama_stats.get("eval_count") or 0)
        if num_predict > 0 and not reply and thinking and eval_count >= num_predict:
            reason = (
                "La IA no entrego JSON final: se alcanzo el limite de salida "
                f"({num_predict} tokens)."
            )
        elif not reply and thinking:
            reason = "La IA solo devolvio thinking y no respuesta final en JSON."
        else:
            reason = "Sin razon detallada."
    return approve, reason, meta


def _create_change_request_for_device(device: Device, ports_payload: list[dict]) -> ChangeRequest:
    config_lines = []
    for port in ports_payload:
        interface = port.get("interface")
        description = port.get("description", "")
        vlan = port.get("vlan", 10)
        port_template = port.get("template_name") or "STANDARD_8021X"
        config_lines.append(
            generate_config(
                port_template,
                {
                    "interface": _expand_interface(interface),
                    "description": description,
                    "vlan": vlan,
                },
            )
        )
    return ChangeRequest.objects.create(
        device=device,
        requested_by=None,
        status=ChangeRequest.STATUS_PENDING,
        ports_json=ports_payload,
        generated_config="\n".join(config_lines),
        site=device.site.name if device.site else "",
    )


def _build_ports_payload(change_request: ChangeRequest) -> list[dict]:
    ports_payload = []
    interfaces = [item.get("interface") for item in change_request.ports_json if item]
    db_ports = {
        port.interface: port
        for port in Port.objects.filter(device=change_request.device, interface__in=interfaces)
        .order_by("interface")
        .all()
    }
    for item in change_request.ports_json:
        interface = item.get("interface")
        db_port = db_ports.get(interface)
        ports_payload.append(
            {
                "interface": interface,
                "action": (db_port.validation_action if db_port else "REVISAR"),
                "reason": (db_port.validation_reason if db_port else "Sin validacion"),
                "vlan": item.get("vlan") or (db_port.vlan if db_port else None),
                "mode": item.get("mode") or (db_port.mode if db_port else None),
                "description": item.get("description") or (db_port.description if db_port else ""),
            }
        )
    return ports_payload


def _deploy_change_request(change_request: ChangeRequest, request_user=None) -> tuple[dict, int]:
    if change_request.status != ChangeRequest.STATUS_APPROVED:
        return {
            "status": "error",
            "message": (f"invalid status: expected APPROVED, got {change_request.status}"),
        }, 400
    device = change_request.device
    inventory_path = os.environ.get(
        "NETAUTO_INVENTORY",
        str(Path(__file__).resolve().parent.parent / "ansible" / "inventory" / "generated.ini"),
    )
    ssh_port = _lookup_inventory_port(inventory_path, device.hostname or device.ip)
    if not _tcp_check(device.ip, ssh_port):
        return {
            "status": "error",
            "message": f"Dispositivo sin conectividad (SSH {ssh_port} no responde).",
        }, 503
    enable_snapshots = _env_enabled("NETAUTO_ENABLE_SNAPSHOTS", True)
    snapshot_result = {"rc": 0}
    snapshot_path = f"/tmp/{device.hostname}-running.txt"
    running_config = ""
    if enable_snapshots:
        snapshot_result = run_playbook(
            playbook="snapshot_running_config.yml",
            extra_vars={},
            device_ip=device.ip,
            limit=device.hostname or device.ip,
        )
        if snapshot_result.get("rc") == 0:
            try:
                with open(snapshot_path, "r", encoding="utf-8", errors="ignore") as handle:
                    running_config = handle.read()
            except FileNotFoundError:
                running_config = ""
        if running_config:
            ConfigSnapshot.objects.create(
                change_request=change_request,
                device=device,
                running_config=running_config,
            )
    enable_password = os.environ.get("SWITCH_ENABLE", "").strip()
    extra_vars = {"config_lines": change_request.generated_config.splitlines()}
    if enable_password:
        extra_vars["enable_password"] = enable_password
    result = run_playbook(
        playbook="deploy_config.yml",
        extra_vars=extra_vars,
        device_ip=device.ip,
        limit=device.hostname or device.ip,
    )
    success = result.get("rc") == 0
    if success and enable_snapshots:
        after_result = run_playbook(
            playbook="snapshot_running_config.yml",
            extra_vars={},
            device_ip=device.ip,
            limit=device.hostname or device.ip,
        )
        after_config = ""
        if after_result.get("rc") == 0:
            try:
                with open(snapshot_path, "r", encoding="utf-8", errors="ignore") as handle:
                    after_config = handle.read()
            except FileNotFoundError:
                after_config = ""
        if after_config:
            ConfigSnapshot.objects.create(
                change_request=change_request,
                device=device,
                running_config=after_config,
            )
    if success:
        change_request.status = ChangeRequest.STATUS_DEPLOYED
    else:
        change_request.status = ChangeRequest.STATUS_FAILED
    change_request.save(update_fields=["status"])
    DeploymentResult.objects.create(
        change_request=change_request,
        success=success,
        ansible_output=json.dumps(result),
    )

    if success:
        approval = (
            ChangeApproval.objects.filter(change_request=change_request)
            .order_by("-approved_at")
            .first()
        )
        approval_actor = ""
        approval_at = None
        if approval:
            _source, actor, _reason = _approval_source_and_reason(approval)
            approval_actor = actor
            approval_at = approval.approved_at
        default_mode = None
        if "switchport mode access" in change_request.generated_config:
            default_mode = "access"
        elif "switchport mode trunk" in change_request.generated_config:
            default_mode = "trunk"
        for port_data in change_request.ports_json:
            interface = port_data.get("interface")
            if not interface:
                continue
            if default_mode and "mode" not in port_data:
                port_data["mode"] = default_mode
            if "vlan" not in port_data and default_mode == "access":
                port_data["vlan"] = 10
            try:
                port = Port.objects.get(device=device, interface=interface)
            except Port.DoesNotExist:
                continue
            updated_fields: list[str] = []
            for field in (
                "description",
                "vlan",
                "mode",
                "speed",
                "duplex",
                "mac_address",
            ):
                if field not in port_data:
                    continue
                old_value = getattr(port, field)
                new_value = port_data.get(field)
                if old_value != new_value:
                    ChangeLog.objects.create(
                        change_request=change_request,
                        port_interface=interface,
                        field=field,
                        old_value="" if old_value is None else str(old_value),
                        new_value="" if new_value is None else str(new_value),
                        deployed_by=request_user,
                    )
                    setattr(port, field, new_value)
                    updated_fields.append(field)
            port.last_change_request_id = change_request.id
            if approval_actor:
                port.last_change_approved_by = approval_actor
            if approval_at:
                port.last_change_approved_at = approval_at
            if "last_change_request_id" not in updated_fields:
                updated_fields.append("last_change_request_id")
            if "last_change_approved_by" not in updated_fields:
                updated_fields.append("last_change_approved_by")
            if "last_change_approved_at" not in updated_fields:
                updated_fields.append("last_change_approved_at")
            if "updated_at" not in updated_fields:
                updated_fields.append("updated_at")
            port.save(update_fields=updated_fields)

        if _env_enabled("NETAUTO_ENABLE_POST_DEPLOY_SYNC", True):
            sync_device(device)

    if not success:
        message = "Error en deploy."
        ansible_output = json.dumps(result)
        if (
            "authentication" in ansible_output.lower()
            or "permission denied" in ansible_output.lower()
        ):
            message = "Error de autenticacion SSH."
        return {"status": "error", "message": message, "result": result, "success": success}, 502
    return {"status": "ok", "result": result, "success": success}, 200


def _ai_approve_and_deploy(change_request: ChangeRequest, request_user=None) -> tuple[dict, int]:
    if change_request.status != ChangeRequest.STATUS_PENDING:
        return {
            "status": "error",
            "message": (f"invalid status: expected PENDING, got {change_request.status}"),
        }, 400

    trace: list[dict[str, object]] = [
        {
            "step": "start",
            "message": "Inicio de flujo IA approve+deploy",
            "ts": timezone.now().isoformat(),
        }
    ]
    ports_payload = _build_ports_payload(change_request)
    trace.append(
        {
            "step": "ports_loaded",
            "message": f"Puertos evaluados: {len(ports_payload)}",
            "ts": timezone.now().isoformat(),
        }
    )
    if any((port.get("action") or "").upper() in {"EXCLUIR", "REVISAR"} for port in ports_payload):
        trace.append(
            {
                "step": "local_policy_reject",
                "message": "Rechazo por acciones EXCLUIR/REVISAR antes de invocar IA.",
                "ts": timezone.now().isoformat(),
            }
        )
        change_request.status = ChangeRequest.STATUS_REJECTED
        change_request.save(update_fields=["status"])
        ChangeApproval.objects.create(
            change_request=change_request,
            approved_by=request_user,
            comments="IA rechazo: puertos con accion EXCLUIR/REVISAR.",
        )
        DeploymentResult.objects.create(
            change_request=change_request,
            success=False,
            ansible_output=json.dumps(
                {
                    "ai_decision": {
                        "approve": False,
                        "reason": "Puertos con accion EXCLUIR/REVISAR.",
                        "trace": trace,
                    },
                    "message": "IA rechazo por reglas locales.",
                }
            ),
        )
        return {
            "status": "error",
            "message": "IA rechazo: hay puertos no elegibles.",
            "ai_trace": trace,
        }, 409

    trace.append(
        {
            "step": "model_inference",
            "message": "Consultando modelo Ollama para aprobacion",
            "ts": timezone.now().isoformat(),
        }
    )
    approve, reason, meta = _ollama_decide(change_request, ports_payload)
    trace.append(
        {
            "step": "model_verdict",
            "message": f"Veredicto IA: {'approve' if approve else 'reject'}",
            "ts": timezone.now().isoformat(),
        }
    )
    if not approve:
        change_request.status = ChangeRequest.STATUS_REJECTED
        change_request.save(update_fields=["status"])
        ChangeApproval.objects.create(
            change_request=change_request,
            approved_by=request_user,
            comments=f"IA rechazo: {reason}",
        )
        DeploymentResult.objects.create(
            change_request=change_request,
            success=False,
            ansible_output=json.dumps(
                {
                    "ai_decision": {
                        "approve": False,
                        "reason": reason,
                        "meta": meta,
                        "trace": trace,
                    },
                    "message": "IA rechazo en evaluacion.",
                }
            ),
        )
        return {
            "status": "error",
            "message": f"IA rechazo: {reason}",
            "ai_trace": trace,
            "ai_meta": meta,
        }, 409

    change_request.status = ChangeRequest.STATUS_APPROVED
    change_request.save(update_fields=["status"])
    ChangeApproval.objects.create(
        change_request=change_request,
        approved_by=request_user,
        comments=f"IA aprobo: {reason}",
    )

    trace.append(
        {
            "step": "deploy_started",
            "message": "IA aprobo, iniciando despliegue",
            "ts": timezone.now().isoformat(),
        }
    )
    payload, status = _deploy_change_request(change_request, request_user=request_user)
    trace.append(
        {
            "step": "deploy_finished",
            "message": f"Deploy finalizado con status HTTP {status}",
            "ts": timezone.now().isoformat(),
        }
    )
    latest = (
        DeploymentResult.objects.filter(change_request=change_request)
        .order_by("-deployed_at")
        .first()
    )
    if latest:
        try:
            result_payload = json.loads(latest.ansible_output) if latest.ansible_output else {}
        except json.JSONDecodeError:
            result_payload = {"raw": latest.ansible_output}
        result_payload["ai_decision"] = {
            "approve": True,
            "reason": reason,
            "meta": meta,
            "trace": trace,
        }
        latest.ansible_output = json.dumps(result_payload)
        latest.save(update_fields=["ansible_output"])

    payload["ai_trace"] = trace
    payload["ai_meta"] = meta
    payload["ai_reason"] = reason
    return payload, status


@method_decorator(csrf_exempt, name="dispatch")
class ChangeRequestDeployView(View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        change_request = ChangeRequest.objects.get(pk=pk)
        user = request.user if request.user.is_authenticated else None
        if change_request.status == ChangeRequest.STATUS_PENDING:
            change_request.status = ChangeRequest.STATUS_APPROVED
            change_request.save(update_fields=["status"])
            ChangeApproval.objects.create(
                change_request=change_request,
                approved_by=user,
                comments="Aprobado automaticamente desde despliegue manual.",
            )
        payload, status = _deploy_change_request(change_request, request_user=user)
        return JsonResponse(payload, status=status)


@method_decorator(csrf_exempt, name="dispatch")
class ChangeRequestAiApproveDeployView(View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        change_request = ChangeRequest.objects.get(pk=pk)
        user = request.user if request.user.is_authenticated else None
        payload, status = _ai_approve_and_deploy(change_request, request_user=user)
        return JsonResponse(payload, status=status)


def _build_agent_event_list(
    payload: dict, started_at: str | None, ended_at: str | None
) -> list[dict]:
    events: list[dict] = []
    ai_trace = payload.get("ai_trace") if isinstance(payload.get("ai_trace"), list) else []
    ai_meta = payload.get("ai_meta") if isinstance(payload.get("ai_meta"), dict) else {}
    llm_step = 1
    for item in ai_trace:
        if not isinstance(item, dict):
            continue
        step = item.get("step")
        ts = item.get("ts")
        message = item.get("message")
        if step == "model_inference":
            events.append(
                {
                    "event_type": "llm_start",
                    "ts": ts,
                    "payload": {
                        "step": llm_step,
                        "model": ai_meta.get("model") or "ollama",
                        "ai_message": None,
                        "human_message": message,
                    },
                }
            )
            llm_step += 1
        elif step == "model_verdict":
            ollama_stats = (
                ai_meta.get("ollama_stats") if isinstance(ai_meta.get("ollama_stats"), dict) else {}
            )
            events.append(
                {
                    "event_type": "llm_end",
                    "ts": ts,
                    "payload": {
                        "input_tokens": int(ollama_stats.get("prompt_eval_count") or 0),
                        "output_tokens": int(ollama_stats.get("eval_count") or 0),
                        "llm_response": ai_meta.get("raw_response") or None,
                        "thinking": ai_meta.get("thinking") or None,
                    },
                }
            )
        elif step == "deploy_started":
            events.append(
                {
                    "event_type": "tool_start",
                    "ts": ts,
                    "payload": {
                        "tool_name": "deploy_config",
                        "tool_call_id": f"deploy-{uuid.uuid4()}",
                        "input": {
                            "change_request_id": payload.get("change_request_id"),
                        },
                    },
                }
            )
        elif step == "deploy_finished":
            events.append(
                {
                    "event_type": "tool_end",
                    "ts": ts,
                    "payload": {
                        "result": payload.get("result"),
                        "duration_seconds": None,
                    },
                }
            )

    if not events and started_at:
        events.append(
            {
                "event_type": "llm_start",
                "ts": started_at,
                "payload": {
                    "step": 1,
                    "model": ai_meta.get("model") if isinstance(ai_meta, dict) else "ollama",
                    "ai_message": None,
                    "human_message": "Autorizacion IA",
                },
            }
        )
        if ended_at:
            events.append(
                {
                    "event_type": "llm_end",
                    "ts": ended_at,
                    "payload": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                    },
                }
            )

    return events


@method_decorator(csrf_exempt, name="dispatch")
class ChangeRequestAiApproveDeployEnvelopeView(View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        change_request = ChangeRequest.objects.get(pk=pk)
        user = request.user if request.user.is_authenticated else None
        user_message = "Autorizacion IA para cambio de red"
        body = request.body.decode("utf-8", errors="ignore").strip()
        if body:
            try:
                data = json.loads(body)
                maybe_message = (data.get("user_message") or "").strip()
                if maybe_message:
                    user_message = maybe_message
            except json.JSONDecodeError:
                pass

        payload, status_code = _ai_approve_and_deploy(change_request, request_user=user)
        ai_meta = payload.get("ai_meta") if isinstance(payload.get("ai_meta"), dict) else {}
        ai_trace = payload.get("ai_trace") if isinstance(payload.get("ai_trace"), list) else []

        started_at = ai_trace[0].get("ts") if ai_trace and isinstance(ai_trace[0], dict) else None
        ended_at = ai_trace[-1].get("ts") if ai_trace and isinstance(ai_trace[-1], dict) else None
        started_dt = _parse_iso_datetime(started_at)
        ended_dt = _parse_iso_datetime(ended_at)
        total_minutes = None
        if started_dt and ended_dt:
            total_minutes = (ended_dt - started_dt).total_seconds() / 60.0

        ollama_stats = (
            ai_meta.get("ollama_stats") if isinstance(ai_meta.get("ollama_stats"), dict) else {}
        )
        total_input_tokens = int(ollama_stats.get("prompt_eval_count") or 0)
        total_output_tokens = int(ollama_stats.get("eval_count") or 0)

        final_reply = payload.get("ai_reason") or payload.get("message") or "Proceso finalizado"
        status_text = "success" if status_code < 400 else "error"
        error_text = None if status_text == "success" else (payload.get("message") or "Error")

        response_payload = {
            "id": str(uuid.uuid4()),
            "started_at": started_at,
            "ended_at": ended_at,
            "total_time": total_minutes,
            "user_message": user_message,
            "final_reply": final_reply,
            "status": status_text,
            "error_text": error_text,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "events": _build_agent_event_list(
                {**payload, "change_request_id": change_request.id}, started_at, ended_at
            ),
        }
        return JsonResponse(response_payload, status=status_code)


@method_decorator(csrf_exempt, name="dispatch")
class ChangeRequestAiApproveDeployBatchView(View):
    def post(self, request: HttpRequest) -> HttpResponse:
        user = request.user if request.user.is_authenticated else None
        interface_filter = None
        raw = request.body.decode("utf-8", errors="ignore").strip()
        if raw:
            try:
                data = json.loads(raw)
                maybe_interface = (data.get("interface") or "").strip()
                interface_filter = maybe_interface or None
            except json.JSONDecodeError:
                interface_filter = None
        payload = _run_ai_batch(request_user=user, interface_filter=interface_filter)
        return JsonResponse(payload)


def _run_ai_batch(
    request_user=None, progress_callback=None, interface_filter: str | None = None
) -> dict:
    today = timezone.localdate()
    if not interface_filter:
        default_interface = os.environ.get("NETAUTO_BATCH_INTERFACE", "").strip()
        interface_filter = default_interface or None
    devices = list(Device.objects.order_by("id"))
    enable_batch_sync = _env_enabled("NETAUTO_ENABLE_BATCH_SYNC", True)
    results = []
    total = max(len(devices), 1)

    if progress_callback:
        progress_callback(0, "start", {"total_devices": len(devices)})

    for idx, device in enumerate(devices, start=1):
        base_pct = int(((idx - 1) / total) * 100)
        if progress_callback:
            progress_callback(
                base_pct,
                "sync",
                {"device": device.hostname, "message": "Sincronizando dispositivo"},
            )
        if enable_batch_sync:
            sync_result, _ports = sync_device(device)
            sync_ok = sync_result.get("rc") == 0
            if sync_ok:
                device.last_sync = timezone.now()
                device.save(update_fields=["last_sync"])
            elif progress_callback:
                progress_callback(
                    min(base_pct + 10, 99),
                    "sync_failed_continue",
                    {
                        "device": device.hostname,
                        "message": "Sync fallo, continuando con estado en base de datos",
                    },
                )
        else:
            sync_result = {
                "status": "skipped",
                "rc": 0,
                "message": "Sync deshabilitado por NETAUTO_ENABLE_BATCH_SYNC",
            }
            sync_ok = True

        ports = list(Port.objects.filter(device=device).order_by("interface"))
        if interface_filter:
            selected_ports = [
                port for port in ports if (port.interface or "").lower() == interface_filter.lower()
            ]
        else:
            selected_ports = [
                port for port in ports if (port.validation_action or "").upper() == "MIGRAR"
            ]
        if progress_callback:
            progress_callback(
                min(base_pct + 25, 99),
                "analyze_ports",
                {
                    "device": device.hostname,
                    "message": (
                        f"Interfaces objetivo: {len(selected_ports)}"
                        if interface_filter
                        else f"Puertos MIGRAR: {len(selected_ports)}"
                    ),
                },
            )
        if not selected_ports:
            status = "skipped" if sync_ok else "sync_failed_no_candidates"
            reason = (
                f"interface {interface_filter} no encontrada"
                if interface_filter
                else "sin puertos MIGRAR"
            )
            results.append(
                {
                    "device": device.hostname,
                    "status": status,
                    "reason": reason,
                    "sync": {
                        "ok": sync_ok,
                        "result": sync_result,
                    },
                }
            )
            if progress_callback:
                progress_callback(
                    min(base_pct + 35, 99),
                    "skipped",
                    {"device": device.hostname, "message": "Sin puertos candidatos"},
                )
            continue

        ports_payload = []
        for port in selected_ports:
            ports_payload.append(
                {
                    "interface": port.interface,
                    "description": port.description or "",
                    "vlan": port.vlan if port.vlan is not None else 10,
                    "mode": "access",
                    "template_name": "STANDARD_8021X",
                }
            )
        if progress_callback:
            progress_callback(
                min(base_pct + 45, 99),
                "create_cr",
                {"device": device.hostname, "message": "Creando change request"},
            )
        change_request = _create_change_request_for_device(device, ports_payload)
        if progress_callback:
            progress_callback(
                min(base_pct + 60, 99),
                "ai_approval",
                {
                    "device": device.hostname,
                    "message": f"Evaluando CR #{change_request.id} con IA",
                    "change_request": change_request.id,
                },
            )
        payload, status = _ai_approve_and_deploy(change_request, request_user=request_user)
        results.append(
            {
                "device": device.hostname,
                "change_request": change_request.id,
                "http_status": status,
                "result": payload,
                "sync": {
                    "ok": sync_ok,
                    "result": sync_result,
                },
            }
        )
        if progress_callback:
            progress_callback(
                min(base_pct + 95, 99),
                "device_done",
                {
                    "device": device.hostname,
                    "message": f"Dispositivo completado (CR #{change_request.id})",
                    "change_request": change_request.id,
                },
            )

    if progress_callback:
        progress_callback(100, "done", {"processed_devices": len(devices)})
    return {"status": "ok", "date": str(today), "results": results}


@method_decorator(csrf_exempt, name="dispatch")
class ChangeRequestAiApproveDeployBatchAsyncView(View):
    def post(self, request: HttpRequest) -> HttpResponse:
        from audit.tasks import ai_approve_deploy_batch_task

        user_id = request.user.id if request.user.is_authenticated else None
        interface_filter = None
        raw = request.body.decode("utf-8", errors="ignore").strip()
        if raw:
            try:
                data = json.loads(raw)
                maybe_interface = (data.get("interface") or "").strip()
                interface_filter = maybe_interface or None
            except json.JSONDecodeError:
                interface_filter = None
        task = ai_approve_deploy_batch_task.delay(
            user_id=user_id,
            interface_filter=interface_filter,
        )
        return JsonResponse({"status": "ok", "task_id": task.id})


@method_decorator(csrf_exempt, name="dispatch")
class JobListView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        items = DeploymentResult.objects.select_related(
            "change_request", "change_request__device"
        ).order_by("-deployed_at")[:200]

        latest_job = None
        for item in items:
            ansible_payload, ai_meta, ai_trace = _extract_ai_metrics(item.ansible_output or "")
            ai_decision = (
                ansible_payload.get("ai_decision") if isinstance(ansible_payload, dict) else None
            )
            if not isinstance(ai_decision, dict):
                continue

            started_at = (
                ai_trace[0].get("ts") if ai_trace and isinstance(ai_trace[0], dict) else None
            )
            ended_at = (
                ai_trace[-1].get("ts") if ai_trace and isinstance(ai_trace[-1], dict) else None
            )
            started_dt = _parse_iso_datetime(started_at)
            ended_dt = _parse_iso_datetime(ended_at)
            total_minutes = None
            if started_dt and ended_dt:
                total_minutes = (ended_dt - started_dt).total_seconds() / 60.0

            maybe_stats = ai_meta.get("ollama_stats") if isinstance(ai_meta, dict) else None
            stats = maybe_stats if isinstance(maybe_stats, dict) else {}
            input_tokens = int(stats.get("prompt_eval_count") or 0)
            output_tokens = int(stats.get("eval_count") or 0)

            final_reply = ai_decision.get("reason") or "Sin razon detallada."
            status_text = (
                "success" if bool(ai_decision.get("approve")) and item.success else "error"
            )
            error_text = None if status_text == "success" else final_reply

            user_message = (
                f"Autorizacion IA para CR #{item.change_request_id} "
                f"en {item.change_request.device.hostname}"
            )
            latest_job = {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"netauto-cr-{item.change_request_id}")),
                "started_at": started_at,
                "ended_at": ended_at,
                "total_time": total_minutes,
                "user_message": user_message,
                "final_reply": final_reply,
                "status": status_text,
                "error_text": error_text,
                "total_input_tokens": input_tokens,
                "total_output_tokens": output_tokens,
                "events": _build_agent_event_list(
                    {
                        "ai_trace": ai_trace,
                        "ai_meta": ai_meta,
                        "change_request_id": item.change_request_id,
                        "result": ansible_payload.get("result")
                        if isinstance(ansible_payload, dict)
                        else None,
                    },
                    started_at,
                    ended_at,
                ),
            }
            break

        response = JsonResponse(latest_job or {})
        response["Access-Control-Allow-Origin"] = "*"
        return response


@method_decorator(csrf_exempt, name="dispatch")
class JobStatusView(View):
    def get(self, request: HttpRequest, task_id: str) -> HttpResponse:
        result = AsyncResult(task_id)
        meta = result.info if isinstance(result.info, dict) else None
        status = result.status
        if status == "PENDING":
            try:
                inspector = celery_app.control.inspect(timeout=1)
                active = inspector.active() or {}
                is_active = any(
                    any(task.get("id") == task_id for task in (tasks or []))
                    for tasks in active.values()
                )
                if is_active:
                    status = "RUNNING"
                    if not meta:
                        meta = {
                            "percent": 1,
                            "stage": "running",
                            "message": "Tarea en ejecucion (worker activo)",
                        }
            except Exception:
                pass
        payload = {
            "id": task_id,
            "status": status,
            "ready": result.ready(),
            "successful": result.successful() if result.ready() else None,
            "progress": meta,
            "result": result.result if result.ready() else None,
        }
        response = JsonResponse({"status": "ok", "task": payload})
        response["Access-Control-Allow-Origin"] = "*"
        return response


def _tcp_check(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _lookup_inventory_port(inventory_path: str, hostname: str) -> int:
    port = 22
    try:
        with open(inventory_path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("["):
                    continue
                if not line.startswith(f"{hostname} "):
                    continue
                for part in line.split():
                    if part.startswith("ansible_port="):
                        value = part.split("=", 1)[-1]
                        if value.isdigit():
                            port = int(value)
                break
    except FileNotFoundError:
        return port
    return port


class ChangeRequestResultsView(View):
    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        change_request = ChangeRequest.objects.get(pk=pk)
        results = DeploymentResult.objects.filter(change_request=change_request).order_by(
            "-deployed_at"
        )
        logs = ChangeLog.objects.filter(change_request=change_request).order_by("-deployed_at")
        approvals = (
            ChangeApproval.objects.filter(change_request=change_request)
            .select_related("approved_by")
            .order_by("-approved_at")
        )
        result_payload = []
        for item in results:
            execution_source = "analyst"
            execution_reason = "Aprobado manualmente."
            try:
                parsed = json.loads(item.ansible_output) if item.ansible_output else {}
            except json.JSONDecodeError:
                parsed = {}
            ai_decision = parsed.get("ai_decision") if isinstance(parsed, dict) else None
            if isinstance(ai_decision, dict):
                execution_source = "ai"
                execution_reason = ai_decision.get("reason") or "Decision automatica por IA."
            result_payload.append(
                {
                    "id": item.id,
                    "success": item.success,
                    "ansible_output": item.ansible_output,
                    "deployed_at": item.deployed_at,
                    "execution_source": execution_source,
                    "execution_reason": execution_reason,
                }
            )
        snapshot = (
            ConfigSnapshot.objects.filter(change_request=change_request)
            .order_by("-created_at")
            .first()
        )
        log_payload = []
        for item in logs:
            log_payload.append(
                {
                    "id": item.id,
                    "port_interface": item.port_interface,
                    "field": item.field,
                    "old_value": item.old_value,
                    "new_value": item.new_value,
                    "deployed_by": item.deployed_by_id,
                    "deployed_at": item.deployed_at,
                }
            )
        approval_payload = []
        for item in approvals:
            source, actor, reason = _approval_source_and_reason(item)
            approval_payload.append(
                {
                    "id": item.id,
                    "source": source,
                    "actor": actor,
                    "reason": reason,
                    "comments": item.comments,
                    "approved_at": item.approved_at,
                }
            )
        latest_approval = approval_payload[0] if approval_payload else None
        return JsonResponse(
            {
                "status": "ok",
                "results": result_payload,
                "approvals": approval_payload,
                "decision_summary": latest_approval,
                "change_logs": log_payload,
                "snapshot": {
                    "created_at": snapshot.created_at if snapshot else None,
                    "running_config": snapshot.running_config if snapshot else "",
                },
            }
        )


def _parse_iso_datetime(value: object):
    if not isinstance(value, str) or not value:
        return None
    try:
        return timezone.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_ai_metrics(ansible_output: str) -> tuple[dict, dict, list[dict]]:
    try:
        payload = json.loads(ansible_output) if ansible_output else {}
    except json.JSONDecodeError:
        return {}, {}, []
    if not isinstance(payload, dict):
        return {}, {}, []
    ai_decision = payload.get("ai_decision") if isinstance(payload.get("ai_decision"), dict) else {}
    ai_meta = ai_decision.get("meta") if isinstance(ai_decision.get("meta"), dict) else {}
    ai_trace = ai_decision.get("trace") if isinstance(ai_decision.get("trace"), list) else []
    return payload, ai_meta, ai_trace


@method_decorator(csrf_exempt, name="dispatch")
class AiAuthorizationDashboardView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        limit = int(request.GET.get("limit", "50"))
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200

        approvals = (
            ChangeApproval.objects.filter(comments__istartswith="IA")
            .select_related("change_request", "change_request__device")
            .order_by("-approved_at")[:limit]
        )

        items = []
        total_prompt_tokens = 0
        total_eval_tokens = 0
        total_tokens = 0

        for approval in approvals:
            change_request = approval.change_request
            deployment = (
                DeploymentResult.objects.filter(change_request=change_request)
                .order_by("-deployed_at")
                .first()
            )

            ansible_payload, ai_meta, ai_trace = _extract_ai_metrics(
                deployment.ansible_output if deployment else ""
            )
            ollama_stats = ai_meta.get("ollama_stats") if isinstance(ai_meta, dict) else {}
            prompt_tokens = (
                int(ollama_stats.get("prompt_eval_count") or 0)
                if isinstance(ollama_stats, dict)
                else 0
            )
            eval_tokens = (
                int(ollama_stats.get("eval_count") or 0) if isinstance(ollama_stats, dict) else 0
            )
            token_total = prompt_tokens + eval_tokens
            total_prompt_tokens += prompt_tokens
            total_eval_tokens += eval_tokens
            total_tokens += token_total

            start_ts = None
            end_ts = None
            for step in ai_trace:
                if not isinstance(step, dict):
                    continue
                if step.get("step") == "start" and not start_ts:
                    start_ts = step.get("ts")
                if step.get("step") in {"deploy_finished", "model_verdict", "local_policy_reject"}:
                    end_ts = step.get("ts")
            start_dt = _parse_iso_datetime(start_ts)
            end_dt = _parse_iso_datetime(end_ts)
            duration_ms = None
            if start_dt and end_dt:
                duration_ms = int((end_dt - start_dt).total_seconds() * 1000)

            change_log_count = (
                ChangeLog.objects.filter(change_request=change_request)
                .values("port_interface")
                .distinct()
                .count()
            )
            interface_count = len(change_request.ports_json or [])
            migrated_status = f"{change_log_count}/{interface_count} interfaces aplicadas"

            source, actor, reason = _approval_source_and_reason(approval)
            status = "rejected"
            error = ""
            final_info = reason
            if change_request.status == ChangeRequest.STATUS_DEPLOYED:
                status = "deployed"
                final_info = f"Despliegue exitoso. {migrated_status}."
            elif change_request.status in {
                ChangeRequest.STATUS_FAILED,
                ChangeRequest.STATUS_REJECTED,
            }:
                status = "error"
                if source == "ai" and reason:
                    error = reason
                elif deployment and not deployment.success:
                    error = "Deploy fallido"
                else:
                    error = "No autorizado por IA"
            elif change_request.status == ChangeRequest.STATUS_APPROVED:
                status = "approved"
                final_info = "Aprobado por IA, pendiente despliegue."

            if deployment and not deployment.success and not error:
                error = "Deploy fallido"

            items.append(
                {
                    "task_id": f"CR-{change_request.id}",
                    "change_request_id": change_request.id,
                    "source": source,
                    "actor": actor,
                    "device": {
                        "hostname": change_request.device.hostname,
                        "ip": change_request.device.ip,
                        "site": change_request.site,
                    },
                    "model": ai_meta.get("model") if isinstance(ai_meta, dict) else "",
                    "started_at": start_ts,
                    "finished_at": end_ts,
                    "duration_ms": duration_ms,
                    "status": status,
                    "reason": reason,
                    "error": error,
                    "final_info": final_info,
                    "interfaces": {
                        "requested": interface_count,
                        "migrated": change_log_count,
                        "status": migrated_status,
                    },
                    "tokens": {
                        "prompt": prompt_tokens,
                        "completion": eval_tokens,
                        "total": token_total,
                    },
                    "raw_result": ansible_payload,
                }
            )

        return JsonResponse(
            {
                "status": "ok",
                "summary": {
                    "total_tasks": len(items),
                    "total_tokens": total_tokens,
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_eval_tokens,
                    "deployed": len([item for item in items if item["status"] == "deployed"]),
                    "errors": len([item for item in items if item["status"] == "error"]),
                },
                "items": items,
            }
        )


class ChangeRequestDetailView(View):
    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        change_request = ChangeRequest.objects.get(pk=pk)
        return JsonResponse(
            {
                "status": "ok",
                "change_request": {
                    "id": change_request.id,
                    "device_id": change_request.device_id,
                    "status": change_request.status,
                    "created_at": change_request.created_at,
                    "ports": change_request.ports_json,
                    "generated_config": change_request.generated_config,
                },
            }
        )


class ChangeRequestDiffView(View):
    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        change_request = ChangeRequest.objects.get(pk=pk)
        snapshot = (
            ConfigSnapshot.objects.filter(change_request=change_request)
            .order_by("-created_at")
            .first()
        )
        snapshots = list(
            ConfigSnapshot.objects.filter(change_request=change_request).order_by("created_at")
        )
        if len(snapshots) < 2:
            return JsonResponse(
                {"status": "error", "message": "not enough snapshots"},
                status=404,
            )

        before_text = snapshots[0].running_config or ""
        after_text = snapshots[-1].running_config or ""

        def _filter_runtime(lines: list[str]) -> list[str]:
            filtered = []
            for line in lines:
                if line.startswith("! Last configuration change"):
                    continue
                if line.startswith("! NVRAM config last updated"):
                    continue
                filtered.append(line)
            return filtered

        before_lines = _filter_runtime(before_text.splitlines())
        after_lines = _filter_runtime(after_text.splitlines())

        diff_lines = list(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile="running-config (antes)",
                tofile="running-config (despues)",
                lineterm="",
                n=4,
            )
        )
        diff_rows = []
        for line in diff_lines:
            if line.startswith("---") or line.startswith("+++"):
                continue
            if line.startswith("@@"):
                diff_rows.append(
                    "<tr class='hunk'><td class='code' colspan='2'>"
                    + html.escape(line)
                    + "</td></tr>"
                )
                continue
            if line.startswith("+"):
                cls = "insert"
            elif line.startswith("-"):
                cls = "delete"
            else:
                cls = "context"
            diff_rows.append(
                "<tr class='" + cls + "'>"
                "<td class='sign'>" + html.escape(line[:1] if cls != "context" else "") + "</td>"
                "<td class='code'>" + html.escape(line[1:] if cls != "context" else line) + "</td>"
                "</tr>"
            )

        page = (
            "<!doctype html>"
            '<html lang="es">'
            "<head>"
            '<meta charset="utf-8" />'
            '<meta name="viewport" content="width=device-width, initial-scale=1" />'
            f"<title>Compare CR #{change_request.id}</title>"
            "<style>"
            "body { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; "
            "background: #0b1220; color: #e5e7eb; margin: 0; }"
            ".top { padding: 16px 20px; border-bottom: 1px solid #1f2937; "
            "display: flex; gap: 12px; align-items: center; flex-wrap: wrap; position: relative; }"
            ".toggle { position: absolute; left: 50%; transform: translateX(-50%); margin-left: 0; }"
            "@media (max-width: 720px) { .toggle { position: static; transform: none; } }"
            ".badge { font-size: 12px; color: #93c5fd; background: #0f172a; "
            "padding: 4px 10px; border: 1px solid #1d4ed8; border-radius: 999px; }"
            ".toggle { display: inline-flex; align-items: center; gap: 8px; "
            "padding: 6px 10px; border-radius: 999px; background: #111827; "
            "border: 1px solid #1f2937; color: #e5e7eb; font-size: 12px; cursor: pointer; }"
            ".toggle .icon { width: 18px; height: 18px; border-radius: 999px; "
            "background: #0f172a; display: inline-grid; place-items: center; "
            "border: 1px solid #1f2937; font-weight: 700; }"
            ".container { height: calc(100vh - 58px); overflow: auto; }"
            "table { width: 100%; border-collapse: collapse; }"
            "th, td { padding: 6px 10px; vertical-align: top; }"
            "th { position: sticky; top: 0; background: #111827; font-size: 12px; "
            "text-align: left; border-bottom: 1px solid #1f2937; z-index: 1; }"
            ".sign { width: 24px; text-align: center; font-weight: 700; }"
            ".code { white-space: pre; font-size: 12px; line-height: 1.45; }"
            "tr.hunk td { color: #93c5fd; background: #0f172a; font-size: 12px; }"
            "tr.context td { background: #0b1220; color: #cbd5f5; }"
            "tr.delete td { background: #3f1d1d; }"
            "tr.insert td { background: #163b2b; }"
            ".full-block { display: none; padding: 16px 20px; border-top: 1px solid #1f2937; }"
            ".full-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }"
            ".full-title { font-size: 12px; color: #93c5fd; margin-bottom: 8px; }"
            ".full-pre { background: #0f172a; border: 1px solid #1f2937; "
            "border-radius: 12px; padding: 12px; white-space: pre; overflow: auto; max-height: 50vh; }"
            "</style>"
            "</head>"
            "<body>"
            f'<div class="top">CR #{change_request.id} · cambios entre running-config '
            '<span class="badge">solo cambios</span>'
            '<button class="toggle" id="toggleFull" title="Ver running-config completo">'
            '<span class="icon" id="toggleIcon">+</span>ver todo</button>'
            "</div>"
            '<div class="container">'
            "<table>"
            "<thead><tr>"
            "<th colspan='2'>Cambios (formato git)</th>"
            "</tr></thead>"
            "<tbody>" + "".join(diff_rows) + "</tbody></table>"
            "<div class='full-block' id='fullBlock'>"
            "<div class='full-grid'>"
            "<div><div class='full-title'>running-config antes</div>"
            "<pre class='full-pre'>" + html.escape(before_text) + "</pre></div>"
            "<div><div class='full-title'>running-config despues</div>"
            "<pre class='full-pre'>" + html.escape(after_text) + "</pre></div>"
            "</div></div></div>"
            "<script>"
            "const toggle=document.getElementById('toggleFull');"
            "const block=document.getElementById('fullBlock');"
            "const icon=document.getElementById('toggleIcon');"
            "toggle.addEventListener('click',()=>{"
            "const open=block.style.display==='block';"
            "block.style.display=open?'none':'block';"
            "icon.textContent=open?'+':'-';"
            "});"
            "</script>"
            "</body>"
            "</html>"
        )
        return HttpResponse(page)


def _format_diff(diff_text: str) -> str:
    lines = diff_text.splitlines()
    output = []
    for line in lines:
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            output.append(f"<span class='meta'>{line}</span>")
        elif line.startswith("+"):
            output.append(f"<span class='add'>{line}</span>")
        elif line.startswith("-"):
            output.append(f"<span class='del'>{line}</span>")
        else:
            output.append(line)
    return "\n".join(output)


@method_decorator(csrf_exempt, name="dispatch")
class TokenRevokeView(View):
    def post(self, request: HttpRequest) -> HttpResponse:
        payload = request.body.decode("utf-8", errors="ignore")
        if not payload:
            return JsonResponse({"status": "error", "message": "empty body"}, status=400)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "invalid json"}, status=400)

        token_value = data.get("token")
        if not token_value:
            return JsonResponse({"status": "error", "message": "token required"}, status=400)
        try:
            token = ApiToken.objects.get(token=token_value)
        except ApiToken.DoesNotExist:
            return JsonResponse({"status": "error", "message": "not found"}, status=404)
        token.is_active = False
        token.save(update_fields=["is_active"])
        return JsonResponse({"status": "ok"})


@method_decorator(csrf_exempt, name="dispatch")
class TokenRotateView(View):
    def post(self, request: HttpRequest) -> HttpResponse:
        payload = request.body.decode("utf-8", errors="ignore")
        if not payload:
            return JsonResponse({"status": "error", "message": "empty body"}, status=400)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "invalid json"}, status=400)

        token_value = data.get("token")
        if not token_value:
            return JsonResponse({"status": "error", "message": "token required"}, status=400)
        try:
            token = ApiToken.objects.get(token=token_value, is_active=True)
        except ApiToken.DoesNotExist:
            return JsonResponse({"status": "error", "message": "not found"}, status=404)
        new_value = ApiToken.generate()
        token.token = new_value
        token.rotated_at = timezone.now()
        token.save(update_fields=["token", "rotated_at"])
        return JsonResponse({"status": "ok", "token": new_value})


class TokenListView(View):
    @method_decorator(permission_required("accounts.view_apitoken", raise_exception=True))
    def get(self, request: HttpRequest) -> HttpResponse:
        tokens = ApiToken.objects.select_related("user").order_by("-created_at")[:200]
        payload = []
        for token in tokens:
            payload.append(
                {
                    "id": token.id,
                    "user": token.user.username,
                    "name": token.name,
                    "is_active": token.is_active,
                    "created_at": token.created_at,
                    "expires_at": token.expires_at,
                    "last_used_at": token.last_used_at,
                    "rotated_at": token.rotated_at,
                }
            )
        return JsonResponse({"status": "ok", "tokens": payload})


def _expand_interface(name: str) -> str:
    if not name:
        return name
    name = name.strip().rstrip(",;:")
    if name.startswith("TenGi"):
        return name.replace("TenGi", "TenGigabitEthernet", 1)
    if name.startswith("Gi"):
        return name.replace("Gi", "GigabitEthernet", 1)
    if name.startswith("Fa"):
        return name.replace("Fa", "FastEthernet", 1)
    if name.startswith("Te"):
        return name.replace("Te", "TenGigabitEthernet", 1)
    if name.startswith("Et"):
        return name.replace("Et", "Ethernet", 1)
    return name
