from clingon import clingon
import git

class ReleaseManager(object):
    def __init__(self, release_type):
        self.release_type = release_type
        self.repo = git.Repo(".")
        self.git = self.repo.git

    def release(self):
        print("release {}".format(self.release_type))
        version = self.get_new_version_number()
        changelog = self.generate_changelog()
        self.make_git_release(version, changelog)
        self.publish()

    def get_new_version_number(self):
        last_tag = self.git.describe("--tags", abbrev=0)
        print("tag = {}".format(last_tag))

    def generate_changelog(self):
        pass

    def make_git_release(self, version, changelog):
        pass

    def publish(self):
        pass


@clingon.clize
def release(release_type):
    manager = ReleaseManager(release_type)
    manager.release()

