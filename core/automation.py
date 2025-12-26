import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

import appdirs

from function import util


@dataclass
class AutomationStep:
    phase: str
    command: str
    allow_failure: bool = False


@dataclass
class CommandExecution:
    phase: str
    command: str
    started_at: float
    finished_at: float
    stdout: str
    stderr: str
    exit_code: int
    attempt: int
    ok: bool
    kind: str = "step"


@dataclass
class RepairAction:
    title: str
    commands: list[str]
    retry_original: bool = True


@dataclass
class AutomationRun:
    run_id: str
    operation: str
    target: str
    started_at: float
    updated_at: float
    status: str
    current_step_index: int = 0
    attempt: int = 0
    max_attempts: int = 3
    last_error: Optional[dict] = None
    executions: list[dict] = field(default_factory=list)
    report_path: str = ""


def _automation_base_dir() -> str:
    base = appdirs.user_data_dir(util.APP_NAME, roaming=False)
    return os.path.join(base, "automation")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _latest_index_path() -> str:
    return os.path.join(_automation_base_dir(), "latest.json")


def _run_record_path(run_id: str) -> str:
    return os.path.join(_automation_base_dir(), "runs", f"{run_id}.json")


def _load_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_json(path: str, data: dict) -> None:
    _ensure_dir(os.path.dirname(path))
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _latest_key(operation: str, target: str) -> str:
    return f"{operation}::{target}"


def get_latest_run_id(operation: str, target: str) -> Optional[str]:
    data = _load_json(_latest_index_path()) or {}
    return data.get(_latest_key(operation, target))


def set_latest_run_id(operation: str, target: str, run_id: str) -> None:
    path = _latest_index_path()
    data = _load_json(path) or {}
    data[_latest_key(operation, target)] = run_id
    _save_json(path, data)


def load_run(run_id: str) -> Optional[AutomationRun]:
    raw = _load_json(_run_record_path(run_id))
    if not raw:
        return None
    try:
        return AutomationRun(**raw)
    except Exception:
        return None


def save_run(run: AutomationRun) -> None:
    run.updated_at = time.time()
    if not run.report_path:
        run.report_path = _run_record_path(run.run_id)
    _save_json(_run_record_path(run.run_id), asdict(run))
    set_latest_run_id(run.operation, run.target, run.run_id)


class ErrorDiagnosisEngine:
    def propose_repairs(
            self,
            *,
            command: str,
            stdout: str,
            stderr: str,
            exit_code: int,
            distro_id: str = "",
    ) -> list[RepairAction]:
        text = f"{stdout}\n{stderr}".lower()
        distro = (distro_id or "").lower().strip()

        if any(x in text for x in ["not in the sudoers file", "a password is required", "permission denied"]):
            return []

        if any(x in text for x in ["could not get lock", "lock-frontend", "dpkg frontend lock"]):
            return [RepairAction("等待包管理器锁释放", ["sleep 3"], retry_original=True)]

        if any(x in text for x in ["dpkg was interrupted", "run 'dpkg --configure -a'"]):
            return [
                RepairAction(
                    "修复 dpkg 中断状态",
                    ["dpkg --configure -a", "apt -y -f install", "apt update"],
                    retry_original=True,
                )
            ]

        if any(x in text for x in ["temporary failure resolving", "could not resolve", "name or service not known"]):
            return [
                RepairAction(
                    "尝试修复 DNS/网络服务",
                    [
                        "systemctl restart systemd-resolved 2>/dev/null || true",
                        "systemctl restart NetworkManager 2>/dev/null || true",
                        "service network restart 2>/dev/null || true",
                    ],
                    retry_original=True,
                )
            ]

        if any(x in text for x in
               ["unable to locate package", "no package", "package .* has no installation candidate"]):
            return [RepairAction("刷新包索引/缓存", self._refresh_pkg_index(command=command, distro=distro), True)]

        if any(x in text for x in
               ["failed to start", "job for docker.service failed", "unit docker.service not found"]):
            return [
                RepairAction(
                    "尝试修复 docker 服务状态",
                    [
                        "systemctl daemon-reload 2>/dev/null || true",
                        "systemctl reset-failed docker 2>/dev/null || true",
                        "systemctl restart docker 2>/dev/null || true",
                    ],
                    retry_original=True,
                )
            ]

        if any(x in text for x in ["gpg", "no pubkey", "signature verification failed"]):
            if "apt" in command or "apt-get" in command or "debian" in distro or "ubuntu" in distro:
                return [
                    RepairAction(
                        "尝试修复 APT GPG/密钥问题",
                        ["apt update", "apt install -y ca-certificates curl gnupg"],
                        retry_original=True,
                    )
                ]
            return []

        return []

    def _refresh_pkg_index(self, *, command: str, distro: str) -> list[str]:
        cmd = (command or "").lower()
        if "apt-get" in cmd or "apt " in cmd or distro in {"ubuntu", "debian"}:
            return ["apt update"]
        if "dnf" in cmd or distro in {"fedora", "rhel", "rocky", "almalinux"}:
            return ["dnf makecache -y 2>/dev/null || dnf makecache 2>/dev/null || true"]
        if "yum" in cmd or distro in {"centos", "amzn"}:
            return ["yum makecache -y 2>/dev/null || yum makecache fast 2>/dev/null || true"]
        if "zypper" in cmd or distro in {"opensuse", "sles"}:
            return ["zypper refresh 2>/dev/null || true"]
        if "apk" in cmd or distro == "alpine":
            return ["apk update 2>/dev/null || true"]
        if "pacman" in cmd or distro == "arch":
            return ["pacman -Sy --noconfirm 2>/dev/null || true"]
        return []


class AutomationEngine:
    def __init__(
            self,
            *,
            execute_command: Callable[..., tuple[str, str, int]],
            operation: str,
            target: str,
            diagnosis: Optional[ErrorDiagnosisEngine] = None,
            max_attempts: int = 3,
            timeout: int = 300,
            should_stop: Optional[Callable[[], bool]] = None,
    ):
        self.execute_command = execute_command
        self.operation = operation
        self.target = target
        self.diagnosis = diagnosis or ErrorDiagnosisEngine()
        self.max_attempts = int(max_attempts)
        self.timeout = int(timeout)
        self.should_stop = should_stop

    def run(
            self,
            *,
            steps: list[AutomationStep],
            progress_callback: Optional[Callable[[str, int], None]] = None,
            sudo_password: Optional[str] = None,
            resume: bool = True,
            distro_id: str = "",
    ) -> AutomationRun:
        run = None
        if resume:
            latest_id = get_latest_run_id(self.operation, self.target)
            if latest_id:
                prev = load_run(latest_id)
                if prev and prev.status in {"running", "failed"}:
                    run = prev

        if not run:
            run = AutomationRun(
                run_id=str(uuid.uuid4()),
                operation=self.operation,
                target=self.target,
                started_at=time.time(),
                updated_at=time.time(),
                status="running",
                current_step_index=0,
                attempt=0,
                max_attempts=self.max_attempts,
            )
            save_run(run)

        if progress_callback and run.current_step_index > 0 and run.status in {"running", "failed"}:
            progress_callback(f"检测到未完成任务，正在从第 {run.current_step_index + 1} 步恢复", 1)

        run.status = "running"
        save_run(run)

        total = max(1, len(steps))
        for idx in range(run.current_step_index, len(steps)):
            if self.should_stop and self.should_stop():
                run.status = "stopped"
                save_run(run)
                return run
            step = steps[idx]
            pct = min(99, max(1, int(5 + 90 * (idx / total))))
            ok = self._execute_with_repairs(
                run=run,
                step=step,
                percent=pct,
                progress_callback=progress_callback,
                sudo_password=sudo_password,
                distro_id=distro_id,
            )
            if not ok and not step.allow_failure:
                run.status = "failed"
                run.current_step_index = idx
                save_run(run)
                return run
            run.current_step_index = idx + 1
            save_run(run)

        if self.should_stop and self.should_stop():
            run.status = "stopped"
            save_run(run)
            return run

        run.status = "success"
        save_run(run)
        if progress_callback:
            progress_callback("完成", 100)
        return run

    def _execute_with_repairs(
            self,
            *,
            run: AutomationRun,
            step: AutomationStep,
            percent: int,
            progress_callback: Optional[Callable[[str, int], None]],
            sudo_password: Optional[str],
            distro_id: str,
    ) -> bool:
        run.attempt = 0
        save_run(run)

        def emit(msg: str) -> None:
            if progress_callback:
                progress_callback(msg, percent)

        allow_failure = bool(step.allow_failure)
        for attempt in range(1, run.max_attempts + 1):
            if self.should_stop and self.should_stop():
                return False
            run.attempt = attempt
            save_run(run)

            started = time.time()
            stdout, stderr, exit_code = self.execute_command(
                step.command, sudo_password=sudo_password, timeout=self.timeout,
                output_callback=self._stream_cb(step, emit)
            )
            finished = time.time()

            if self.should_stop and self.should_stop():
                return False

            ok = (exit_code == 0) or allow_failure
            exec_item = CommandExecution(
                phase=step.phase,
                command=step.command,
                started_at=started,
                finished_at=finished,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                attempt=attempt,
                ok=ok,
                kind="step",
            )
            run.executions.append(asdict(exec_item))
            save_run(run)

            if ok:
                return True

            repairs = self.diagnosis.propose_repairs(
                command=step.command,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                distro_id=distro_id,
            )

            run.last_error = {
                "phase": step.phase,
                "command": step.command,
                "stdout_tail": (stdout or "")[-4000:],
                "stderr_tail": (stderr or "")[-4000:],
                "exit_code": exit_code,
                "attempt": attempt,
            }
            save_run(run)

            if not repairs:
                emit(f"失败: {step.command}\n{(stderr or stdout or '').strip()}")
                return False

            for repair in repairs:
                emit(f"诊断: {repair.title}")
                for rcmd in repair.commands:
                    if not rcmd or not rcmd.strip():
                        continue
                    r_started = time.time()
                    r_out, r_err, r_code = self.execute_command(
                        rcmd, sudo_password=sudo_password, timeout=self.timeout,
                        output_callback=self._stream_cb(AutomationStep(step.phase, rcmd), emit)
                    )
                    r_finished = time.time()
                    r_ok = r_code == 0
                    r_item = CommandExecution(
                        phase=step.phase,
                        command=rcmd,
                        started_at=r_started,
                        finished_at=r_finished,
                        stdout=r_out,
                        stderr=r_err,
                        exit_code=r_code,
                        attempt=attempt,
                        ok=r_ok,
                        kind="repair",
                    )
                    run.executions.append(asdict(r_item))
                    save_run(run)
                if not repair.retry_original:
                    return True

        emit(f"失败(多轮尝试后仍未成功): {step.command}")
        return False

    def _stream_cb(self, step: AutomationStep, emit: Callable[[str], None]) -> Callable[[str, str], None]:
        def _cb(out: str, err: str) -> None:
            chunk = f"{out}{err}"
            if not chunk:
                return
            chunk = chunk[-2000:]
            msg = f"执行: {step.command}\n{chunk}"
            emit(msg)

        return _cb
