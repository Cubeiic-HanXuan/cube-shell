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
