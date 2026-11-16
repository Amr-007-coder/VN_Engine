# Creating a release

The release script reads the version from `engine/data/version.txt`, asks which game templates to build, whether to build editor packages, and whether to attach a starter-project Android APK. It uses Git only; no GitHub CLI is needed.

From the repository root, run:

```powershell
python .\tools\release.py
```

Each template selection defaults to **yes**. The editor selection defaults to **yes** and builds Windows, Linux, and macOS editor packages. The Android APK selection defaults to **no**; when enabled, GitHub Actions builds it from a fresh project-specific Web archive using the Web runtime template built for that release. If the worktree has changes, the script shows them and asks before staging and committing all tracked and untracked files. Review that list before accepting. A clean worktree is tagged at its current commit.

The script pushes the current branch, then creates and pushes an annotated `v<version>` tag containing the selections. That tag starts the single GitHub Actions workflow, which builds the selected Windows, Linux, macOS, and/or web templates and attaches the selected templates to the GitHub release. When editor builds are selected, each editor ZIP also contains the current Web runtime template for browser and Android exports. The workflow builds it as an internal dependency when Web was not selected as a release asset. The optional starter APK uses the same template and requires Node.js, Java, and Android SDK tools on the CI runner.

To see the planned Git actions without committing, tagging, or pushing:

```powershell
python .\tools\release.py --dry-run
```

The dry run still checks the version, branch, remote, and current worktree and asks for the same selections. If a local or remote `v<version>` tag already exists, update `engine/data/version.txt` before creating another release.

Install the combined build dependencies locally with `python -m pip install -r requirements.txt` if needed. The web template build also needs `ffmpeg` available on `PATH`; GitHub Actions installs it automatically. While building the web template, the script downloads and bundles the Pygbag and BrowserFS runtime assets. The resulting web export serves these assets locally at runtime, without CDN requests.
