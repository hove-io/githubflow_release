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


def write_debian_changelog(write_lines, project_path):
    changelog_path = "debian/changelog"
    changelog_filename = os.path.join(project_path, changelog_path)
    f_changelog = None
    if os.path.exists(changelog_filename):
        try:
            f_changelog = codecs.open(changelog_filename, 'r', 'utf-8')
        except IOError:
            logging.error("Unable to open debian/changelog")
            exit(1)
    else:
        # no previous changelog
        os.makedirs(os.path.dirname(changelog_filename), exist_ok=True)

    back_filename = changelog_filename + "~"
    f_changelogback = codecs.open(back_filename, "w", "utf-8")

    for line in write_lines:
        f_changelogback.write(line)

    for line in f_changelog or []:
        f_changelogback.write(line)

    if f_changelog is not None:
        f_changelog.close()
    f_changelogback.close()
    _, _ = subprocess.Popen(["vim", back_filename, "--nofork"],
                            stderr=subprocess.PIPE).communicate()

    copyfile(back_filename, changelog_filename)
    return changelog_filename


class ReleaseManager(object):
    def __init__(self, path, release_type, remote_name, github_repo, github_user, github_token, base_branch):
        self.generate_debian_changelog = True
        self.release_type = release_type
        self.project_path = path
        self.repo = git.Repo(path)
        self.git = self.repo.git
        self.remote_name = remote_name
        self.base_branch = base_branch
        if github_user and github_token:
            # TODO auth
            self.github_auth = requests.auth.HTTPBasicAuth(github_user, github_token)
        else:
            self.github_auth = None

        # TODO get the remote repos to call (based on git remote -v ?)
        self.github_repository = github_repo
        self.files_to_commit = []  # if some files are created and need to be commit, they are stored here

        """ Tag format configuration """
        self.tag_header_format = 'Version {version}\n\n'  # can be formated with {version}
        self.tag_pr_line_format = ' * {pr.title}  <{pr.url}>\n'  # can be formated with {pr}
        self.tag_name_format = 'v{version}'  # can be formated with {version}
        self.tag_footer_format = ''

    def release(self):
        logging.info("release {}".format(self.release_type))
        self._update_repository()
        version = self._get_new_version_number()
        logging.debug("new tag is {}".format(version))
        pullrequests = self._generate_changelog(version)
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
                    has_excluded_label = any(l in ("hotfix", "not_in_changelog") for l in labels)

                    if not has_excluded_label:
                        lines.append(pr)
                        nb_successive_merged_pr = 0
        return lines

    def _generate_changelog(self, version):

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

    def checkout_parent_branch(self):
        if self.release_type in ["major", "minor"]:
            parent = self.base_branch
        else:
            parent = RELEASE_BRANCH

        self.git.checkout(parent)
        self.git.submodule('update')

        logging.debug("current branch {}".format(self.repo.active_branch))

    def _make_git_release(self, version, prs):
        """
        git branch update
        - a temporary branch is created from the base branch
        - if some files have been added, they are commited
        """
        tmp_name = "release_{version}_{rand}".format(version=version, rand=uuid.uuid4())

        self.checkout_parent_branch()

        #we then create a new temporary branch
        logging.debug("creating temporary release branch {}".format(tmp_name))
        self.git.checkout(b=tmp_name)
        logging.debug("current branch {}".format(self.repo.active_branch))

        if self.generate_debian_changelog:
            self._generate_debian_changelog(prs, version)

        for f in self.files_to_commit:
            self.git.add(f)

        self.git.commit(m="Version {}".format(version))

        return tmp_name

    def tag(self, version, pullrequests):
        """ tag the git release branch with the version and the changelog """
        tag_message = self.tag_header_format.format(version=version)

        for pr in pullrequests:
            tag_message += self.tag_pr_line_format.format(pr=pr)

        tag_message += self.tag_footer_format.format(version=version)

        logging.info("tag: {}".format(tag_message))

        tag_name = self.tag_name_format.format(version=version)
        self.repo.create_tag(tag_name, message=tag_message)

    def _publish(self, version, tmp_branch, pullrequests):

        self.git.checkout(RELEASE_BRANCH)
        self.git.submodule('update')
        #merge with the release branch
        self.git.merge(tmp_branch, RELEASE_BRANCH, '--no-ff')

        logging.debug("current branch {}".format(self.repo.active_branch))
        #we tag the release
        self.tag(version, pullrequests)

        #and we merge back the release branch to dev (at least for the tag in release)
        self.git.merge(RELEASE_BRANCH, self.base_branch, '--no-ff')

        logging.info("publishing the release")

        logging.info("Check the release, you will probably want to merge release in dev:")
        logging.info("  git checkout {}; git submodule update".format(self.base_branch))
        logging.info("  git merge {}".format(RELEASE_BRANCH))
        logging.info("And when you're happy do:")
        logging.info("  git push {} {} {} --tags".format(self.remote_name, self.base_branch, RELEASE_BRANCH))
        #TODO: when we'll be confident, we will do that automaticaly

    def _update_repository(self):
        """we fetch all latest changes"""
        logging.info('fetching changes')
        self.repo.remote(self.remote_name).fetch("--tags")

    def _generate_debian_changelog(self, pullrequests, version):
        logging.info('generating debian changelog')

        write_lines = [
            u'{project} ({version}) unstable; urgency=low\n'.format(project='', version=version),
            u'\n',
        ]
        for pr in pullrequests:
            write_lines.append(u'  * {title}  <{url}>\n'.format(title=pr.title, url=pr.url))

        author_name = self.git.config('user.name')
        author_mail = self.git.config('user.email')
        write_lines.extend([
            u'\n',
            u' -- {name} <{mail}>  {now} +0100\n'
                .format(name=author_name, mail=author_mail,
                        now=datetime.now().strftime("%a, %d %b %Y %H:%m:%S")),
            u'\n',
        ])

        changelog = write_debian_changelog(write_lines, self.project_path)
        self.files_to_commit.append(changelog)


def init_log():
    # TODO better log
    logging.basicConfig(level=logging.DEBUG)


@clingon.clize
def release(path='.',
            release_type='minor',
            remote_name='origin',
            github_repo='CanalTP/navitia',
            github_user='',
            github_token='',
            base_branch='master'):
    init_log()
    manager = ReleaseManager(path, release_type, remote_name, github_repo, github_user, github_token,
                             base_branch)
    manager.release()

