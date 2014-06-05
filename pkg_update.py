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
from subprocess import call, Popen, PIPE

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
    return call(cmd, shell=True)


###############
# USAGE INPUT #
###############
if len(sys.argv) < 2 or len(sys.argv) > 3:
    sys.stderr.write("Error: Invalid Arguments\n" +
        "Usage: pkg_update.py <repo> [PROJECT-HOME]\n" +
        "E.g. : pkg_update.py my-repo /home/user/Workspace\n")
    sys.exit(1)

try:
    USER = os.environ['CIRCLE_USER']
except KeyError:
    sys.stderr.write("Error: CIRCLE_USER has not been sets\n" +
        "Please add `CIRCLE_USER` in your system environment variable")
    sys.exit(1)

try:
    TOKEN = os.environ['CIRCLE_TOKEN']
except KeyError:
    sys.stderr.write("Error: CIRCLE_TOKEN has not been sets\n" +
        "Please add `CIRCLE_TOKEN` in your system environment variable")
    sys.exit(1)

try:
    GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
except KeyError:
    sys.stderr.write("Error: GITHUB_TOKEN has not been sets\n" +
        "Please add `GITHUB_TOKEN` in your system environment variable")
    sys.exit(1)

TEMPORARY_BRANCH = 'pkg-update'


##################
# Repo Directory #
##################
try:
    WORKSPACE = sys.argv[2]
except IndexError as e:
    try:
        WORKSPACE = os.environ['WORKSPACE']
    except KeyError as e:
        WORKSPACE = os.path.join(os.environ['HOME'], 'Workspace')
REPO = sys.argv[1]
REPO_DIR = os.path.join(WORKSPACE, REPO)

##########################
# POST SCRIPT DELAY TIME #
##########################
POST_SCRIPT_DELAY = 6 # in second

#####################
# PRE UPDATE SCRIPT #
#####################
def pre_update():
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
            'user': USER,
            'repo': REPO,
        }
        sh("git clone git@github.com:{user}/{repo}.git".format(**data))
        os.chdir(REPO_DIR)
        logging.info("Cloning the repository")

    logging.info("Recreating {branch} branch".format(branch=TEMPORARY_BRANCH))
    sh("git checkout -B {branch}".format(branch=TEMPORARY_BRANCH))

    logging.info("Installing new package when required")
    sh("bundle install")

    logging.info("Updating Package")
    sh("bundle update")

    logging.info("Committing Frozen Package File")
    sh("git add Gemfile.lock")
    commit_message = "Auto Commit: Package Update"
    sh("git commit -m '{msg}'".format(msg=commit_message))

    logging.info("Force Push {} remote branch".format(TEMPORARY_BRANCH))
    sh("git push -u origin {} --force".format(TEMPORARY_BRANCH))

    sh("git checkout master")
    logging.info("Done with Branching, proceed with testing on CI now")

####################################################
# CHECK CIRCLE CI TEST STATUS ON A SEPARATE BRANCH #
####################################################
def is_test_pass(user, repo, branch, token):
    data = {
        'user': user,
        'repo': repo,
        'branch': branch,
        'token': token,
        'limit': 1,
    }
    circle_ci_resource = 'https://circleci.com/api/v1/'
    target_path = "project/{user}/{repo}/tree/{branch}?" \
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
        logging.info("Bundle Update Fail the test")
        return False

###############################
# CREATE A MERGE PULL REQUEST #
###############################
def create_pull_request(USER, REPO, TEMPORARY_BRANCH, GITHUB_TOKEN):
    github_resource = 'https://api.github.com/'

    # https://developer.github.com/v3/pulls/#create-a-pull-request
    # POST /repos/:owner/:repo/pulls
    target_path = "repos/{owner}/{repo}/pulls".format(owner=USER, repo=REPO)
    url = urlparse.urljoin(github_resource, target_path)
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': 'token ' + GITHUB_TOKEN
    }
    post_data = json.dumps({
        "title": "Merge Package Update",
        "body": "This is an automated merge request.",
        "head": TEMPORARY_BRANCH,
        "base": "master"
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
def post_update(USER, REPO, TEMPORARY_BRANCH, TOKEN, GITHUB_TOKEN):
    logging.info("Starting Post Script")
    if is_test_pass(USER, REPO, TEMPORARY_BRANCH, TOKEN):
        create_pull_request(USER, REPO, TEMPORARY_BRANCH, GITHUB_TOKEN)
    logging.info("That's all, bye")


pre_update()
execute_later(
        func=post_update,
        delay=POST_SCRIPT_DELAY,
        args=(USER, REPO, TEMPORARY_BRANCH, TOKEN, GITHUB_TOKEN)
)
