#!/usr/bin/env python

from __future__ import unicode_literals
import argparse
import git
import logging
import os
import requests
import semver
import uuid
from git.exc import GitCommandError

GITHUB_HEADERS = {}
RELEASE_BRANCH = 'release'
DEVELOPMENT_BRANCH = 'master'
GITHUB_API_URL = 'https://api.github.com'


class PullRequest(object):
    def __init__(self, github_api_response):
        self.title = github_api_response['title']
        self.url = github_api_response['html_url']
        self.head_sha1 = github_api_response['head']['sha']
        # we consider that if the pr has a merged_at date, it has been merged
        self.is_merged = github_api_response['merged_at'] is not None
        self.raw_response = github_api_response
        logging.debug(u'pr: {} -- {}'.format(self.title, self.url))
        self._labels = None

    def fetch_labels(self, headers):
        """ call github to fetch the labels of the pr """
        if not self._labels:
            label_query = self.raw_response['_links']['issue']['href'] + '/labels'
            self._labels = [r['name'] for r in requests.get(label_query, headers=headers).json()]
        return self._labels


class ReleaseManager(object):
    def __init__(self, path, release_type, remote_name, github_repo, github_token,
                 excluded_pr_tag, dry_run):
        self.excluded_pr_tag = excluded_pr_tag
        self.release_type = release_type
        self.project_path = path
        self.repo = git.Repo(path)
        self.git = self.repo.git
        self.remote_name = remote_name
        self.github_headers = {'Authorization': 'token ' + github_token} if github_token else {}
        # TODO get the remote repos to call (based on git remote -v ?)
        self.github_repository = github_repo
        self.files_to_commit = []  # if some files are created and need to be commit, they are stored here
        self.dry_run = dry_run

        """ Tag format configuration """
        # TODO a jinja template would be better
        self.tag_header_format = 'Version {version}\n\n'  # can be formated with {version}
        self.tag_pr_line_format = ' * {pr.title}  <{pr.url}>\n'  # can be formated with {pr}
        self.tag_name_format = 'v{version}'  # can be formated with {version}
        self.tag_footer_format = ''

    def release(self):
        logging.info("release {}".format(self.release_type))
        self._update_repository()
        version = self._get_new_version_number()
        logging.info("new tag is {}".format(version))
        changelog = self._generate_changelog(version)
        if (self.dry_run):
            print('Changelog:')
            print(changelog)
            exit(0)

        self._publish(version, changelog)

    def _get_new_version_number(self):
        try:
            self.last_tag = self.git.describe("--tags", abbrev=0)
        except GitCommandError as e:
            logging.debug('impossible to retrieve tags: {}'.format(e))
            logging.warning('impossible to retrieve tags, we assume there is none')
            self.last_tag = '0.0.0'

        # some tags might have a leading 'v', we remove it to get a real semver
        last_tag = self.last_tag.strip('v')
        logging.debug("tag = {}".format(last_tag))
        if self.release_type == 'major':
            return semver.bump_major(last_tag)
        elif self.release_type == 'minor':
            return semver.bump_minor(last_tag)
        elif self.release_type == 'hotfix':
            return semver.bump_patch(last_tag)
        else:
            logging.fatal('{} is not a known release type'.format(self.release_type))
            exit(2)

    def _closed_pr_generator(self):
        # lazy get all closed PR ordered by last updated
        page = 1
        base_branch = RELEASE_BRANCH if self.release_type == 'hotfix' else DEVELOPMENT_BRANCH
        while True:
            query = "{host}/repos/{repo}/pulls?" \
                    "state=closed&base={base_branch}&sort=updated&direction=desc&page={page}"\
                    .format(host=GITHUB_API_URL, repo=self.github_repository,
                            base_branch=base_branch,
                            latest_tag=self.last_tag,
                            page=page)
            logging.debug("query github api: %s", query)
            github_response = requests.get(query, headers=self.github_headers)

            if github_response.status_code != 200:
                message = github_response.json()['message']
                logging.error(u'Impossible to retrieve PR:\n  %s', message)
                return

            closed_pr = github_response.json()
            if not closed_pr:
                logging.debug("Reached end of PR list")
                return

            for pr in closed_pr:
                yield pr

            page += 1

    def _get_merged_pullrequest(self):
        lines = []
        nb_successive_merged_pr = 0
        for raw_pr in self._closed_pr_generator():
            pr = PullRequest(raw_pr)

            # test if PR was merged (not simply closed)
            # and if distant/release contains HEAD of PR
            # (stops after 10 successive merged PR)

            branch = DEVELOPMENT_BRANCH if self.release_type == 'hotfix' else RELEASE_BRANCH

            if pr.is_merged:
                branches = self.git.branch('-r', '--contains', pr.head_sha1) + '\n'
                # adding separators before and after to match only branch name
                release_branch_name = ' {remote}/{release}\n'.format(remote=self.remote_name,
                                                                     release=branch)
                if release_branch_name in branches:
                    nb_successive_merged_pr += 1
                    if nb_successive_merged_pr >= 10:
                        break
                else:
                    # doing the label search as late as possible to save api calls
                    labels = pr.fetch_labels(self.github_headers)
                    has_excluded_label = any(l in self.excluded_pr_tag for l in labels)

                    if not has_excluded_label:
                        lines.append(pr)
                        nb_successive_merged_pr = 0
        return lines

    def _generate_changelog(self, version):
        pullrequests = self._get_merged_pullrequest()

        # TODO we could have a way to save the PR in a file to let the user customize it
        if not pullrequests:
            logging.warning('no changes detected, no release to do')
            exit(0)

        changelog = self.tag_header_format.format(version=version)

        for pr in pullrequests:
            # try:
            changelog += self.tag_pr_line_format.format(pr=pr)
            # except Exception as e:
            #     print(pr)

            changelog += self.tag_footer_format.format(version=version)

        return changelog

    def get_parent_branch(self):
        """ get the branch we want to start working on """
        return DEVELOPMENT_BRANCH if self.release_type in ["major", "minor"] else RELEASE_BRANCH

    def _make_git_release(self, version):
        """
        git branch update
        - a temporary branch is created from the base branch
        - if some files have been added, they are commited
        """
        tmp_name = "release_{version}_{rand}".format(version=version, rand=uuid.uuid4())

        parent_branch = self.get_parent_branch()

        # we then create a new temporary branch
        logging.info("creating temporary release branch {}".format(tmp_name))
        tmp_branch = self.repo.create_head(tmp_name, '{remote}/{parent}'.format(remote=self.remote_name,
                                                                                parent=parent_branch))

        logging.debug("current branch {}".format(self.repo.active_branch))

        if self.files_to_commit:
            for f in self.files_to_commit:
                self.git.add(f)

            self.git.commit(m="Version {}".format(version))

        return tmp_branch

    def tag(self, version, changelog):
        """ tag the git release branch with the version and the changelog """
        tag_name = self.tag_name_format.format(version=version)
        self.repo.create_tag(tag_name, ref=RELEASE_BRANCH, message=changelog)

    def _publish(self, version, pullrequests):
        logging.info("doing release")

        if self.release_type != 'hotfix':
            self.git.checkout(DEVELOPMENT_BRANCH)
            tmp_branch = self._make_git_release(version)

            self.git.checkout(RELEASE_BRANCH)
            self.git.merge(tmp_branch, RELEASE_BRANCH, '--no-ff')

            # we can remove the temporary branch
            logging.info('deleting temporary branch {}'.format(tmp_branch))
            self.repo.delete_head(tmp_branch)
        else:
            self.git.checkout(RELEASE_BRANCH)

        # we tag the release
        self.tag(version, pullrequests)

        # and we merge back the release branch to master/dev (at least for the tag in release)
        self.git.checkout(DEVELOPMENT_BRANCH)
        self.git.merge(RELEASE_BRANCH, DEVELOPMENT_BRANCH, '--no-ff')

        display_push_release_message(self.remote_name)
        # TODO: when we'll be confident, we will do that automaticaly

    def _update_repository(self):
        """we fetch all latest changes"""
        logging.info('fetching changes')
        self.repo.remote(self.remote_name).fetch("--tags")

        self.git.checkout(DEVELOPMENT_BRANCH)
        self.git.pull(self.remote_name, DEVELOPMENT_BRANCH, '--rebase')

        try:
            self.git.checkout(RELEASE_BRANCH)
            self.git.pull(self.remote_name, RELEASE_BRANCH, '--rebase')
        except GitCommandError as e:
            logging.warning("impossible to checkout {} because {}. We'll try to create the branch".format(
                RELEASE_BRANCH, e))
            self.repo.create_head(RELEASE_BRANCH)


def display_push_release_message(remote_name):
    logging.info("============================================")
    logging.info("Check the release, and when you're happy do:")
    logging.info("  git push {} {} {} --tags".format(remote_name, DEVELOPMENT_BRANCH, RELEASE_BRANCH))


def init_log():
    # TODO better log
    logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))


def release():
    init_log()

    parser = argparse.ArgumentParser(
        description="Used to do a release base on  git flow  of a github project"
                    "The main use of it is to have a nice changelog based on the github pull request merged since last release")
    parser.add_argument('--path', '-p', metavar='PATH', default='.',
                        help='path to the git repository to release')
    parser.add_argument('--release-type', '-r', metavar='RELEASE_TYPE', default='minor', choices=['major', 'minor', 'hotfix'],
                        help='should be "major", "minor" or "hotfix"')
    parser.add_argument('--remote-name', metavar='REMOTE_NAME', default='upstream',
                        help='should be "major", "minor" or "hotfix"name of the git remote')
    parser.add_argument('github_repo', metavar='REPO', default='CanalTP/tartare', nargs='?',
                        help='id of the github repository. should be "organisation/name_of_the repo"')
    parser.add_argument('--github-token', metavar='GITHUB_TOKEN', default=None,
                        help='optional: token to the github user. If not provided the API calls might be limited')
    parser.add_argument('--excluded-pr-tag', metavar='EXCLUDED_PR_TAGS', default=['hotfix', 'not_in_changelog'], nargs='*',
                        help='path to the git repository to release')
    parser.add_argument('--dry-run', '-d', default=False, action='store_true',
                        help='Display changelog without doing the release')

    args = parser.parse_args()
    args.github_token = args.github_token if args.github_token else os.environ.get('GITHUB_API_TOKEN', None)

    try:
        manager = ReleaseManager(**vars(args))
        manager.release()
    except GitCommandError as e:
        if 'CONFLICT' in e.stdout:
            logging.error("============================================")
            logging.error("You have a conflict when merging {} to {}.".format(RELEASE_BRANCH, DEVELOPMENT_BRANCH))
            logging.error("Resolve the conflicts.")
            logging.error("git commit -a")
            display_push_release_message(args.remote_name)

    except Exception as e:
        logging.exception(e)

if __name__ == '__main__':
    release()
