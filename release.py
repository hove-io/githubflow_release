#!/usr/bin/env python
from clingon import clingon
import git
from git.exc import GitCommandError
import requests
import semver
import logging


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

    def fetch_labels(self, auth):
        """ call github to fetch the labels of the pr """
        return []
        #label_query = self.raw_response['_links']['issue']['href'] + '/labels'
        #return requests.get(label_query, auth=auth).json()


class ReleaseManager(object):
    def __init__(self, path, release_type, remote_name, github_user, github_token):
        self.release_type = release_type
        self.repo = git.Repo(path)
        self.git = self.repo.git
        self.remote_name = remote_name
        if github_user and github_token:
            # TODO auth
            self.github_auth = requests.auth.HTTPBasicAuth(github_user, github_token)
        else:
            self.github_auth = None

        # TODO get the remote repos to call (based on git remote -v ?) + default branch
        self.github_repository = 'CanalTP/navitia'
        self.base_branch = 'dev'

    def release(self):
        logging.info("release {}".format(self.release_type))
        version = self._get_new_version_number()
        logging.debug("new tag is {}".format(version))
        changelog = self._generate_changelog()
        self._make_git_release(version, changelog)
        self._publish()

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
                    has_excluded_label = any(l['name'] in ("hotfix", "not_in_changelog") for l in labels)

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

        logging.info('merged pr:')
        for p in pullrequests:
            logging.info(' {} - {}'.format(p.title, p.url))

        return pullrequests

    def _make_git_release(self, version, changelog):
        pass

    def _publish(self):
        pass


def init_log():
    # TODO better log
    logging.basicConfig(level=logging.DEBUG)


@clingon.clize
def release(path='.', release_type='minor', remote_name='origin', github_user='', github_token=''):
    init_log()
    manager = ReleaseManager(path, release_type, remote_name, github_user, github_token)
    manager.release()

