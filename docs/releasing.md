# Creating a release

The release script reads the version from `engine/data/version.txt`, asks which game templates to build, whether to build editor packages, and whether to attach a starter-project Android APK. It uses Git only; no GitHub CLI is needed.

From the repository root, run:

```powershell
python .\tools\release.py
```

Each template selection defaults to **yes**. The editor selection defaults to **yes** and builds Windows, Linux, and macOS editor packages. The Android APK selection defaults to **no**; when enabled, GitHub Actions builds it from a fresh Pygbag build of the current source. If the worktree has changes, the script shows them and asks before staging and committing all tracked and untracked files. Review that list before accepting. A clean worktree is tagged at its current commit.

The script pushes the current branch, then creates and pushes an annotated `v<version>` tag containing the selections. That tag starts the single GitHub Actions workflow, which builds the selected Windows, Linux, macOS, and/or web templates and attaches them to the GitHub release. When editor builds are selected, each editor ZIP contains only the templates selected for that release, plus the source files and bundled Pygbag package needed to create a fresh Android web build later. The APK build requires Node.js, Java, and Android SDK tools on the CI runner.

To see the planned Git actions without committing, tagging, or pushing:

```powershell
python .\tools\release.py --dry-run
```

The dry run still checks the version, branch, remote, and current worktree and asks for the same selections. If a local or remote `v<version>` tag already exists, update `engine/data/version.txt` before creating another release.

Install the combined build dependencies locally with `python -m pip install -r requirements.txt` if needed. The web template build also needs `ffmpeg` available on `PATH`; GitHub Actions installs it automatically. While building the web template, the script downloads and bundles the Pygbag and BrowserFS runtime assets. The resulting web export serves these assets locally at runtime, without CDN requests.
