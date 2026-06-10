<div align="center">
<a href="https://github.com/Cubeiic-HanXuan/cube-shell/">
<img src="docs/images/docs-log.png" width="350" alt="ragflow logo">
</a>
</div>

<p align="center">
  <a href="./README.md">简体中文</a> |
  <a href="./README.en.md">English</a>
</p>

![Python-badge] ![License-badge] ![release-badge] ![download-badge] ![download-latest]

## cube-shell

#### Introduction

`cube-shell` is a remote operations and management tool for Linux servers. It can replace tools like Xshell, XSftp, and
MobaXterm for server management. `cube-shell` is simple yet powerful. Most SSH client tools on the market are bloated
with unnecessary menus and overly complex UIs, making them unfriendly to first-time users.

`cube-shell` was designed with simplicity and practicality in mind — no redundant menus to get in your way. Installation
is just as easy: simply extract and run, no installer required.

### What can cube-shell do?

**1. Device List**

![](docs/images/1.png)

- Add configuration
- Edit configuration
- Delete configuration

**2. Quick Menu Bar**

All menu items support keyboard shortcuts
![](docs/images/2.png)

- Add configuration
- Add SSH tunnel
- Export device configurations
- Import device configurations

**3. SFTP File Operations**

![](docs/images/3.png)

- Download files (batch download supported)
- Upload files (batch upload supported)
- Edit files
- Create folders
- Create files
- Refresh (new feature)
- Delete files and folders (batch delete supported)

**4. SSH Remote Terminal**

![](docs/images/4.png)

- Full terminal operations
- Multi-tab support (including multiple tabs to the same server)
- Drag-and-drop tab reordering
- Copy, paste, and clear screen
- Syntax highlighting
- Terminal theme switching
- Command-line auto-completion
- Linked navigation between terminal tabs and SFTP file panel

**5. Theme Switching**

`cube-shell 1.5.x` features an optimized modern IDE-style theme system, supporting two themes: dark and light.
![](docs/images/5.png)
![](docs/images/6.png)

**6. Status Bar**

![](docs/images/7.png)

- CPU monitoring
- Memory monitoring
- Disk monitoring
- Network upload speed
- Network download speed
- Operating system
- Kernel
- Kernel version
- Process management (quick kill, process search)

**7. Extended Features**

- SSH Tunneling
  ![](docs/images/8.png)
- Intranet Penetration (NAT Traversal)
  ![](docs/images/9.png)
- Container Management
  ![](docs/images/10.png)
- Common Containers
  ![](docs/images/11.png)

### Software Architecture

`cube-shell` is primarily developed in Python.

Key technologies used:
| Name | Version | Description |
| --- | --- | --- |
| Python | 3.12.3 | |
| PySide6 | 6.7.2 | Python bindings for C++ Qt, supporting cross-platform development |
| paramiko | 3.4.0 | Python library for SSH and SFTP protocol operations |
| Pygments | 2.18.0 | Popular Python library for code syntax highlighting |
| pyqtdarktheme | 2.1.0 | Modern theme library for Qt |
| deepdiff | 8.0.1 | Python deep file comparison library |
| openai | 2.37.0 | AI large language model SDK |
| pyte | 0.8.2 | Linux terminal data stream framework |
| frp | 0.61.0 | Intranet penetration toolkit |

**Icons are primarily sourced from:**

`https://icons8.com/icons/color`

`https://www.iconfont.cn/`

#### Installation

You can download the latest release from [Releases](https://github.com/Cubeiic-HanXuan/cube-shell/releases), or clone
the source code and build it yourself.

`cube-shell` uses [Nuitka](https://nuitka.net/) to compile Python source code into native binaries, achieving
approximately 50% performance improvement and 40% reduction in package size.

##### Prerequisites

| Requirement          | Details                                                                                                     |
|----------------------|-------------------------------------------------------------------------------------------------------------|
| Python               | **3.12** or higher                                                                                          |
| Git                  | For cloning the repository                                                                                  |
| C Compiler Toolchain | Windows requires MinGW64 or MSVC; macOS requires Xcode Command Line Tools; Linux requires `build-essential` |
| Disk Space           | At least **2 GB** recommended (compilation generates a large number of intermediate files)                  |

##### Common Steps (All Platforms)

1. Clone the repository

```bash
git clone https://github.com/Cubeiic-HanXuan/cube-shell.git
cd cube-shell
```

2. Create and activate a Python virtual environment

```bash
python3 -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
```

3. Install project dependencies

```bash
pip install -r requirements.txt
```

##### Building for Windows

> Requires **MinGW64** or **MSVC** compiler, and [Inno Setup](https://jrsoftware.org/isinfo.php) (for packaging the
> installer).

1. Compile into a standalone executable

```bash
build-exe.bat
```

The script will automatically install Nuitka and compile the project. Output will be in the `deploy\cube-shell.dist\`
directory.

2. Package as an EXE installer (optional)

```bash
deploy-install.bat
```

This generates a Windows installer (`.exe`) that can be distributed to users for direct installation.

##### Building for macOS

> Requires **Xcode Command Line Tools** and [create-dmg](https://github.com/create-dmg/create-dmg) (the script will
> automatically install it via Homebrew).

1. Grant execution permission and run the script

```bash
chmod +x app.sh
./app.sh
```

The script will automatically handle Nuitka compilation, resource copying, and DMG packaging.

2. Build output

| File                    | Description                                                                            |
|-------------------------|----------------------------------------------------------------------------------------|
| `deploy/cube-shell.dmg` | macOS disk image installer — double-click to mount, then drag into Applications to use |

##### Building for Linux (Ubuntu/Debian)

> For Ubuntu / Debian-based distributions. The script uses `apt-get` to automatically install required system
> dependencies.

1. Grant execution permission and run the script

```bash
chmod +x build-linux.sh
./build-linux.sh
```

The script will automatically install system dependencies (`patchelf`, `ccache`, Qt runtime libraries, etc.), compile
the application, and generate desktop entry files and launch scripts.

2. Build output

| File                                        | Description                                                                                                 |
|---------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| `deploy/cube-shell.dist/`                   | Complete application directory — run `./cube-shell.sh` to launch directly                                   |
| `deploy/cube-shell-linux-x86_64.tar.gz`     | Compressed release package, can be distributed and extracted on other machines                              |
| `deploy/cube-shell.dist/cube-shell.desktop` | Desktop shortcut file — copy to `~/.local/share/applications/` to make it available in the application menu |

#### Contributing

Contributions are welcome! We appreciate your help in making cube-shell better.

1. Fork this repository
2. Create a new Feat_xxx branch
3. Commit your code
4. Create a Pull Request

#### Video Tutorials

[cube-shell-video](https://mp.weixin.qq.com/s/ntDuDipnCqN4v2Y4Urzo6w)

#### Join the Community

<div>
<img src="docs/images/QQ.png" width="185" alt="follow on QQ">
<img src="docs/images/weixin.png" width="554" alt="follow on Weixin">
<img src="docs/images/ZFB.png" width="150" alt="维护不易，觉得不错的可以赞助一下">
<img src="docs/images/wei_zf.png" width="175" alt="维护不易，觉得不错的可以赞助一下">
</div>


[License-link]: https://github.com/Cubeiic-HanXuan/cube-shell/blob/master/LICENSE "License"
[License-badge]: https://img.shields.io/badge/License-LGPL%20v3-blue.svg "License"
[Python-link]: https://www.python.org/downloads/ "Python"
[Python-badge]: https://img.shields.io/badge/python-3.12+-blue.svg "Python"

[release-link]: https://github.com/Cubeiic-HanXuan/cube-shell/releases "Release status"
[release-link]: https://github.com/Cubeiic-HanXuan/cube-shell/releases "Release status"
[release-badge]: https://img.shields.io/github/release/Cubeiic-HanXuan/cube-shell.svg?style=flat-square "Release status"
[download-link]: https://github.com/Cubeiic-HanXuan/cube-shell/releases/latest "Download status"
[download-badge]: https://img.shields.io/github/downloads/Cubeiic-HanXuan/cube-shell/total.svg "Download status"
[download-latest]: https://img.shields.io/github/downloads/Cubeiic-HanXuan/cube-shell/latest/total.svg "latest status"
