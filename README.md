# generic git release script

The script performs a git release of a project

The Release process is very simple, it merges a development branch (usually called 'master' or 'dev') to the release
branch (usually called 'release'). After the merge the release branch is tagged with the new version number.

![release process](doc/release.png)

A changelog can be created using github PullRequests merged since last release.

## Invocation

For any of the 2 ways documented below, using python 3 is required (3.6 and 3.7 are working).\
It is also advised to create a dedicated python virtualenv to avoid system-wise pip install.\
Cloning repository is mandatory (pip package available online is deprecated).

### Recommended way

> Installation and run.

In the dedicated python 3 virtualenv, inside repository:

```bash
python setup.py install            # will install commands in venv (dependencies included)
githubflow_release --help          # invoke "releaser"
githubflow_get_new_version --help  # invoke "new version number processing"
```

### Debug way

> Simple python command.

In the dedicated python 3 virtualenv, inside repository:

```bash
pip install -r requirements.txt                  # install dependencies only
python githubflow_release/run.py --help          # invoke "releaser"
python githubflow_release/new_version.py --help  # invoke "new version number processing"
```

## Script usage

To know all the parameters use the --help option.

Some projects may need to keep consistency for some options: you can create a `gitflow_release.yml` in the root
directory of your project to give some default values.
The values are overridden if given in the command lines.
  
Example of `gitflow_release.yml`:
  
```yml
# configuration of my project release
# used by https://github.com/hove-io/githubflow_release
github_repo: hove-io/my_project
base_branch: master
generate_debian_changelog: False
excluded_pr_tag: [hotfix, not_in_changelog, my_tag]
```

Usage:

Create new release (in the dedicated virtualenv):

```bash
cd my_project;
githubflow_release --release-type major|minor --github-repo User/repo_name --project-path /path/repo_name/ --remote-name origin
```

You can automatically push the release branch master (--base-branch) and tags by adding the parameter --auto-push (in the dedicated virtualenv):

```bash
cd my_project;
githubflow_release --release-type major|minor --github-repo User/repo_name --project-path /path/repo_name/ --remote-name origin --auto-push
```

Get new version (in the dedicated virtualenv):

```bash
cd my_project;
githubflow_get_new_version --release-type major|minor|hotfix --project-path /path/repo_name/ --remote-name origin
```

Example for [navitia](https://github.com/CanalTP/navitia) repo (actual version 10.4.0):

```bash
cd my_project
githubflow_get_new_version --release-type minor  --project-path /workspace/navitia/ --remote-name origin
```

Output:
```bash
10.5.0
```

Github might be limiting your access to their API. If so you need to provide some github credential.

If so either generate a custom token (the best way) or use your own github password (DO NOT PUT it into
your configuration file):

```bash
githubflow_release --release-type minor --github-user 'my_github_login' --github-token 'my_github_custom_token_or_password'
```
