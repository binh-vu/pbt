<h1 align="center">PBT</h1>

<div align="center">
<b>pbt</b> — A build tool for multiple Python projects in a single repository
    
![PyPI](https://img.shields.io/pypi/v/pbt)
![Python](https://img.shields.io/badge/python-v3.8+-blue.svg)
[![GitHub Issues](https://img.shields.io/github/issues/binh-vu/pbt.svg)](https://github.com/binh-vu/pbt/issues)
![Contributions welcome](https://img.shields.io/badge/contributions-welcome-orange.svg)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

</div>

## Introduction

Having all packages in the same repository make it much easier to develop, share, reuse, and refactor code. Building and publishing the packages should not be done manually because it is time-consuming and may be frustrated if the projects are depending on each other. [pbt](https://github.com/binh-vu/pbt) is a tool designed to help make the process easier and faster. It supports building, installing, and updating versions of your packages and their dependencies consistently. It also provides utility commands to help you work with your packages in multi-repositories as if you are working with a monorepo.

## Installation

```bash
pip install -U pbt
```

## Usage

Note: currently, [pbt](https://github.com/binh-vu/pbt) supports Python packages configured with Poetry (an awesome dependency management that you should consider using).

Assuming that you organized your packages to different sub-folders, each has their own project configuration file (e.g., `pyproject.toml`). You can run the following commands in the root directory (containing your projects). Note: [pbt](https://github.com/binh-vu/pbt) will discover the project based on the project name in its configuration file not the folder name.

You can also discover the list of commands by running `pbt --help`. Many commands have an option `--cwd` to override the current working directory.

1. **List all packages in the current project, and their dependencies if required**

```bash
pbt list [-d]
```

- `-d`, `--dev`: Whether to print to the local (inter-) dependencies

2. **Create virtual environment of a package and install its dependencies**

```bash
pbt install [-d] [-v] [-p <package>]
```

- `-d`: also install dev-dependencies of the package
- `-v`: verbose
- `-p`: specify the package we want to build, if empty build all packages.

If you have encounter some errors during the installation, you can checkout the `pyproject.failed.toml` file that is generated by pbt in `./cache/<package>` folder (relative to your current working directory). For example, on M1 chip, if your python version is `^3.8`, you can't use the newer scipy (e.g., >1.8 as it requires python `<3.11`), poetry lock chooses to use an old version `1.6.0`, which typically can't build on M1 due to no pre-built numpy for it.

3. **Update all package inter-dependencies**

```bash
pbt update
```

4. **Clean packages' build & lock files**

```bash
pbt clean [-p <package>]
```

- `-p`: specify the package we want to build, if empty build all packages.

6. **Git clone a multi-repository project**

```bash
pbt git clone --repo <repo_url>
```

Clone a repository and check out all of its submodules to their correct branches that we were using last time.

7. **Git update a multi-repository project**

```bash
pbt git update
```

Pull latest changes from the repository, and check out all of its submodules to their correct branches.
