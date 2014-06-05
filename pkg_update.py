#!/usr/bin/python
import os
import sys
import json
import time
import sched
import urllib
import urllib2
import urlparse
import logging
from subprocess import call, Popen, PIPE, check_call

############
# LOG FILE #
############
logging.basicConfig(filename='pkg-update.log',
        format="[%(filename)s] [%(asctime)s] %(levelname)s: %(message)s",
        level=logging.INFO)

##################
# HELPER METHODS #
##################
def execute_later(func, delay, args=[]):
    """Delay execution for later"""
    logging.info("Will check the post test result 1 hour later")
    s = sched.scheduler(time.time, time.sleep)
    s.enter(delay, 0, func, args)
    s.run()

def sh(cmd):
    """Just execute shell command line"""
    print("#>>> {}".format(cmd))
    process = Popen(cmd, shell=True, stdout=PIPE)
    stdout, stderr = process.communicate()
    if stdout:
        logging.info(stdout)
    if stderr:
        logging.error(stderr)
    return (stdout, stderr)


###############
# USAGE INPUT #
###############
if len(sys.argv) < 2 or len(sys.argv) > 4:
    sys.stderr.write("Error: Invalid Arguments\n" +
        "Usage: pkg_update.py <repo> [PROJECT-HOME]\n" +
        "E.g. : pkg_update.py my-repo /home/user/Workspace\n")
    sys.exit(1)

##############
# REPOSITORY #
##############
project_owner = sys.argv[1]
project_repo = sys.argv[2]


#########
# TOKEN #
#########
github_token = os.getenv('GITHUB_TOKEN')
ci_token = os.getenv('CIRCLE_TOKEN')
if ci_token is None:
    raise Exception("Please set the CIRCLE_TOKEN environment variable")
if github_token is None:
    raise Exception("Please set the GITHUB_TOKEN environment variable")

##################
# Repo Directory #
##################
try:
    WORKSPACE = sys.argv[3]
except IndexError as e:
    try:
        WORKSPACE = os.environ['WORKSPACE']
    except KeyError as e:
        WORKSPACE = os.path.join(os.environ['HOME'], 'Workspace')
REPO_DIR = os.path.join(WORKSPACE, project_repo)

##########################
# POST SCRIPT DELAY TIME #
##########################
POST_SCRIPT_DELAY = 6 # in second

#####################
# PRE UPDATE SCRIPT #
#####################
def pre_update(vcs):
    logging.info("Start Package Update Script")

    SCRIPT_PATH = os.getcwd()
    if os.path.exists(REPO_DIR):
        os.chdir(REPO_DIR)
        logging.info("Pulling the latest master branch")
        sh("git checkout master")
        sh("git pull")
    else:
        os.chdir(WORKSPACE)
        data = {
            'owner': vcs.owner,
            'repo': vcs.repo,
        }
        sh("git clone git@github.com:{owner}/{repo}.git".format(**data))
        os.chdir(REPO_DIR)
        logging.info("Cloning the repository")

    logging.info("Recreating {branch} branch".format(branch=vcs.pkg_branch))
    sh("git checkout -B {branch}".format(branch=vcs.pkg_branch))

    logging.info("Installing new package when required")
    sh("bundle install")

    logging.info("Updating Package")
    sh("bundle update")

    logging.info("Committing Frozen Package File")
    sh("git add Gemfile.lock")
    commit_message = "Auto Commit: Package Update"
    sh("git commit -m '{msg}'".format(msg=commit_message))

    logging.info("Force Push {} remote branch".format(vcs.pkg_branch))
    sh("git push -u origin {} --force".format(vcs.pkg_branch))

    sh("git checkout master")
    logging.info("Done with Branching, proceed with testing on CI now")

####################################################
# CHECK CIRCLE CI TEST STATUS ON A SEPARATE BRANCH #
####################################################
def is_test_pass(ci, vcs):
    data = {
        'owner': vcs.owner,
        'repo': vcs.repo,
        'branch': vcs.pkg_branch,
        'token': ci.token,
        'limit': 1,
    }
    circle_ci_resource = 'https://circleci.com/api/v1/'
    target_path = "project/{owner}/{repo}/tree/{branch}?" \
                  "circle-token={token}&limit={limit}".format(**data)
    url = urlparse.urljoin(circle_ci_resource, target_path)
    headers = {'Accept': 'application/json'}
    req = urllib2.Request(url, headers=headers)
    try:
        resp = urllib2.urlopen(req)
    except urllib2.HTTPError as e:
        logging.error(e.code)
        return False
    except urllib2.URLError as e:
        logging.error(e.args)
        return False
    else:
        data = json.load(resp)

    try:
        last_build = data[0]
    except IndexError as e:
        logging.warning("No last build found")
        return False

    if last_build.get('status') is 'success':
        logging.info("Last test build passed")
        return True
    else:
        logging.warning("Bundle Update Fail the test")
        return False

###############################
# CREATE A MERGE PULL REQUEST #
###############################
def create_pull_request(vcs):
    github_resource = 'https://api.github.com/'

    # https://developer.github.com/v3/pulls/#create-a-pull-request
    # POST /repos/:owner/:repo/pulls
    target_path = "repos/{owner}/{repo}/pulls".format(owner=vcs.owner,
            repo=vcs.repo)
    url = urlparse.urljoin(github_resource, target_path)
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': 'token ' + vcs.token
    }
    post_data = json.dumps({
        "title": "Merge Package Update",
        "body": "This is an automated merge request.",
        "head": vcs.pkg_branch,
        "base": vcs.base_branch
    })
    req = urllib2.Request(url, data=post_data, headers=headers)
    try:
        resp = urllib2.urlopen(req)
    except urllib2.HTTPError as e:
        logging.error(e.code)
        logging.error(e.read())
        return False
    except urllib2.URLError as e:
        logging.error(e.args)
        return False
    else:
        logging.info("Pull request Created")
    return json.load(resp)

######################
# POST UPDATE SCRIPT #
######################
def post_update(vcs, ci):
    logging.info("Starting Post Script")
    if is_test_pass(ci, vcs):
        create_pull_request(vcs)
    logging.info("That's all, bye")


###################
# START EXECUTION #
###################
def update_pkg(vcs, ci):
    pre_update(vcs)
    execute_later(
            func=post_update,
            delay=POST_SCRIPT_DELAY,
            args=(vcs, ci)
    )

class CircleCIAccount(object):
    def __init__(self, token):
        self.token = token


class GithubAccount(object):
    def __init__(self, project_owner, project_repo, token,
            pkg_branch='pkg-update', base_branch='master'):
        self.owner = project_owner
        self.repo = project_repo
        self.token = token
        self.pkg_branch = pkg_branch
        self.base_branch = base_branch

vcs = GithubAccount(project_owner, project_repo, github_token)
ci = CircleCIAccount(ci_token)
update_pkg(vcs, ci)
