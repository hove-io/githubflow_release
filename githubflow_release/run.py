"""Github flow release

Usage:
  githubflow_release (--release-type <type>)
                     (--github-repo <repo>)
                     [--defaults-file=FILE]
                     [--project-path=DIR]
                     [--remote-name=<name>]
                     [--github-user=<user>]
                     [--github-token=<token>]
                     [--base-branch=<branch>]
                     [--debian-changelog]
                     [--excluded-pr-tag <tags>]...
                     [--hotfix-pr-id <pr-id>]...
                     [--dry-run]
  githubflow_release (-h | --help)
  githubflow_release --version

Options:
  -h --help                 Show this screen.
  --version                 Show version.
  --defaults-file=FILE      Defaults file  [default: gitflow_release.yml]
  --project-path=DIR        Project path   [default: .]
  --release-type=<type>     Release type   [default: minor]
  --remote-name=<name>      Remote name    [default: upstream]
  --github-repo=<repo>      Github repo (User/Repository)
  --github-user=<user>      Github user
  --github-token=<token>    Github token
  --base-branch=<branch>    Base branch  [default: master]
  --debian-changelog        Generate debian_changelog
  --excluded-pr-tag=<tags>  PR will be excluded if labelled with the given tag [default: hotfix not_in_changelog]
  --hotfix-pr-id=<pr-id>    Hotfix PR ID
  --dry-run                 Display changelog without doing the release
"""
from docopt import docopt
from githubflow_release.release import release


def main():
    arguments = docopt(__doc__, version='Github Flow Release 1.0.0')

    release(project_path=arguments['--project-path'],
            release_type=arguments['--release-type'],
            remote_name=arguments['--remote-name'],
            github_repo=arguments['--github-repo'],
            github_user=arguments['--github-user'],
            github_token=arguments['--github-token'],
            base_branch=arguments['--base-branch'],
            generate_debian_changelog=arguments['--debian-changelog'],
            hotfix_pr_ids=arguments['--hotfix-pr-id'],
            excluded_pr_tag=arguments['--excluded-pr-tag'],
            dry_run=arguments['--dry-run'])

if __name__ == '__main__':
    main()
