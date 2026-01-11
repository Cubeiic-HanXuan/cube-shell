# -*- coding: utf-8 -*-
import shlex
from PySide6.QtCore import QThread, Signal


class CompressThread(QThread):
    finished_sig = Signal(bool, str)  # success, message

    def __init__(self, ssh_conn, files, output_name, format_type, pwd):
        """
        :param ssh_conn: SSH connection object
        :param files: List of relative filenames to compress
        :param output_name: Output filename (e.g. archive.tar.gz)
        :param format_type: ".tar.gz" or ".zip"
        :param pwd: Current remote directory
        """
        super().__init__()
        self.ssh_conn = ssh_conn
        self.files = files
        self.output_name = output_name
        self.format_type = format_type
        self.pwd = pwd

    def run(self):
        try:
            if getattr(self.ssh_conn, "is_local", False):
                # 本机压缩：
                # - 不依赖系统 tar/zip 命令，避免不同平台命令缺失/参数差异
                # - 直接使用 Python 标准库 tarfile/zipfile
                # - self.files 仍是“相对当前目录”的文件名，保持与远程一致
                import os
                import tarfile
                import zipfile

                base_dir = os.path.expanduser(self.pwd)
                out_path = os.path.join(base_dir, self.output_name)

                def _iter_paths():
                    for rel in self.files:
                        yield os.path.join(base_dir, rel), rel

                if self.format_type == ".tar.gz":
                    with tarfile.open(out_path, "w:gz") as tf:
                        for abs_p, rel_p in _iter_paths():
                            if self.isInterruptionRequested():
                                return
                            tf.add(abs_p, arcname=rel_p, recursive=True)
                    self.finished_sig.emit(True, "Compression task finished")
                    return

                if self.format_type == ".zip":
                    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                        for abs_p, rel_p in _iter_paths():
                            if self.isInterruptionRequested():
                                return
                            if os.path.isdir(abs_p):
                                # 目录需要递归 walk，把目录下的所有文件逐个加入 zip
                                # arcname 使用相对 base_dir 的路径，保证解压后目录结构一致
                                for root, _dirs, files in os.walk(abs_p):
                                    if self.isInterruptionRequested():
                                        return
                                    for fn in files:
                                        fp = os.path.join(root, fn)
                                        arc = os.path.relpath(fp, base_dir)
                                        zf.write(fp, arcname=arc)
                            else:
                                zf.write(abs_p, arcname=rel_p)
                    self.finished_sig.emit(True, "Compression task finished")
                    return

                self.finished_sig.emit(False, f"Unsupported format: {self.format_type}")
                return

            # 1. Escape filenames to handle spaces/special chars
            quoted_files = [shlex.quote(f) for f in self.files]
            files_str = ' '.join(quoted_files)

            # 2. Construct command
            cmd = ""
            pwd_quoted = shlex.quote(self.pwd)
            output_quoted = shlex.quote(self.output_name)

            if self.format_type == ".tar.gz":
                cmd = f"cd {pwd_quoted} && tar -czf {output_quoted} {files_str}"
            elif self.format_type == ".zip":
                # Check if zip is installed, if not, try to install it or warn user
                # We can't easily install it non-interactively across all distros here reliably without sudo.
                # So we check first.
                check_cmd = "command -v zip >/dev/null 2>&1"
                # Executing check synchronously
                stdin, stdout, stderr = self.ssh_conn.conn.exec_command(check_cmd)
                if stdout.channel.recv_exit_status() != 0:
                     self.finished_sig.emit(False, "zip command not found. Please install zip on the server (e.g., 'apt install zip' or 'yum install zip').")
                     return
                
                cmd = f"cd {pwd_quoted} && zip -r {output_quoted} {files_str}"
            else:
                self.finished_sig.emit(False, f"Unsupported format: {self.format_type}")
                return

            # 3. Execute command using paramiko directly to avoid timeout limits
            # ssh_conn.conn is the paramiko SSHClient
            stdin, stdout, stderr = self.ssh_conn.conn.exec_command(cmd)

            # Wait for completion and support cancellation
            while not stdout.channel.exit_status_ready():
                if self.isInterruptionRequested():
                    # Attempt to close channel to stop
                    stdout.channel.close()
                    return
                self.msleep(100)

            exit_status = stdout.channel.recv_exit_status()

            if exit_status == 0:
                self.finished_sig.emit(True, "Compression task finished")
            else:
                error_msg = stderr.read().decode('utf-8', errors='ignore')
                self.finished_sig.emit(False, error_msg or "Unknown error")

        except Exception as e:
            self.finished_sig.emit(False, str(e))


class DecompressThread(QThread):
    finished_sig = Signal(bool, str)  # success, message

    def __init__(self, ssh_conn, files, pwd):
        """
        :param ssh_conn: SSH connection object
        :param files: List of filenames to decompress
        :param pwd: Current remote directory (destination)
        """
        super().__init__()
        self.ssh_conn = ssh_conn
        self.files = files
        self.pwd = pwd

    def run(self):
        try:
            if getattr(self.ssh_conn, "is_local", False):
                # 本机解压：
                # - 使用标准库 zipfile/tarfile
                # - 解压属于高风险操作：压缩包可能包含“../”路径或绝对路径，导致目录穿越写文件（zip-slip/tar-slip）
                # - 这里在 extractall 前做路径校验：任何条目解出来不在 dest_dir 内则拒绝执行
                import os
                import tarfile
                import zipfile

                dest_dir = os.path.expanduser(self.pwd)

                def _safe_join(base: str, *paths: str) -> str:
                    return os.path.abspath(os.path.join(base, *paths))

                def _ensure_within_base(base: str, target: str) -> bool:
                    base_abs = os.path.abspath(base)
                    target_abs = os.path.abspath(target)
                    return target_abs == base_abs or target_abs.startswith(base_abs + os.sep)

                for filename in self.files:
                    if self.isInterruptionRequested():
                        return

                    fp = os.path.expanduser(filename)
                    if fp.endswith(".zip"):
                        with zipfile.ZipFile(fp, "r") as zf:
                            # zip-slip 防护：校验每个 entry 的落盘路径都在 dest_dir 内
                            for info in zf.infolist():
                                out_path = _safe_join(dest_dir, info.filename)
                                if not _ensure_within_base(dest_dir, out_path):
                                    self.finished_sig.emit(False, f"Unsafe zip entry: {info.filename}")
                                    return
                            zf.extractall(dest_dir)
                    elif fp.endswith(".tar.gz") or fp.endswith(".tgz"):
                        with tarfile.open(fp, "r:gz") as tf:
                            # tar-slip 防护：校验每个 member 的落盘路径都在 dest_dir 内
                            for member in tf.getmembers():
                                out_path = _safe_join(dest_dir, member.name)
                                if not _ensure_within_base(dest_dir, out_path):
                                    self.finished_sig.emit(False, f"Unsafe tar entry: {member.name}")
                                    return
                            tf.extractall(dest_dir)
                    elif fp.endswith(".tar"):
                        with tarfile.open(fp, "r:") as tf:
                            # tar-slip 防护：校验每个 member 的落盘路径都在 dest_dir 内
                            for member in tf.getmembers():
                                out_path = _safe_join(dest_dir, member.name)
                                if not _ensure_within_base(dest_dir, out_path):
                                    self.finished_sig.emit(False, f"Unsafe tar entry: {member.name}")
                                    return
                            tf.extractall(dest_dir)
                    else:
                        self.finished_sig.emit(False, f"Unsupported archive format: {filename}")
                        return

                self.finished_sig.emit(True, "Decompression task finished")
                return

            pwd_quoted = shlex.quote(self.pwd)
            
            for filename in self.files:
                # Check cancellation before each file
                if self.isInterruptionRequested():
                    return

                file_quoted = shlex.quote(filename)
                cmd = ""
                
                # Determine command based on extension
                if filename.endswith(".zip"):
                    # Check for zip/unzip command
                    check_cmd = "command -v unzip >/dev/null 2>&1"
                    stdin, stdout, stderr = self.ssh_conn.conn.exec_command(check_cmd)
                    if stdout.channel.recv_exit_status() != 0:
                         self.finished_sig.emit(False, "unzip command not found. Please install unzip on the server.")
                         return
                    # -o: overwrite without prompting
                    # -d: destination directory
                    cmd = f"unzip -o {file_quoted} -d {pwd_quoted}"
                elif filename.endswith(".tar.gz") or filename.endswith(".tgz"):
                    cmd = f"tar -xzvf {file_quoted} -C {pwd_quoted}"
                elif filename.endswith(".tar"):
                    cmd = f"tar -xvf {file_quoted} -C {pwd_quoted}"
                else:
                    # Skip unknown formats or try tar as fallback? 
                    # For now, treat as error or skip
                    self.finished_sig.emit(False, f"Unsupported archive format: {filename}")
                    return

                # Execute
                stdin, stdout, stderr = self.ssh_conn.conn.exec_command(cmd)
                
                # Wait loop
                while not stdout.channel.exit_status_ready():
                    if self.isInterruptionRequested():
                        stdout.channel.close()
                        return
                    self.msleep(100)
                
                exit_status = stdout.channel.recv_exit_status()
                if exit_status != 0:
                    error_msg = stderr.read().decode('utf-8', errors='ignore')
                    self.finished_sig.emit(False, f"Failed to extract {filename}: {error_msg}")
                    return

            self.finished_sig.emit(True, "Decompression task finished")

        except Exception as e:
            self.finished_sig.emit(False, str(e))
