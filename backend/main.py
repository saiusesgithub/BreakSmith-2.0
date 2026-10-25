"""Local-only BreakSmith orchestrator. Untrusted repository code is never executed."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "backend" / "rules" / "python-security.yml"
DEMO = ROOT / "demo-repository"
MODEL = os.getenv("BREAKSMITH_MODEL", "qwen3:4b")
OLLAMA = os.getenv("BREAKSMITH_OLLAMA_URL", "http://localhost:11434").rstrip("/")
TIMEOUT = float(os.getenv("BREAKSMITH_INFERENCE_TIMEOUT", "180"))
THINK = os.getenv("BREAKSMITH_THINK", "false").lower() == "true"
MAX_BYTES = 30 * 1024 * 1024
MAX_FILES = 3000
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
MODEL_LOCK = threading.Lock()

app = FastAPI(title="BreakSmith 2.0", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET", "POST"], allow_headers=["*"])


class ScanRequest(BaseModel):
    source: str


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def event(job: dict, agent: str, action: str, status: str, outcome: str = "") -> None:
    job["events"].append({"timestamp": now(), "agent": agent, "action": action, "status": status, "outcome": outcome})
    job["updated_at"] = now()


def stage(job: dict, state: str, agent: str, outcome: str = "") -> None:
    job["state"] = state
    event(job, agent, state.replace("_", " ").title(), "running" if state not in {"COMPLETE", "FAILED"} else state.lower(), outcome)


def safe_github_url(source: str) -> bool:
    try:
        parsed = urlparse(source)
        parts = parsed.path.strip("/").removesuffix(".git").split("/")
        return (parsed.scheme == "https" and parsed.hostname == "github.com" and not parsed.port
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                and len(parts) == 2 and all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in parts))
    except ValueError:
        return False


def allowed_local(source: str) -> Path:
    path = Path(source).expanduser().resolve(strict=True)
    configured = os.getenv("BREAKSMITH_LOCAL_ROOTS", str(ROOT))
    roots = [Path(p).expanduser().resolve() for p in configured.split(os.pathsep) if p]
    if not path.is_dir() or not any(path == r or r in path.parents for r in roots):
        raise ValueError("Local directory must be inside BREAKSMITH_LOCAL_ROOTS.")
    return path


def copy_sources(source: Path, target: Path) -> tuple[int, int]:
    count = total = 0
    excluded = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"}
    for directory, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [d for d in dirs if d not in excluded and not (Path(directory) / d).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink() or path.suffix.lower() != ".py":
                continue
            size = path.stat().st_size
            count += 1
            total += size
            if count > MAX_FILES or total > MAX_BYTES:
                raise ValueError("Repository exceeds the 3,000 source file or 30 MB source limit.")
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    return count, total


def clone(source: str, target: Path) -> None:
    env = os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "GIT_ALLOW_PROTOCOL": "https",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_LFS_SKIP_SMUDGE": "1"})
    command = ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "credential.helper=", "-c", "http.followRedirects=false",
               "clone", "--depth", "1", "--single-branch", "--no-tags", "--filter=blob:none", source, str(target)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, env=env)
    if result.returncode:
        raise RuntimeError(f"Git clone failed: {result.stderr.strip()[-500:]}")


def snippet(path: Path, line: int, radius: int = 5) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start, end = max(0, line - radius - 1), min(len(lines), line + radius)
    return "\n".join(f"{i + 1:>4}  {lines[i]}" for i in range(start, end))


def scan(workspace: Path) -> list[dict]:
    executable = Path(sys.executable).with_name("semgrep.exe" if os.name == "nt" else "semgrep")
    command = [str(executable), "scan", "--config", str(RULES), "--json", "--quiet", "--metrics=off", "--no-git-ignore", "."]
    semgrep_data = workspace / ".semgrep"
    semgrep_data.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update({"XDG_CONFIG_HOME": str(workspace), "XDG_CACHE_HOME": str(workspace),
                "SEMGREP_LOG_FILE": str(semgrep_data / "semgrep.log"),
                "SEMGREP_SETTINGS_FILE": str(semgrep_data / "settings.yml"),
                "SEMGREP_VERSION_CACHE_PATH": str(semgrep_data / "version")})
    try:
        result = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=120, env=env)
    except FileNotFoundError as exc:
        raise RuntimeError("Semgrep CLI is unavailable. Install backend requirements and restart the backend.") from exc
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Semgrep failed: {(result.stderr or result.stdout)[-700:]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Semgrep returned invalid JSON: {result.stderr[-500:]}") from exc
    findings = []
    for item in payload.get("results", []):
        reported = Path(item["path"])
        path = (reported if reported.is_absolute() else workspace / reported).resolve()
        if not path.is_relative_to(workspace.resolve()) or path.is_symlink():
            continue
        rel = path.relative_to(workspace.resolve()).as_posix()
        line = item["start"]["line"]
        check_id = item["check_id"]
        rule_id = check_id[check_id.find("breaksmith."):] if "breaksmith." in check_id else check_id
        rule = rule_id.split(".")[-1]
        severity = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}.get(item["extra"].get("severity", "INFO"), "LOW")
        title = item["extra"].get("metadata", {}).get("title") or rule.replace("-", " ").title()
        findings.append({"id": uuid.uuid5(uuid.NAMESPACE_URL, f"{rel}:{line}:{rule}").hex[:12], "title": title, "severity": severity,
                         "filename": rel, "line": line, "rule_id": rule_id, "snippet": snippet(path, line),
                         "explanation": item["extra"].get("message", ""), "analysis": None, "fix": None, "ai_error": None})
    return sorted(findings, key=lambda f: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}[f["severity"]], f["filename"], f["line"]))


def ask_model(system: str, evidence: dict, keys: set[str]) -> dict:
    no_think = "" if THINK else "/no_think\n"
    request = {"model": MODEL, "stream": False, "think": THINK, "format": "json", "options": {"temperature": 0.1, "num_predict": 450},
               "messages": [{"role": "system", "content": no_think + system}, {"role": "user", "content": no_think + json.dumps(evidence)}]}
    try:
        with MODEL_LOCK, httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(f"{OLLAMA}/api/chat", json=request)
            if response.is_error:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")
            content = response.json()["message"]["content"].split("</think>")[-1].strip()
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Model response is not a JSON object")
        if not keys <= parsed.keys():
            raise ValueError(f"Model response missing fields: {', '.join(sorted(keys - parsed.keys()))}")
        return parsed
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        raise RuntimeError(f"Ollama {MODEL} response failed: {exc}") from exc


def analyze(job: dict, finding: dict) -> None:
    stage(job, "ANALYZING", "AI Analyst", f"Reviewing {finding['filename']}:{finding['line']}")
    data = ask_model("You are a careful security analyst. Use only the given scanner evidence. Return a concise JSON object with keys category, explanation, impact, risk, remediation, uncertainty. Do not claim exploitability without evidence.",
                     {k: finding[k] for k in ("title", "severity", "rule_id", "snippet", "explanation")},
                     {"category", "explanation", "impact", "risk", "remediation", "uncertainty"})
    finding["analysis"] = data
    event(job, "AI Analyst", "Analysis complete", "complete", f"{finding['title']} analyzed by {MODEL}")


def propose_fix(job: dict, finding: dict) -> None:
    stage(job, "GENERATING_FIX", "Remediation Agent", f"Preparing fix for {finding['filename']}:{finding['line']}")
    source_line = next((line[6:] for line in finding["snippet"].splitlines() if line.startswith(f"{finding['line']:>4}  ")), None)
    if not source_line:
        raise RuntimeError("Could not locate the exact finding line in scanner evidence.")
    rule_advice = ("For shell invocation, pass a list such as ['nslookup', hostname] with shell=False; never compose a command string."
                   if "shell-true" in finding["rule_id"] else
                   "For SQL construction, use query placeholders and a separate parameter tuple; never interpolate user data into SQL. This code uses sqlite3, so use a ? placeholder, not %s."
                   if "sql-string-format" in finding["rule_id"] and "sqlite3" in finding["snippet"] else
                   "For SQL construction, use placeholders supported by the database driver and a separate parameter tuple."
                   if "sql-string-format" in finding["rule_id"] else "Keep the replacement minimal and functional.")
    data = ask_model("Fix one Python security flaw. Return ONLY a JSON object with string keys original_code, corrected_code, explanation, confidence, verification. Copy original_code verbatim from source_line and give a minimal corrected_code. " + rule_advice,
                     {"issue": finding["explanation"], "source_line": source_line},
                     {"original_code", "corrected_code", "explanation", "confidence", "verification"})
    if not all(isinstance(data[k], str) and data[k].strip() for k in ("original_code", "corrected_code")):
        raise RuntimeError("Model returned an empty code replacement.")
    if source_line.count(data["original_code"]) != 1 or data["original_code"] == data["corrected_code"]:
        raise RuntimeError("Model replacement did not match the source excerpt exactly and unambiguously.")
    if "sql-string-format" in finding["rule_id"] and "sqlite3" in finding["snippet"] and "%s" in data["corrected_code"]:
        raise RuntimeError("Model suggested a placeholder incompatible with sqlite3.")
    if "shell-true" in finding["rule_id"] and "shell=True" in data["corrected_code"].replace(" ", ""):
        raise RuntimeError("Model retained shell=True in the proposed replacement.")
    finding["fix"] = data
    event(job, "Remediation Agent", "Fix proposed", "complete", f"Suggested replacement for {finding['filename']}")


def run_job(job: dict) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix="breaksmith-") as temp:
            workspace = Path(temp) / "source"
            source = job["source"]
            if source == "demo":
                stage(job, "CLONING", "Recon Agent", "Copying the intentionally vulnerable demo into an isolated workspace")
                workspace.mkdir()
                count, size = copy_sources(DEMO, workspace)
            elif safe_github_url(source):
                stage(job, "CLONING", "Recon Agent", "Cloning public GitHub repository")
                raw = Path(temp) / "clone"
                clone(source, raw)
                workspace.mkdir()
                count, size = copy_sources(raw, workspace)
            else:
                stage(job, "CLONING", "Recon Agent", "Copying allowed local source into an isolated workspace")
                workspace.mkdir()
                count, size = copy_sources(allowed_local(source), workspace)
            job["metrics"]["files_scanned"] = count
            job["metrics"]["source_bytes"] = size
            event(job, "Recon Agent", "Source indexed", "complete", f"{count} source files ({size:,} bytes)")
            if not count:
                stage(job, "COMPLETE", "Orchestrator", "No supported Python source files to scan")
                return
            stage(job, "SCANNING", "Vulnerability Scanner", "Running curated Semgrep rules")
            job["findings"] = scan(workspace)
            event(job, "Vulnerability Scanner", "Scan complete", "complete", f"{len(job['findings'])} findings")
            if not job["findings"]:
                stage(job, "COMPLETE", "Orchestrator", "No scanner findings. No AI analysis was performed.")
                return
            for finding in job["findings"][:3]:
                try:
                    analyze(job, finding)
                except RuntimeError as exc:
                    finding["ai_error"] = str(exc)
                    event(job, "AI Analyst", "Analysis failed", "error", str(exc))
            for candidate in (f for f in job["findings"] if f["analysis"]):
                try:
                    propose_fix(job, candidate)
                    break
                except RuntimeError as exc:
                    candidate["ai_error"] = str(exc)
                    event(job, "Remediation Agent", "Fix failed", "error", str(exc))
            stage(job, "COMPLETE", "Orchestrator", "Scan workflow finished")
    except Exception as exc:
        job["error"] = str(exc)
        stage(job, "FAILED", "Orchestrator", str(exc))


def investigate_finding(job: dict, finding: dict) -> None:
    try:
        if not finding["analysis"]:
            analyze(job, finding)
        if not finding["fix"]:
            propose_fix(job, finding)
    except RuntimeError as exc:
        finding["ai_error"] = str(exc)
        event(job, "AI Agent", "Investigation failed", "error", str(exc))
    finally:
        stage(job, "COMPLETE", "Orchestrator", "Selected finding investigation finished")


def public_job(job: dict) -> dict:
    findings = job["findings"]
    return {k: v for k, v in job.items() if k != "thread"} | {"summary": {"total": len(findings), "by_severity": dict(Counter(f["severity"] for f in findings)),
            "analyzed": sum(bool(f["analysis"]) for f in findings), "fixes_proposed": sum(bool(f["fix"]) for f in findings)}}


@app.get("/api/health")
def health() -> dict:
    try:
        with httpx.Client(timeout=3) as client:
            response = client.get(f"{OLLAMA}/api/tags")
            response.raise_for_status()
            models = [m["name"] for m in response.json().get("models", [])]
        ollama = {"available": MODEL in models, "model": MODEL, "error": None if MODEL in models else f"{MODEL} is not installed"}
    except Exception as exc:
        ollama = {"available": False, "model": MODEL, "error": str(exc)}
    semgrep_cli = Path(sys.executable).with_name("semgrep.exe" if os.name == "nt" else "semgrep")
    return {"status": "ok", "ollama": ollama, "semgrep": semgrep_cli.is_file()}


@app.post("/api/scans")
def create_scan(request: ScanRequest) -> dict:
    source = request.source.strip()
    if not source:
        raise HTTPException(400, "A repository URL or allowed local directory is required")
    if source != "demo" and not safe_github_url(source):
        try:
            allowed_local(source)
        except (OSError, ValueError) as exc:
            raise HTTPException(400, f"Enter a public https://github.com/owner/repo URL or an allowed local directory. {exc}") from exc
    with JOBS_LOCK:
        if sum(j["state"] not in {"COMPLETE", "FAILED"} for j in JOBS.values()) >= 2:
            raise HTTPException(429, "Two scans are already running. Wait for one to finish.")
        job = {"id": uuid.uuid4().hex, "source": source, "state": "IDLE", "created_at": now(), "updated_at": now(), "events": [], "findings": [], "metrics": {"files_scanned": 0, "source_bytes": 0}, "error": None}
        JOBS[job["id"]] = job
    thread = threading.Thread(target=run_job, args=(job,), daemon=True)
    thread.start()
    return {"id": job["id"]}


@app.get("/api/scans/{scan_id}")
def get_scan(scan_id: str) -> dict:
    job = JOBS.get(scan_id)
    if not job:
        raise HTTPException(404, "Scan not found")
    return public_job(job)


@app.post("/api/scans/{scan_id}/findings/{finding_id}/investigate")
def investigate(scan_id: str, finding_id: str) -> dict:
    job = JOBS.get(scan_id)
    if not job:
        raise HTTPException(404, "Scan not found")
    if job["state"] != "COMPLETE":
        raise HTTPException(409, "Wait for the current workflow to finish")
    finding = next((f for f in job["findings"] if f["id"] == finding_id), None)
    if not finding:
        raise HTTPException(404, "Finding not found")
    if finding["fix"]:
        return {"status": "already_proposed"}
    job["state"] = "ANALYZING"
    threading.Thread(target=investigate_finding, args=(job, finding), daemon=True).start()
    return {"status": "started"}
