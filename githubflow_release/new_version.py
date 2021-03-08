"""Github flow release

Usage:
  githubflow_get_new_version (--release-type <type>)
                     [--project-path <DIR>]
                     [--remote-name <name>]
                     [--github-user <user>]
                     [--github-token <token>]
  githubflow_get_new_version (-h | --help)
  githubflow_get_new_version --version

Options:
  -h --help                 Show this screen.
  --version                 Show version.
  --project-path <DIR>      Project path   [default: .]
  --release-type <type>     Release type   [default: minor]
  --remote-name <name>      Remote name    [default: upstream]
  --github-user <user>      Github user
  --github-token <token>    Github token
"""
from docopt import docopt
from githubflow_release.release import new_version


def main():
    arguments = docopt(__doc__, version='Github Flow Release 1.0.0')

    print(new_version(project_path=arguments['--project-path'],
                       release_type=arguments['--release-type'],
                       remote_name=arguments['--remote-name'],
                       github_user=arguments['--github-user'],
                       github_token=arguments['--github-token']))


if __name__ == '__main__':
    main()
