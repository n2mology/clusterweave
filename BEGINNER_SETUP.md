# Beginner Setup

`ClusterWeave` is a Linux/WSL workflow. If you are brand new to GitHub or command-line tools, the easiest path is:

1. Use Windows with WSL2 and Ubuntu.
2. Open the project in VS Code.
3. Run the copy/paste commands below inside Ubuntu.

If you already use Linux directly, skip the WSL-specific steps and use the same Linux commands.

## Official Setup Links

- WSL install guide: https://learn.microsoft.com/en-us/windows/wsl/install
- VS Code download: https://code.visualstudio.com/download
- VS Code with WSL: https://code.visualstudio.com/docs/remote/wsl
- Git download page: https://git-scm.com/downloads.html
- GitHub account setup: https://docs.github.com/en/get-started/start-your-journey/creating-an-account-on-github
- GitHub cloning guide: https://docs.github.com/articles/cloning-a-repository?platform=mac&tool=desktop
- Apptainer installation guide: https://apptainer.org/docs/admin/main/installation.html

## Recommended Path: Windows + WSL + VS Code

### 1. Install WSL and Ubuntu

Open PowerShell as Administrator and run:

```powershell
wsl --install
```

Restart your computer if prompted.

When Ubuntu opens for the first time, create your Linux username and password.

### 2. Install VS Code

Install VS Code from the official download page:

- https://code.visualstudio.com/download

Then install the Microsoft WSL extension in VS Code:

- https://code.visualstudio.com/docs/remote/wsl

### 3. Open Ubuntu and install the basic tools

Run these commands inside Ubuntu:

```bash
sudo apt update
sudo apt install -y git curl python3 python3-venv python3-pip software-properties-common
sudo add-apt-repository -y ppa:apptainer/ppa
sudo apt update
sudo apt install -y apptainer
```

These commands install:

- `git` for getting the repository
- `python3` for the helper scripts
- `apptainer` for the containerized workflow stages

If `apptainer` does not install cleanly on your system, follow the official Apptainer guide:

- https://apptainer.org/docs/admin/main/installation.html

### 4. Download the ClusterWeave repository

If you are comfortable with Git, clone the repository:

```bash
cd ~
git clone https://github.com/n2mology/clusterweave.git
cd clusterweave
```

If you are not ready to use `git clone`, you can also use the repository page on GitHub and choose `Code -> Download ZIP`, then unzip it and open the `clusterweave` folder in Ubuntu or VS Code.

### 5. Open the project in VS Code

Inside Ubuntu, run:

```bash
code .
```

If `code` is not recognized yet, open VS Code normally, then use `File -> Open Folder` and open your `clusterweave` folder.

### 6. Start your first ClusterWeave project

The first manual input is your accession list.

Create a project-specific accession file:

```bash
cp accessions.txt accessions_my_project.txt
```

Edit it in VS Code and place one accession per line.

Then run:

```bash
bash install_ncbi_cli.sh
PROJECT_NAME=my_project ACCESSIONS_FILE=$PWD/accessions_my_project.txt bash prepare_genomes_from_accessions.sh
PROJECT_NAME=my_project bash run_clusterweave.sh
```

This creates project-specific folders here:

- `data/genomes/fungi/my_project/`
- `data/results/my_project/`

## Running More Than One Project

To keep multiple studies separate inside one `ClusterWeave` clone, use a different `PROJECT_NAME` for each one.

Example:

```bash
PROJECT_NAME=project_alpha ACCESSIONS_FILE=$PWD/accessions_project_alpha.txt bash prepare_genomes_from_accessions.sh
PROJECT_NAME=project_alpha bash run_clusterweave.sh

PROJECT_NAME=project_beta ACCESSIONS_FILE=$PWD/accessions_project_beta.txt bash prepare_genomes_from_accessions.sh
PROJECT_NAME=project_beta bash run_clusterweave.sh
```

You do not need a second copy of the repository for each study.

## Direct Linux Setup

If you are already on Linux:

1. Install `git`, `python3`, and `apptainer` with your system package manager.
2. Clone or download the `ClusterWeave` repository.
3. Run the same commands shown above.

If your Linux distribution is not Ubuntu, use the official Apptainer installation guide for your distribution:

- https://apptainer.org/docs/admin/main/installation.html

## Most Important Things To Remember

- `accessions.txt` or `ACCESSIONS_FILE` is the first real user input.
- `PROJECT_NAME` is what keeps one project separate from another.
- `TARGET_GENOME` is optional. You only need it for target-focused summary or clinker outputs.
- `run_clusterweave.sh` is the main end-to-end entrypoint.

## If Something Fails

- If `wsl` is not recognized, revisit the Microsoft WSL install guide.
- If `apptainer` is missing, install it before running the main workflow.
- If the repository URL is not public yet, use a ZIP download or a local copy from the maintainer.
- If you want a shorter technical version after you are comfortable, use [README.md](README.md) and [docs/INSTALL.md](docs/INSTALL.md).
