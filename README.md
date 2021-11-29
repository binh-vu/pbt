<h1 align="center">PBT</h1>

<div align="center">
<b>pbt</b> — a build tool for multi-projects that leverages package registries (pypi, npmjs, etc.).
    
![PyPI](https://img.shields.io/pypi/v/pbt)
![Python](https://img.shields.io/badge/python-v3.7+-blue.svg)
[![GitHub Issues](https://img.shields.io/github/issues/binh-vu/pbt.svg)](https://github.com/binh-vu/pbt/issues)
![Contributions welcome](https://img.shields.io/badge/contributions-welcome-orange.svg)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

</div>

## Introduction

Having all projects in the same repository make it much easier to develop, share, reuse, and refactor code. Building and publishing the projects should not be done manually because it is time-consuming and may be frustrated if the projects are depending on each other. pbt is a tool designed to help make the process easier and faster. It supports building, installing, and updating versions of your projects and their dependencies consistently. It also provides utility commands to help you work with your projects in multi-repositories as if you are working with a monorepo.

## Installation

```bash
pip install -U pab  # not pbt
```

## Usage

Note: currently, **pbt** supports Python projects configured with Poetry (an awesome dependency management that you should consider using).

1. **Installing, cleaning, updating and publishing your projects**

Assuming that you organized your projects as different sub-folders, each has their own project configuration file. 
In the root directory (containing your projects), you can run `install` to install a specific project

```bash
pbt install -p <project> [-e] [-d] [-v]
```
