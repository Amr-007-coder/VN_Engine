# Creating a release

The release script reads the version from `engine/data/version.txt` and asks which game templates and editor packages to build. It uses Git only; no GitHub CLI is needed.

From the repository root, run:

```powershell
python .\tools\release.py
```

Each template selection defaults to **yes**. The editor selection defaults to **yes** and builds Windows, Linux, and macOS editor packages. The selected templates are built exactly as chosen, regardless of whether editor packages are included. Editor packages do not contain runtime templates. If the worktree has changes, the script shows them and asks before staging and committing all tracked and untracked files. Review that list before accepting. A clean worktree is tagged at its current commit.

The script pushes the current branch, then creates and pushes an annotated `v<version>` tag containing the selections. That tag starts the GitHub Actions workflow, which builds the selected templates and, independently, the editor packages when selected. The workflow attaches the resulting artifacts and a ready-to-use starter-project ZIP to the GitHub release. If `Documents/VN Engine Projects/My Visual Novel` does not exist when the editor starts without another project selected, the editor installs the released starter project there; existing files are preserved. Editor users download runtime templates from releases on demand, and the editor cache stores each downloaded template for future use. The Android export dialog lists releases with a Web template, recommends the editor's matching version, and fetches the selected release's engine source temporarily.

To see the planned Git actions without committing, tagging, or pushing:

```powershell
python .\tools\release.py --dry-run
```

The dry run still checks the version, branch, remote, and current worktree and asks for the same selections. If a local or remote `v<version>` tag already exists, update `engine/data/version.txt` before creating another release.

Install the combined build dependencies locally with `python -m pip install -r requirements.txt` if needed. The web template build also needs `ffmpeg` available on `PATH`; GitHub Actions installs it automatically. While building the web template, the script downloads and bundles the Pygbag and BrowserFS runtime assets. The resulting web export serves these assets locally at runtime, without CDN requests.
