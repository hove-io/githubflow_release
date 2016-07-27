#!/usr/bin/env python
from datetime import datetime
import uuid
import os
from shutil import copyfile
import stat
from clingon import clingon
import codecs
from future.moves import subprocess
import git
from git.exc import GitCommandError
import requests
import semver
import logging

# TODO param this
RELEASE_BRANCH = 'release'


class PullRequest(object):
    def __init__(self, github_api_response):
        self.title = github_api_response['title']
        self.url = github_api_response['html_url']
        self.head_sha1 = github_api_response['head']['sha']
        # we consider that if the pr has a merged_at date, it has been merged
        self.is_merged = github_api_response['merged_at'] is not None
        self.raw_response = github_api_response
        logging.debug('pr: {} -- {}'.format(self.title, self.url))
        self._labels = None

    def fetch_labels(self, auth):
        """ call github to fetch the labels of the pr """
        if not self._labels:
            label_query = self.raw_response['_links']['issue']['href'] + '/labels'
            self._labels = [r['name'] for r in requests.get(label_query, auth=auth).json()]
        return self._labels


class ReleaseManager(object):
    def __init__(self, path, release_type, remote_name, github_repo, github_user, github_token,
                 base_branch, generate_debian_changelog, excluded_pr_tag):
        self.generate_debian_changelog = generate_debian_changelog
        self.excluded_pr_tag = excluded_pr_tag
        self.release_type = release_type
        self.project_path = path
        self.repo = git.Repo(path)
        self.git = self.repo.git
        self.remote_name = remote_name
        self.base_branch = base_branch
        if github_user and github_token:
            self.github_auth = requests.auth.HTTPBasicAuth(github_user, github_token)
        else:
            self.github_auth = None

        # TODO get the remote repos to call (based on git remote -v ?)
        self.github_repository = github_repo
        self.files_to_commit = []  # if some files are created and need to be commit, they are stored here

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
        logging.debug("new tag is {}".format(version))
        pullrequests = self._generate_changelog()
        tmp_branch = self._make_git_release(version, pullrequests)
        self._publish(version, tmp_branch, pullrequests)

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
            # TODO I think we can do better stuff for hotfixes and automatically merge some PR passed as
            # arguments
            # too early to do anything then
            logging.fatal("hotfixes are not implemented yet, it's open source you're welcome to do it")
            exit(2)
            #return semver.bump_hotfix(last_tag)
        else:
            logging.fatal('{} is not a known release type'.format(self.release_type))
            exit(2)

    def _closed_pr_generator(self):
        # lazy get all closed PR ordered by last updated
        page = 1
        while True:
            query = "https://api.github.com/repos/{repo}/pulls?" \
                    "state=closed&base={base_branch}&sort=updated&direction=desc&page={page}"\
                    .format(repo=self.github_repository,
                            base_branch=self.base_branch,
                            latest_tag=self.last_tag,
                            page=page)
            logging.debug("query github api: %s", query)
            github_response = requests.get(query, auth=self.github_auth)

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
            if pr.is_merged:
                branches = self.git.branch('-r', '--contains', pr.head_sha1) + '\n'
                # adding separators before and after to match only branch name
                release_branch_name = ' {remote}/{release}\n'.format(remote=self.remote_name,
                                                                     release=RELEASE_BRANCH)
                if release_branch_name in branches:
                    nb_successive_merged_pr += 1
                    if nb_successive_merged_pr >= 10:
                        break
                else:
                    # doing the label search as late as possible to save api calls
                    labels = pr.fetch_labels(self.github_auth)
                    has_excluded_label = any(l in self.excluded_pr_tag for l in labels)

                    if not has_excluded_label:
                        lines.append(pr)
                        nb_successive_merged_pr = 0
        return lines

    def _generate_changelog(self):
        if self.release_type != "hotfix":
            pullrequests = self._get_merged_pullrequest()
        else:
            # TODO: for hotfixes we'll need to generate a changelog based on the hotfix PRs
            pullrequests = []

        # TODO we could have a way to save the PR in a file to let the user customize it

        logging.info('merged pr:')
        for p in pullrequests:
            logging.info(' {} - {}'.format(p.title, p.url))

        if not pullrequests:
            logging.warning('no changes detected, no release to do')
            exit(0)

        return pullrequests

    def get_parent_branch(self):
        """ get the branch we want to start working on """
        if self.release_type in ["major", "minor"]:
            return self.base_branch
        else:
            return RELEASE_BRANCH

    def _make_git_release(self, version, prs):
        """
        git branch update
        - a temporary branch is created from the base branch
        - if some files have been added, they are commited
        """
        tmp_name = "release_{version}_{rand}".format(version=version, rand=uuid.uuid4())

        parent_branch = self.get_parent_branch()

        #we then create a new temporary branch
        logging.debug("creating temporary release branch {}".format(tmp_name))
        tmp_branch = self.repo.create_head(tmp_name, '{remote}/{parent}'.format(remote=self.remote_name,
                                                                                parent=parent_branch))

        logging.debug("current branch {}".format(self.repo.active_branch))

        if self.generate_debian_changelog:
            self._generate_debian_changelog(prs, version)

        if self.files_to_commit:
            for f in self.files_to_commit:
                self.git.add(f)

            self.git.commit(m="Version {}".format(version))

        return tmp_branch

    def tag(self, version, pullrequests):
        """ tag the git release branch with the version and the changelog """
        tag_message = self.tag_header_format.format(version=version)

        for pr in pullrequests:
            tag_message += self.tag_pr_line_format.format(pr=pr)

        tag_message += self.tag_footer_format.format(version=version)

        logging.info("tag: {}".format(tag_message))

        tag_name = self.tag_name_format.format(version=version)
        self.repo.create_tag(tag_name, ref=RELEASE_BRANCH, message=tag_message)

    def _publish(self, version, tmp_branch, pullrequests):
        #merge with the release branch
        try:
            self.git.checkout(RELEASE_BRANCH)
        except GitCommandError as e:
            logging.warning("impossible to checkout {} because {}. We'll try to create the branch".format(
                RELEASE_BRANCH, e))
            self.repo.create_head(RELEASE_BRANCH)

        self.git.submodule('update')
        self.git.merge(tmp_branch, RELEASE_BRANCH, '--no-ff')

        logging.debug("current branch {}".format(self.repo.active_branch))
        #we tag the release
        self.tag(version, pullrequests)

        #and we merge back the release branch to dev (at least for the tag in release)
        self.git.merge(RELEASE_BRANCH, self.base_branch)

        # we can remove the temporary branch
        logging.info('deleting temporary branch {}'.format(tmp_branch))
        self.repo.delete_head(tmp_branch)

        logging.info("============================================")
        logging.info("Check the release, and when you're happy do:")
        logging.info("  git push {} {} {} --tags".format(self.remote_name, self.base_branch, RELEASE_BRANCH))
        #TODO: when we'll be confident, we will do that automaticaly

    def _update_repository(self):
        """we fetch all latest changes"""
        logging.info('fetching changes')
        self.repo.remote(self.remote_name).fetch("--tags")

    def _generate_debian_changelog(self, pullrequests, version):
        logging.info('generating debian changelog')

        changelog_filename = os.path.join(self.project_path, "debian/changelog")

        for pr in pullrequests:
            changelog = '{title}  <{url}>'.format(title=pr.title, url=pr.url)
            dch = 'dch --newversion "{v}" "{text}"'.format(v=version, text=changelog)
            logging.debug('running : ' + dch)
            os.system('cd {project} && {cmd}; cd -'.format(project=self.project_path, cmd=dch))

        self.files_to_commit.append(changelog_filename)


def init_log():
    # TODO better log
    logging.basicConfig(level=logging.DEBUG)


@clingon.clize
def release(defaults_file='gitflow_release.yml',
            path='.',
            release_type='minor',
            remote_name='upstream',
            github_repo='',
            github_user='',
            github_token='',
            base_branch='master',
            generate_debian_changelog=False,
            excluded_pr_tag=['hotfix', 'not_in_changelog']):
    """
    Used to do a release base on  git flow  of a github project
    The main use of it is to have a nice changelog based on the github pull request merged since last release


    * defaults_file: yaml configuration file used to overload the other parameters
    * path: path to the git repository to release
    * release_type: should be 'major', 'minor' or 'hotfix'
    * remote_name: name of the git remote
    * github_repo: id of the github repository. should be 'organisation/name_of_the repo'
    * github_user: optional: name of the github user. If not provided the API calls might be limited
    * github_token: optional: token to the github user. If not provided the API calls might be limited
    * base_branch: git branch used to create the release branch
    * generate_debian_changelog: boolean used to activate the generation of a debian changelog
    * excluded_pr_tag: list of tags used not to put a given pull request in the changelog
    """
    init_log()

    if release_type == 'hotfix':
        logging.error('hotfixes are not handled for the moment, fell free to make a PR to the script to '
                      'handle them :)')
        return 0

    manager = ReleaseManager(path=path,
                             release_type=release_type,
                             remote_name=remote_name,
                             github_repo=github_repo,
                             github_user=github_user,
                             github_token=github_token,
                             base_branch=base_branch,
                             generate_debian_changelog=generate_debian_changelog,
                             excluded_pr_tag=excluded_pr_tag)
    manager.release()

